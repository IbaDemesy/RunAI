"""Transcription en direct Gladia (solaria-1) et flux d'événements voix → commandes."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from time import perf_counter
from typing import Any

import runai.config  # noqa: F401  (charge le .env avant le SDK Gladia, qui lit la clé à l'import)
from runai.telemetry import timed
from runai.voice.audio import AudioStream
from runai.voice.commands import CommandDetector
from runai.voice.models import TranscriptEvent, VoiceEvent
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
) -> dict[str, Any]:
    """Corps de POST /v2/live (dict brut, envoyé tel quel par le SDK)."""
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
            "receive_speech_events": False,
            "receive_errors": True,
        },
    }
    if entries:
        options["realtime_processing"] = {
            "custom_vocabulary": True,
            "custom_vocabulary_config": {"vocabulary": entries, "default_intensity": vocabulary_intensity},
        }
    return options


def default_client() -> Any:
    from gladiaio_sdk import GladiaClient

    return GladiaClient().live_v2_async()


def to_transcript_event(message: Any) -> TranscriptEvent:
    data = message.data
    utterance = data.utterance
    return TranscriptEvent(
        utterance_id=data.id,
        text=utterance.text,
        is_final=data.is_final,
        language=utterance.language,
        start=utterance.start,
        end=utterance.end,
        confidence=utterance.confidence,
    )


async def stream_transcripts(
    chunks: AsyncIterable[bytes],
    *,
    sample_rate: int = 16000,
    client: Any = None,
    options: dict[str, Any] | None = None,
) -> AsyncIterator[TranscriptEvent]:
    """Envoie l'audio à Gladia au fil de l'eau et produit les transcriptions partielles et finales."""
    async with timed("gladia", "live.transcribe", audio_s=0, n_final_utterances=0) as call:
        client = client or default_client()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        errors: list[Exception] = []
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
                        raise VoiceError(f"Session Gladia terminée (code {code})") from (errors[-1] if errors else None)
                    break
                if getattr(item, "type", None) == "transcript":
                    event = to_transcript_event(item)
                    if event.is_final:
                        call.meta["n_final_utterances"] += 1
                    elif "time_to_first_partial_ms" not in call.meta:
                        call.meta["time_to_first_partial_ms"] = (perf_counter() - call.start) * 1000
                    yield event
            if feeder.done() and not feeder.cancelled() and feeder.exception():
                raise VoiceError("Lecture audio interrompue") from feeder.exception()
        finally:
            if not feeder.done():
                feeder.cancel()
            session.end_session()


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
