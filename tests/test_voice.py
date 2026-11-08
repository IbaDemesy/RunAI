import asyncio
import io
import json
import wave
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from runai.voice import (
    CommandDetector,
    CommandKind,
    CommandSource,
    CorrectionTarget,
    EntitiesEvent,
    SpeechEvent,
    TranscriptEvent,
    TranslationEvent,
    WarningEvent,
    audio,
    command_from_text,
    extract_race,
    parse_command,
)
from runai.voice.audio import AudioStream, chunk_size, load_pcm, pcm_chunks
from runai.voice.live import (
    VoiceError,
    build_live_options,
    stream_events,
    stream_transcripts,
    stream_voice_events,
)
from runai.voice.vocabulary import HALF_MARATHON_KM, MARATHON_KM


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Inscris-moi au semi de Lisbonne", CommandKind.new_mission),
        ("Je veux courir la Meia Maratona de Lisboa", CommandKind.new_mission),
        ("Sign me up for the Milano Marathon", CommandKind.new_mission),
        ("Quero correr a meia maratona de Lisboa", CommandKind.new_mission),
        ("Non, attends !", CommandKind.pause),
        ("Stop", CommandKind.pause),
        ("Wait", CommandKind.pause),
        ("Reprends", CommandKind.resume),
        ("C'est bon, tu peux reprendre", CommandKind.resume),
        ("Pode continuar", CommandKind.resume),
        ("Change la date", CommandKind.correction),
        ("Plutôt un hôtel près du départ", CommandKind.correction),
        ("Actually, a cheaper flight", CommandKind.correction),
        ("Annule tout", CommandKind.cancel),
        ("Laisse tomber", CommandKind.cancel),
        ("Cancela tudo", CommandKind.cancel),
    ],
)
def test_parse_command_kinds(text, kind):
    assert parse_command(text).kind is kind


@pytest.mark.parametrize("text", ["", "bonjour", "J'attends la confirmation", "J'arrive à 10 km du départ"])
def test_parse_command_ignores_small_talk(text):
    assert parse_command(text) is None


def test_new_mission_extracts_race_hints():
    race = parse_command("Inscris-moi au semi de Lisbonne").race
    assert (race.name, race.city, race.country, race.distance_km) == (None, "Lisbon", "PT", HALF_MARATHON_KM)


def test_official_name_and_date_are_kept():
    race = extract_race("Je veux courir la Meia Maratona de Lisboa le 8 mars 2027")
    assert race.name == "Meia Maratona de Lisboa"
    assert race.date_text == "8 mars 2027"


def test_marathon_and_km_distances():
    assert extract_race("le marathon de Milan").distance_km == MARATHON_KM
    assert extract_race("un 10 km à Paris").distance_km == 10.0
    assert extract_race("bonjour") is None


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("Change la date", CorrectionTarget.date),
        ("Non, le 15 mars", CorrectionTarget.date),
        ("Plutôt un hôtel près du départ", CorrectionTarget.accommodation),
        ("En fait, un vol moins cher", CorrectionTarget.transport),
        ("Plutôt un budget de 300 euros", CorrectionTarget.budget),
        ("Non, plutôt le marathon de Milan", CorrectionTarget.race),
        ("Plutôt autre chose", CorrectionTarget.other),
    ],
)
def test_correction_targets(text, target):
    command = parse_command(text)
    assert command.kind is CommandKind.correction
    assert command.target is target
    assert command.detail == text


def test_cancel_can_target_one_step():
    command = parse_command("Annule l'hôtel")
    assert (command.kind, command.target) == (CommandKind.cancel, CorrectionTarget.accommodation)


def _transcript(text, is_final, uid="u1"):
    return TranscriptEvent(utterance_id=uid, text=text, is_final=is_final, language="fr")


def test_keyboard_and_voice_produce_the_same_command():
    text = "Plutôt un hôtel près du départ"
    typed = command_from_text(text)
    spoken = CommandDetector().feed(_transcript(text, is_final=True))[0]
    assert typed.command == spoken.command
    assert (typed.source, spoken.source) == (CommandSource.keyboard, CommandSource.voice)


def test_detector_pauses_early_on_partial_once():
    detector = CommandDetector()
    first = detector.feed(_transcript("Non, attends", is_final=False))
    assert [(e.command.kind, e.early) for e in first] == [(CommandKind.pause, True)]
    assert detector.feed(_transcript("Non, attends, plutôt", is_final=False)) == []
    final = detector.feed(_transcript("Non, attends, plutôt un hôtel près du départ", is_final=True))
    assert [e.command.kind for e in final] == [CommandKind.correction]


