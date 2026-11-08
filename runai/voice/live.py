"""Transcription en direct Gladia (solaria-1) et flux d'événements voix → commandes."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from time import perf_counter
from typing import Any

import runai.config  # noqa: F401  (charge le .env avant le SDK Gladia, qui lit la clé à l'import)
from runai.telemetry import timed
from runai.voice.audio import AudioStream
from runai.voice.commands import CommandDetector
from runai.voice.models import (
    EntitiesEvent,
    Entity,
    SpeechEvent,
    TranscriptEvent,
    TranslationEvent,
    VoiceEvent,
    WarningEvent,
)
from runai.voice.vocabulary import gladia_vocabulary

DEFAULT_LANGUAGES = ("fr", "en", "pt")
# Les pauses partent sur les partiels : un endpointing un peu long ne retarde pas l'arrêt et
# évite de couper « Non, attends… plutôt un hôtel près du départ » en deux énoncés.
DEFAULT_ENDPOINTING = 0.3
_ENDED = object()


class VoiceError(RuntimeError):
    pass


def build_live_options(
    sample_rate: int = 16000,
    *,
    languages: Iterable[str] = DEFAULT_LANGUAGES,
    vocabulary: list[dict] | None = None,
    endpointing: float = DEFAULT_ENDPOINTING,
    vocabulary_intensity: float = 0.4,
    translate_to: str | None = "en",
    ner: bool = True,
    speech_events: bool = True,
) -> dict[str, Any]:
    """Build the live session payload, sent unchanged by the Gladia SDK."""
    languages = list(languages)
    entries = [
        entry if entry.get("language") in (None, *languages) else {k: v for k, v in entry.items() if k != "language"}
        for entry in (gladia_vocabulary() if vocabulary is None else vocabulary)
    ]
    options: dict[str, Any] = {
        "model": "solaria-1",
        "encoding": "wav/pcm",
        "bit_depth": 16,
        "sample_rate": sample_rate,
        "channels": 1,
        "endpointing": endpointing,
        "maximum_duration_without_endpointing": 15,
        "language_config": {"languages": languages, "code_switching": len(languages) > 1},
        "messages_config": {
            "receive_partial_transcripts": True,
            "receive_final_transcripts": True,
            "receive_speech_events": speech_events,
            "receive_realtime_processing_events": bool(translate_to or ner),
            "receive_errors": True,
        },
    }
    processing: dict[str, Any] = {}
    if entries:
        processing.update({
            "custom_vocabulary": True,
            "custom_vocabulary_config": {"vocabulary": entries, "default_intensity": vocabulary_intensity},
        })
    if translate_to:
        processing.update({
            "translation": True,
            "translation_config": {
                "target_languages": [translate_to],
                "model": "base",
                "match_original_utterances": True,
            },
        })
    if ner:
        processing["named_entity_recognition"] = True
    if processing:
        options["realtime_processing"] = processing
    return options


def default_client() -> Any:
    from gladiaio_sdk import GladiaClient

    return GladiaClient().live_v2_async()


def to_transcript_event(message: Any, *, revision: int = 1) -> TranscriptEvent:
    data = message.data
    utterance = data.utterance
    return TranscriptEvent(
        utterance_id=data.id,
        revision=revision,
        text=utterance.text,
        is_final=data.is_final,
        language=utterance.language,
        start=utterance.start,
        end=utterance.end,
        confidence=utterance.confidence,
    )


def _utterance_key(utterance: Any) -> tuple[int, float, float] | None:
    if utterance is None:
        return None
    return (getattr(utterance, "channel", 0), utterance.start, utterance.end)


async def stream_voice_events(
    chunks: AsyncIterable[bytes],
    *,
    sample_rate: int = 16000,
    client: Any = None,
    options: dict[str, Any] | None = None,
) -> AsyncIterator[VoiceEvent]:
    """Emit one typed event per transcript, translation, NER or speech message.

    Lifecycle/acknowledgement messages and aggregate post-final transcripts are
    ignored: they must not duplicate the per-utterance updates. SDK messages are
    frozen dataclasses, read through their attributes rather than model_dump().
    Addons sometimes use a numeric ID instead of the transcript ID. Match their
    original utterance's channel/timestamps, buffering early addons until the
    corresponding transcript arrives. Unmatched addons retain their provider ID
    at session end rather than being silently lost.
    """
    async with timed("gladia", "live.transcribe", audio_s=0, n_final_utterances=0) as call:
        client = client or default_client()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        errors: list[Exception] = []
        revisions: dict[str, int] = {}
        utterance_ids: dict[tuple[int, float, float], str] = {}
        pending: list[tuple[TranslationEvent | EntitiesEvent, tuple[int, float, float] | None]] = []
        session = client.start_session(options or build_live_options(sample_rate))
        session.on("message", queue.put_nowait)
        session.on("error", errors.append)
        session.on("ended", lambda ended: queue.put_nowait((_ENDED, ended)))

        async def feed() -> None:
            try:
                async for chunk in chunks:
                    session.send_audio(chunk)
                    call.meta["audio_s"] += len(chunk) / (sample_rate * 2)
            finally:
                session.stop_recording()

        feeder = asyncio.create_task(feed())
        try:
            while True:
                item = await queue.get()
                if isinstance(item, tuple) and item and item[0] is _ENDED:
                    code = getattr(item[1], "code", 1000)
                    if code != 1000:
                        raise VoiceError(f"Gladia session ended abnormally (code {code})") from (errors[-1] if errors else None)
                    break
                message_type = getattr(item, "type", None)
                data = getattr(item, "data", None)
                if message_type == "transcript":
                    revision = revisions.get(data.id, 0) + 1
                    revisions[data.id] = revision
                    key = _utterance_key(data.utterance)
                    if key is not None:
                        utterance_ids[key] = data.id
                    event = to_transcript_event(item, revision=revision)
                    if event.is_final:
                        call.meta["n_final_utterances"] += 1
                    elif "time_to_first_partial_ms" not in call.meta:
                        call.meta["time_to_first_partial_ms"] = (perf_counter() - call.start) * 1000
                    yield event
                    remaining = []
                    for event, key in pending:
                        uid = event.utterance_id if event.utterance_id in revisions else utterance_ids.get(key)
                        if uid is None:
                            remaining.append((event, key))
                        else:
                            yield event.model_copy(update={"utterance_id": uid})
                    pending = remaining
                elif message_type in ("translation", "named_entity_recognition"):
                    if getattr(item, "error", None) is not None or data is None:
                        yield WarningEvent(
                            event_type=message_type,
                            message=f"Gladia {message_type} failed; transcription continues.",
                        )
                        continue
                    key = _utterance_key(data.utterance)
                    uid = data.utterance_id if data.utterance_id in revisions else utterance_ids.get(key)
                    addon: TranslationEvent | EntitiesEvent
                    if message_type == "translation":
                        addon = TranslationEvent(
                            utterance_id=data.utterance_id,
                            source_language=data.original_language,
                            target_language=data.target_language,
                            text=data.translated_utterance.text,
                        )
                    else:
                        addon = EntitiesEvent(
                            utterance_id=data.utterance_id,
                            entities=[
                                Entity(type=result.entity_type, text=result.text, start=result.start, end=result.end)
                                for result in data.results
                            ],
                        )
                    if uid is None:
                        pending.append((addon, key))
                    else:
                        yield addon.model_copy(update={"utterance_id": uid})
                elif message_type in ("speech_start", "speech_end"):
                    yield SpeechEvent(kind="start" if message_type == "speech_start" else "end", time=data.time)
            for event, _ in pending:
                yield event
            if feeder.done() and not feeder.cancelled() and feeder.exception():
                raise VoiceError("Audio input interrupted") from feeder.exception()
        finally:
            if not feeder.done():
                feeder.cancel()
            session.end_session()


async def stream_transcripts(
    chunks: AsyncIterable[bytes],
    *,
    sample_rate: int = 16000,
    client: Any = None,
    options: dict[str, Any] | None = None,
) -> AsyncIterator[TranscriptEvent]:
    """Keep transcript-only consumers independent of Gladia addon events."""
    async for event in stream_voice_events(chunks, sample_rate=sample_rate, client=client, options=options):
        if isinstance(event, TranscriptEvent):
            yield event


async def stream_events(
    audio: AudioStream,
    *,
    detector: CommandDetector | None = None,
    client: Any = None,
    options: dict[str, Any] | None = None,
) -> AsyncIterator[VoiceEvent]:
    """Flux consommable par l'app web : chaque transcription, suivie des commandes qu'elle déclenche."""
    detector = detector or CommandDetector()
    async for transcript in stream_transcripts(
        audio.chunks, sample_rate=audio.sample_rate, client=client, options=options
    ):
        yield transcript
        for command in detector.feed(transcript):
            yield command
