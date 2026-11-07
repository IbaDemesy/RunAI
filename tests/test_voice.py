import asyncio
import io
import json
import wave
from types import SimpleNamespace

import pytest

from runai.voice import (
    CommandDetector,
    CommandKind,
    CommandSource,
    CorrectionTarget,
    TranscriptEvent,
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
    assert (race.name, race.city, race.country, race.distance_km) == (None, "Lisbonne", "PT", HALF_MARATHON_KM)


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
    vocabulary = options["realtime_processing"]["custom_vocabulary_config"]["vocabulary"]
    values = {entry["value"] for entry in vocabulary}
    assert {"Lisbonne", "Lisboa", "Meia Maratona de Lisboa", "Milano Marathon", "Njuko"} <= values
    assert all(entry.get("language") in (None, "fr", "en", "pt") for entry in vocabulary)
    json.dumps(options)


def test_build_live_options_single_language_without_vocabulary():
    options = build_live_options(8000, languages=["fr"], vocabulary=[])
    assert options["language_config"]["code_switching"] is False
    assert "realtime_processing" not in options


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


def test_stream_events_with_fake_gladia():
    session = FakeSession([
        SimpleNamespace(type="audio_chunk"),
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


@pytest.mark.parametrize("text", ["N'annule pas l'hôtel", "Ne t'arrête pas", "Don't stop", "Ne change pas la date"])
def test_negated_keyword_is_not_a_command(text):
    assert parse_command(text) is None
    assert CommandDetector().feed(_transcript(text, is_final=False)) == []


def test_decimal_distance_correction_targets_race():
    command = parse_command("Plutôt 21,1 km")
    assert (command.kind, command.target) == (CommandKind.correction, CorrectionTarget.race)