def test_detector_skips_duplicate_final_pause():
    detector = CommandDetector()
    detector.feed(_transcript("Stop", is_final=False))
    assert detector.feed(_transcript("Stop.", is_final=True)) == []
    assert detector.feed(_transcript("Stop.", is_final=True, uid="u2"))[0].command.kind is CommandKind.pause


def test_pause_word_mid_sentence_is_not_a_barge_in():
    text = "Since I have a new job, I don't stop"
    detector = CommandDetector()
    assert detector.feed(_transcript(text, is_final=False)) == []
    assert parse_command(text) is None


def test_long_conversation_is_not_a_command():
    text = "I've been working all day since yesterday, " * 5 + "et finalement on change la date"
    assert parse_command(text) is None


def test_detector_waits_for_final_for_other_commands():
    detector = CommandDetector()
    assert detector.feed(_transcript("Annule", is_final=False)) == []
    assert detector.feed(_transcript("Annule tout", is_final=True))[0].command.kind is CommandKind.cancel


def test_command_event_to_trace_event():
    trace = command_from_text("Annule tout").to_trace_event()
    assert (trace.source, trace.type, trace.message) == ("keyboard", "command.cancel", "Annule tout")
    assert trace.data["command"]["kind"] == "cancel"


def test_build_live_options():
    options = build_live_options(16000)
    assert options["model"] == "solaria-1"
    assert options["language_config"] == {"languages": ["fr", "en", "pt"], "code_switching": True}
    assert options["messages_config"]["receive_partial_transcripts"] is True
    assert options["messages_config"]["receive_speech_events"] is True
    assert options["messages_config"]["receive_realtime_processing_events"] is True
    processing = options["realtime_processing"]
    assert processing["translation"] is True
    assert processing["translation_config"] == {
        "target_languages": ["en"], "model": "base", "match_original_utterances": True,
    }
    assert processing["named_entity_recognition"] is True
    vocabulary = options["realtime_processing"]["custom_vocabulary_config"]["vocabulary"]
    values = {entry["value"] for entry in vocabulary}
    assert {"Lisbonne", "Lisboa", "Meia Maratona de Lisboa", "Milano Marathon", "Njuko"} <= values
    assert all(entry.get("language") in (None, "fr", "en", "pt") for entry in vocabulary)
    json.dumps(options)


def test_build_live_options_single_language_without_vocabulary():
    options = build_live_options(
        8000, languages=["fr"], vocabulary=[], translate_to=None, ner=False, speech_events=False,
    )
    assert options["language_config"]["code_switching"] is False
    assert "realtime_processing" not in options
    assert options["messages_config"]["receive_realtime_processing_events"] is False
    assert options["messages_config"]["receive_speech_events"] is False


def test_build_live_options_addons_are_independent():
    translated = build_live_options(vocabulary=[], translate_to="pt", ner=False, speech_events=False)
    assert translated["realtime_processing"]["translation_config"]["target_languages"] == ["pt"]
    assert "named_entity_recognition" not in translated["realtime_processing"]
    entities_only = build_live_options(vocabulary=[], translate_to=None)
    assert entities_only["realtime_processing"] == {"named_entity_recognition": True}
    vocabulary_only = build_live_options(translate_to=None, ner=False)
    assert vocabulary_only["realtime_processing"]["custom_vocabulary"] is True
    assert "translation" not in vocabulary_only["realtime_processing"]


def _wav_bytes(sample_rate=16000, seconds=0.25):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buffer.getvalue()


def test_load_pcm_reads_wav_without_conversion(tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(_wav_bytes())
    pcm, sample_rate = load_pcm(path)
    assert (len(pcm), sample_rate) == (8000, 16000)


def test_load_pcm_rejects_audio_over_120_seconds():
    with pytest.raises(RuntimeError, match="120-second"):
        load_pcm(_wav_bytes(sample_rate=8000, seconds=121))


def test_ffmpeg_has_timeout_and_output_cap(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: "/fake/ffmpeg")

    def run(command, **kwargs):
        assert kwargs["timeout"] <= 30
        assert "-t" in command and "-fs" in command
        return SimpleNamespace(returncode=0, stdout=b"\x00\x00", stderr=b"")

    monkeypatch.setattr(audio.subprocess, "run", run)
    assert load_pcm(b"compressed") == (b"\x00\x00", 16000)


def test_ffmpeg_timeout_is_an_audio_error(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: "/fake/ffmpeg")

    def run(*args, **kwargs):
        raise audio.subprocess.TimeoutExpired("ffmpeg", 20)

    monkeypatch.setattr(audio.subprocess, "run", run)
    with pytest.raises(audio.AudioError, match="timed out"):
        load_pcm(b"compressed")


def test_ffmpeg_oversized_output_is_rejected(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda _: "/fake/ffmpeg")
    monkeypatch.setattr(audio.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=b"\x00" * (audio.MAX_CONVERTED_BYTES + 1), stderr=b"",
    ))
    with pytest.raises(audio.AudioDurationError, match="120-second"):
        load_pcm(b"compressed")


def test_pcm_chunks_split_in_100ms():
    async def collect():
        return [chunk async for chunk in pcm_chunks(b"\x00" * 8000, 16000, realtime=False)]

    chunks = asyncio.run(collect())
    assert [len(c) for c in chunks] == [chunk_size(16000)] * 2 + [1600]


class FakeSession:
    """Imite LiveV2AsyncSession : rejoue des messages Gladia quand l'enregistrement s'arrête."""

    def __init__(self, messages, end_code=1000):
        self.messages, self.end_code = messages, end_code
        self.listeners, self.audio, self.ended = {}, [], False

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def _emit(self, event, payload):
        for callback in self.listeners.get(event, []):
            callback(payload)

    def send_audio(self, chunk):
        self.audio.append(chunk)

    def stop_recording(self):
        for message in self.messages:
            self._emit("message", message)
        if self.end_code != 1000:
            self._emit("error", RuntimeError("boom"))
        self._emit("ended", SimpleNamespace(code=self.end_code))

    def end_session(self):
        self.ended = True


class FakeClient:
    def __init__(self, session):
        self.session, self.options = session, None

    def start_session(self, options):
        self.options = options
        return self.session


def _message(uid, text, is_final):
    utterance = SimpleNamespace(text=text, language="fr", start=0.0, end=1.0, confidence=0.9)
    return SimpleNamespace(type="transcript", data=SimpleNamespace(id=uid, is_final=is_final, utterance=utterance))


async def _audio():
    for chunk in (b"\x01\x00", b"\x02\x00"):
        yield chunk


def _sdk_message(message_type, data=None, *, error=None):
    """Use actual frozen SDK dataclasses without creating any network client."""
    from gladiaio_sdk import (
        LiveV2NamedEntityRecognitionMessage,
        LiveV2SpeechEndMessage,
        LiveV2SpeechStartMessage,
        LiveV2TranscriptMessage,
        LiveV2TranslationMessage,
    )

    message_class = {
        "transcript": LiveV2TranscriptMessage,
        "translation": LiveV2TranslationMessage,
        "named_entity_recognition": LiveV2NamedEntityRecognitionMessage,
        "speech_start": LiveV2SpeechStartMessage,
        "speech_end": LiveV2SpeechEndMessage,
    }[message_type]
    payload = {
        "session_id": "test-session", "created_at": "2026-11-07T20:00:00Z",
        "type": message_type, "data": data,
    }
    if error is not None:
        payload["error"] = error
    return message_class.from_dict(payload)


def _utterance(text="Hello", language="en"):
    return {
        "text": text, "language": language, "start": 0.0, "end": 1.0,
        "confidence": 0.9, "channel": 0, "words": [],
    }


def _addon_messages(uid="u1"):
    return [
        _sdk_message("translation", {
            "utterance_id": uid, "utterance": _utterance("Bonjour", "fr"),
            "original_language": "fr", "target_language": "en",
            "translated_utterance": _utterance(),
        }),
        _sdk_message("named_entity_recognition", {
            "utterance_id": uid, "utterance": _utterance(),
            "results": [{"entity_type": "location", "text": "Lisbon", "start": 0.2, "end": 0.8}],
        }),
        _sdk_message("speech_start", {"time": 0.0, "channel": 0}),
        _sdk_message("speech_end", {"time": 1.0, "channel": 0}),
    ]


def _collect_voice(messages, *, streamer=stream_voice_events, options=None):
    session = FakeSession(messages)
    client = FakeClient(session)

    async def collect():
        return [event async for event in streamer(_audio(), sample_rate=8000, client=client, options=options)]

    events = asyncio.run(collect())
    assert session.ended
    assert session.audio == [b"\x01\x00", b"\x02\x00"]
    assert client.options == (options or build_live_options(8000))
    return events


def test_stream_voice_partials_replace_text_and_increment_per_utterance_revision():
    updates = [("u1", "Sign", False), ("u2", "Wait", False), ("u1", "Sign me up", False),
               ("u1", "Sign me up for a race", True)]
    messages = [_sdk_message("transcript", {"id": uid, "is_final": final, "utterance": _utterance(text)})
                for uid, text, final in updates]
    messages.append(SimpleNamespace(type="post_final_transcript", data=None))
    events = _collect_voice(messages)
    assert [(event.utterance_id, event.revision) for event in events] == [
        ("u1", 1), ("u2", 1), ("u1", 2), ("u1", 3),
    ]
    current = {}
    for event, (_, expected_text, _) in zip(events, updates):
        assert event.text == expected_text
        current[event.utterance_id] = event.text
    assert current == {"u1": "Sign me up for a race", "u2": "Wait"}
    assert events[-1].is_final
    assert _collect_voice([messages[0]])[0].revision == 1


def test_stream_voice_addons_correlate_and_include_receipt_metadata():
    before = datetime.now(UTC)
    events = _collect_voice([_message("u1", "Bonjour", True), *_addon_messages()])
    after = datetime.now(UTC)
    transcript, translation, entities, speech_start, speech_end = events
    assert isinstance(translation, TranslationEvent)
    assert translation.utterance_id == entities.utterance_id == transcript.utterance_id == "u1"
    assert (translation.source_language, translation.target_language, translation.text) == ("fr", "en", "Hello")
    assert isinstance(entities, EntitiesEvent)
    assert [entity.model_dump() for entity in entities.entities] == [
        {"type": "location", "text": "Lisbon", "start": 0.2, "end": 0.8},
    ]
    assert isinstance(speech_start, SpeechEvent) and isinstance(speech_end, SpeechEvent)
    assert [(event.kind, event.time) for event in events[-2:]] == [("start", 0.0), ("end", 1.0)]
    for event in events:
        assert event.provider == "gladia" and event.model == "solaria-1"
        assert before <= event.received_at <= after
        assert json.loads(event.model_dump_json())["received_at"].endswith("Z")


@pytest.mark.parametrize("addons_first", [False, True])
def test_stream_voice_normalizes_numeric_addon_ids_to_transcript_ids(addons_first):
    transcript = _message("00_00000000", "Hello", True)
    addons = _addon_messages("0")[:2]
    events = _collect_voice([*addons, transcript] if addons_first else [transcript, *addons])
    assert [event.type for event in events] == ["transcript", "translation", "entities"]
    assert {event.utterance_id for event in events} == {"00_00000000"}
    if addons_first:
        assert events[1].received_at < events[0].received_at


def test_stream_voice_correlation_keeps_channels_separate():
    transcripts = [_sdk_message("transcript", {
        "id": f"channel-{channel}", "is_final": True,
        "utterance": {**_utterance(), "channel": channel},
    }) for channel in (0, 1)]
    entity_message = _sdk_message("named_entity_recognition", {
        "utterance_id": "0", "utterance": {**_utterance(), "channel": 1}, "results": [],
    })
    events = _collect_voice([*transcripts, entity_message])
    assert events[-1].utterance_id == "channel-1"


def test_stream_voice_preserves_unmatched_addons_at_session_end():
    events = _collect_voice(_addon_messages("orphan")[:2])
    assert [event.type for event in events] == ["translation", "entities"]
    assert {event.utterance_id for event in events} == {"orphan"}


@pytest.mark.parametrize("message_type", ["translation", "named_entity_recognition"])
def test_stream_voice_addon_failure_yields_one_warning_and_continues(message_type):
    failed = _sdk_message(message_type, error={"status_code": 500, "message": "Addon failed"})
    events = _collect_voice([failed, _message("u1", "Stop", True)])
    warning, transcript = events
    assert isinstance(warning, WarningEvent)
    assert warning.type == "warning" and warning.event_type == message_type
    assert "transcription continues" in warning.message
    assert isinstance(transcript, TranscriptEvent) and transcript.text == "Stop"


def test_stream_voice_empty_entities_are_valid():
    message = _sdk_message("named_entity_recognition", {
        "utterance_id": "u1", "utterance": _utterance(), "results": [],
    })
    assert _collect_voice([message])[0].entities == []


@pytest.mark.parametrize("end_code,with_transcripts", [(1000, True), (1000, False), (1006, False)])
def test_typed_stream_preserves_telemetry(monkeypatch, end_code, with_transcripts):
    from runai import telemetry

    monkeypatch.setattr(telemetry, "default_log", telemetry.CallLog())
    messages = [*_addon_messages()]
    if with_transcripts:
        messages += [_message("u1", "Stop", False), _message("u1", "Stop", True)]
    client = FakeClient(FakeSession(messages, end_code=end_code))

    async def collect():
        return [event async for event in stream_voice_events(_audio(), client=client)]

    if end_code == 1000:
        asyncio.run(collect())
    else:
        with pytest.raises(VoiceError, match="Gladia session ended abnormally"):
            asyncio.run(collect())
    call, = telemetry.default_log.list()
    assert call.provider == "gladia" and call.operation == "live.transcribe"
    assert call.ok == (end_code == 1000)
    assert call.meta["audio_s"] == 4 / (16000 * 2)
    assert call.meta["n_final_utterances"] == int(with_transcripts)
    assert ("time_to_first_partial_ms" in call.meta) == with_transcripts


def test_stream_transcripts_filters_all_addons_and_warnings():
    failed = _sdk_message("translation", error={"status_code": 500, "message": "Addon failed"})
    events = _collect_voice(
        [*_addon_messages(), failed, _message("u1", "Stop", True)],
        streamer=stream_transcripts, options=build_live_options(8000, translate_to=None),
    )
    assert len(events) == 1 and isinstance(events[0], TranscriptEvent)


def test_cli_emits_addons_but_only_detects_commands_from_transcripts(monkeypatch, capsys):
    from runai.voice import __main__ as cli

    events = _collect_voice([_message("u1", "Stop", False), *_addon_messages(), _message("u1", "Stop", True)])

    async def fake_stream(chunks, *, sample_rate):
        assert sample_rate == 16000
        for event in events:
            yield event

    monkeypatch.setattr(cli, "stream_voice_events", fake_stream)
    monkeypatch.setattr(cli, "file_stream", lambda source: AudioStream(16000, _audio()))
    cli.main(["--file", "unused.wav", "--partials"])
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["type"] for event in output] == [
        "transcript", "command", "translation", "entities", "speech", "speech", "transcript",
    ]
    assert output[1]["command"]["kind"] == "pause"


def test_cli_hides_partials_but_not_addons(capsys):
    from runai.voice.__main__ import _emit

    for event in _collect_voice([_message("u1", "Hello", False), *_addon_messages()]):
        _emit(event, None, show_partials=False)
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["type"] for event in output] == ["translation", "entities", "speech", "speech"]


def test_stream_events_with_fake_gladia():
    session = FakeSession([
        SimpleNamespace(type="audio_chunk"),
        *_addon_messages(),
        _message("u1", "Non, attends", is_final=False),
        _message("u1", "Non, attends, plutôt un hôtel près du départ", is_final=True),
        _message("u2", "Reprends", is_final=True),
    ])
    client = FakeClient(session)

    async def collect():
        return [e async for e in stream_events(AudioStream(16000, _audio()), client=client)]

    events = asyncio.run(collect())
    commands = [(e.command.kind, e.early) for e in events if e.type == "command"]
    assert commands == [
        (CommandKind.pause, True),
        (CommandKind.correction, False),
        (CommandKind.resume, False),
    ]
    assert [e.text for e in events if e.type == "transcript"][-1] == "Reprends"
    assert session.audio == [b"\x01\x00", b"\x02\x00"]
    assert client.options["sample_rate"] == 16000
    assert session.ended


def test_stream_transcripts_raises_on_abnormal_end():
    client = FakeClient(FakeSession([], end_code=1006))

    async def collect():
        return [e async for e in stream_transcripts(_audio(), client=client)]

    with pytest.raises(VoiceError):
        asyncio.run(collect())


def test_decimal_distance_keeps_integer_part():
    assert extract_race("Une course de 21,1 km à Paris").distance_km == 21.1
    assert extract_race("10.5 km à Porto").distance_km == 10.5


@pytest.mark.parametrize("text", [
    "N'annule pas l'hôtel", "N'annule pas le semi de Paris", "Ne t'arrête pas", "Don't stop", "Ne change pas la date",
])
def test_negated_keyword_is_not_a_command(text):
    assert parse_command(text) is None
    assert CommandDetector().feed(_transcript(text, is_final=False)) == []


def test_decimal_distance_correction_targets_race():
    command = parse_command("Plutôt 21,1 km")
    assert (command.kind, command.target) == (CommandKind.correction, CorrectionTarget.race)


def test_race_mission_survives_unrelated_keyword():
    assert parse_command("Le semi de Paris avec une pause à Porto").kind is CommandKind.new_mission


@pytest.mark.parametrize(("text", "kind"), [
    ("Pause, le semi de Paris", CommandKind.pause),
    ("C'est bon, continue le semi de Paris", CommandKind.resume),
    ("Le semi de Paris me va, c'est bon", CommandKind.new_mission),
    ("Pour le semi de Paris, reprends", CommandKind.resume),
])
def test_pause_and_resume_beat_implicit_race_mission(text, kind):
    assert parse_command(text).kind is kind
