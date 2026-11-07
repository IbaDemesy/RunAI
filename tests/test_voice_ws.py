import asyncio
import base64
import threading
from contextlib import contextmanager
from functools import partial
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from runai.app import voice_ws
from runai.app.auth import BasicAuthMiddleware
from runai.app.providers import UnavailableTranscriber
from runai.app.real import RealTranscriber
from runai.app.replay import ReplayRaceSearch, ReplayTrace, ReplayTranscriber
from runai.app.server import build_demo_service, create_app
from runai.contracts.common import DataMode
from runai.voice.live import stream_transcripts, stream_voice_events
from runai.voice.models import TranscriptEvent, TranslationEvent

PATH = "/api/voice/stream"
PCM = b"\x00\x00" * 1600


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    monkeypatch.delenv("RUNAI_PUBLIC", raising=False)
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    return build_demo_service(delay=0)


@contextmanager
def connection(service, sample_rate=16000):
    with TestClient(create_app(service)) as client, client.websocket_connect(PATH) as ws:
        ws.send_json({"type": "start", "sample_rate": sample_rate})
        assert ws.receive_json() == {
            "type": "ready", "mode": service.providers.mode.value,
            "provider": "gladia", "model": "solaria-1",
        }
        yield ws


def assert_closed(ws, code):
    with pytest.raises(WebSocketDisconnect) as error:
        ws.receive_json()
    assert error.value.code == code


def assert_error(ws, message):
    error = ws.receive_json()
    assert error["type"] == "error"
    assert message in error["message"]
    assert_closed(ws, 1011)


def test_demo_streams_partials_before_stop_then_final_and_ended(service):
    with connection(service) as ws:
        for text in ("I want", "I want to run a half"):
            ws.send_bytes(PCM)
            partial = ws.receive_json()
            assert partial["type"] == "transcript"
            assert partial["text"] == text
            assert partial["is_final"] is False
        ws.send_json({"type": "stop"})
        final = ws.receive_json()
        assert final["is_final"] is True
        assert final["text"] == "I want to run a half marathon."
        assert ws.receive_json() == {"type": "ended"}
        assert_closed(ws, 1000)


@pytest.mark.parametrize("sample_rate", (8000, 16000, 32000, 44100, 48000))
def test_supported_sample_rates_and_empty_capture(service, sample_rate):
    with connection(service, sample_rate) as ws:
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "ended"}
        assert_closed(ws, 1000)


@pytest.mark.parametrize("start", (
    {"type": "stop"}, {"type": "start"}, {"type": "start", "sample_rate": 123},
    {"type": "start", "sample_rate": True}, {"type": "start", "sample_rate": "16000"},
    {"type": "start", "sample_rate": 16000.0}, [], None,
))
def test_invalid_start_rejected(service, start):
    with TestClient(create_app(service)) as client, client.websocket_connect(PATH) as ws:
        ws.send_json(start)
        assert_error(ws, "")


@pytest.mark.parametrize("message", ("not json", '["stop"]'))
def test_malformed_control_rejected(service, message):
    with connection(service) as ws:
        ws.send_text(message)
        assert_error(ws, "Expected a JSON")


def test_audio_before_start_rejected(service):
    with TestClient(create_app(service)) as client, client.websocket_connect(PATH) as ws:
        ws.send_bytes(PCM)
        assert_error(ws, "Expected a JSON")


def test_pcm_samples_must_be_16_bit(service):
    with connection(service) as ws:
        ws.send_bytes(b"\x00")
        assert_error(ws, "PCM16")


def test_total_byte_limit_is_cumulative(service, monkeypatch):
    monkeypatch.setattr("runai.app.server.MAX_AUDIO_BYTES", len(PCM) + 2)
    with connection(service) as ws:
        ws.send_bytes(PCM)
        assert ws.receive_json()["is_final"] is False
        ws.send_bytes(PCM)
        assert_error(ws, "byte limit")


def test_audio_duration_limit(service):
    with connection(service, sample_rate=8000) as ws:
        ws.send_bytes(b"\x00\x00" * (8000 * 120 + 1))
        assert_error(ws, "120-second")


def test_capture_wall_clock_limit(service, monkeypatch):
    monkeypatch.setattr(voice_ws, "MAX_AUDIO_SECONDS", 0.03)
    with connection(service) as ws:
        assert_error(ws, "120-second")


def test_idle_capture_stops_cleanly(service, monkeypatch):
    monkeypatch.setattr(voice_ws, "IDLE_TIMEOUT_SECONDS", 0.05)
    with connection(service) as ws:
        assert ws.receive_json() == {"type": "ended"}
        assert_closed(ws, 1000)


def test_idle_before_start_reports_error(service, monkeypatch):
    monkeypatch.setattr(voice_ws, "IDLE_TIMEOUT_SECONDS", 0.03)
    with TestClient(create_app(service)) as client, client.websocket_connect(PATH) as ws:
        assert_error(ws, "timed out")


def test_restart_rejected(service):
    with connection(service) as ws:
        ws.send_json({"type": "start", "sample_rate": 16000})
        assert_error(ws, "cannot restart")


def test_unavailable_provider_is_explicit(service):
    service.providers.mode = DataMode.live
    service.providers.transcriber = UnavailableTranscriber("missing credentials")
    with connection(service) as ws:
        assert_error(ws, "Gladia is unavailable")


def test_replay_streams_trace_without_live_calls(service):
    service.providers.mode = DataMode.replay
    trace = ReplayTrace(label="Recorded voice", transcript="Find a coastal race.")
    service.providers.search = ReplayRaceSearch(trace)
    service.providers.transcriber = ReplayTranscriber(trace)
    with connection(service) as ws:
        ws.send_bytes(PCM)
        assert ws.receive_json()["is_final"] is False
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["text"] == "Find a coastal race."
        assert ws.receive_json() == {"type": "ended"}


def test_missing_replay_transcript_reports_error(service):
    service.providers.transcriber = ReplayTranscriber(ReplayTrace(label="Empty"))
    with connection(service) as ws:
        assert_error(ws, "no transcript")


class RichEvent(BaseModel):
    type: str = "translation"
    text: str
    nested: dict


def test_real_adapter_forwards_all_event_types_and_redacts_payload(service, monkeypatch):
    secret = "test-provider-credential"
    monkeypatch.setenv("GLADIA_API_KEY", secret)
    closed = threading.Event()

    async def streamer(chunks, *, sample_rate):
        try:
            assert sample_rate == 16000
            async for chunk in chunks:
                assert chunk == PCM
                yield RichEvent(text=secret, nested={"value": secret})
        finally:
            closed.set()

    service.providers.transcriber = RealTranscriber(streamer=streamer)
    with connection(service) as ws:
        ws.send_bytes(PCM)
        assert ws.receive_json() == {"type": "translation", "text": "[REDACTED]", "nested": {"value": "[REDACTED]"}}
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "ended"}
    assert closed.wait(1)


def test_provider_error_is_redacted_and_cleaned_up(service, monkeypatch):
    secret = "test-private-provider-token"
    monkeypatch.setenv("GLADIA_API_KEY_2", secret)
    closed = threading.Event()

    async def streamer(chunks, *, sample_rate):
        try:
            async for _ in chunks:
                raise RuntimeError(f"Provider failed: {secret}")
                yield  # pragma: no cover
        finally:
            closed.set()

    service.providers.transcriber = RealTranscriber(streamer=streamer)
    with connection(service) as ws:
        ws.send_bytes(PCM)
        assert_error(ws, "Provider failed: [REDACTED]")
    assert closed.wait(1)


def test_disconnect_closes_upstream_even_after_stop(service):
    closed = threading.Event()
    started = threading.Event()

    async def streamer(chunks, *, sample_rate):
        try:
            started.set()
            async for _ in chunks:
                yield RichEvent(text="Listening", nested={})
            await asyncio.Event().wait()
        finally:
            closed.set()

    service.providers.transcriber = RealTranscriber(streamer=streamer)
    for send_stop in (False, True):
        closed.clear()
        started.clear()
        with connection(service) as ws:
            ws.send_bytes(PCM)
            assert ws.receive_json()["type"] == "translation"
            assert started.wait(1)
            if send_stop:
                ws.send_json({"type": "stop"})
        assert closed.wait(1)


def test_finalization_timeout_closes_upstream(service, monkeypatch):
    monkeypatch.setattr(voice_ws, "DRAIN_TIMEOUT_SECONDS", 0.03)
    closed = threading.Event()

    async def streamer(chunks, *, sample_rate):
        try:
            async for _ in chunks:
                yield RichEvent(text="Listening", nested={})
            await asyncio.Event().wait()
        finally:
            closed.set()

    service.providers.transcriber = RealTranscriber(streamer=streamer)
    with connection(service) as ws:
        ws.send_json({"type": "stop"})
        assert_error(ws, "final transcription")
    assert closed.wait(1)


def test_disconnect_ends_gladia_sdk_session(service):
    fed = threading.Event()
    ended = threading.Event()

    class Session:
        def on(self, name, callback):
            pass

        def send_audio(self, chunk):
            assert chunk == PCM
            fed.set()

        def stop_recording(self):
            pass

        def end_session(self):
            ended.set()

    client = SimpleNamespace(start_session=lambda options: Session())
    service.providers.transcriber = RealTranscriber(streamer=partial(stream_transcripts, client=client))
    with connection(service) as ws:
        ws.send_bytes(PCM)
        assert fed.wait(1)
    assert ended.wait(1)


def test_backpressure_is_bounded_and_closes_provider(service, monkeypatch):
    monkeypatch.setattr(voice_ws, "MAX_BUFFERED_FRAMES", 3)
    started = threading.Event()
    closed = threading.Event()

    async def streamer(chunks, *, sample_rate):
        try:
            started.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover
        finally:
            closed.set()

    service.providers.transcriber = RealTranscriber(streamer=streamer)
    with connection(service) as ws:
        assert started.wait(1)
        for _ in range(3):
            ws.send_bytes(PCM)
        assert_error(ws, "faster than")
    assert closed.wait(1)


@pytest.mark.parametrize("frame", ({"type": "start", "sample_rate": 16000}, {"type": "stop"}, PCM))
def test_frames_after_stop_cannot_start_another_session(service, frame):
    async def streamer(chunks, *, sample_rate):
        async for _ in chunks:
            yield RichEvent(text="Listening", nested={})
        await asyncio.Event().wait()

    service.providers.transcriber = RealTranscriber(streamer=streamer)
    with connection(service) as ws:
        ws.send_json({"type": "stop"})
        if isinstance(frame, bytes):
            ws.send_bytes(frame)
        else:
            ws.send_json(frame)
        assert_error(ws, "one audio session")


@pytest.mark.parametrize("authorization", (None, "Basic !!!", "Bearer other", "Basic dXNlcjp3cm9uZw=="))
def test_websocket_basic_auth_denies_missing_or_invalid_credentials(service, monkeypatch, authorization):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "user:password")
    headers = {"authorization": authorization} if authorization else {}
    with TestClient(create_app(service)) as client:
        assert client.get("/api/health").status_code == 200
        with pytest.raises(WebSocketDenialResponse) as error, client.websocket_connect(PATH, headers=headers):
            pytest.fail("Unauthenticated WebSocket was accepted")
        assert error.value.status_code == 403


def test_websocket_basic_auth_accepts_valid_credentials(service, monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "user:password")
    token = base64.b64encode(b"user:password").decode()
    with TestClient(create_app(service)) as client, client.websocket_connect(PATH, headers={"authorization": f"Basic {token}"}) as ws:
        ws.send_json({"type": "start", "sample_rate": 16000})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "ended"}


def test_websocket_auth_throttle_is_shared_with_http_and_expires(service, monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "user:password")
    clock = [100.0]
    monkeypatch.setattr("runai.app.auth.time.monotonic", lambda: clock[0])
    token = base64.b64encode(b"user:password").decode()
    with TestClient(create_app(service)) as client:
        for _ in range(5):
            with pytest.raises(WebSocketDenialResponse) as error, client.websocket_connect(PATH):
                pytest.fail("Unauthenticated WebSocket was accepted")
            assert error.value.status_code == 403
        assert client.get("/").status_code == 429
        with pytest.raises(WebSocketDenialResponse) as error, client.websocket_connect(
            PATH, headers={"authorization": f"Basic {token}"},
        ):
            pytest.fail("Throttled WebSocket was accepted")
        assert error.value.status_code == 429
        assert error.value.headers["retry-after"] == "60"
        clock[0] += 60
        with client.websocket_connect(PATH, headers={"authorization": f"Basic {token}"}) as ws:
            ws.send_json({"type": "start", "sample_rate": 16000})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "stop"})
            assert ws.receive_json() == {"type": "ended"}


def test_real_transcriber_defaults_to_typed_events_but_uploads_keep_only_transcripts(monkeypatch):
    assert RealTranscriber().streamer is stream_voice_events
    monkeypatch.setattr("runai.app.real.load_pcm", lambda audio: (PCM, 16000))

    async def streamer(chunks, *, sample_rate):
        async for _ in chunks:
            pass
        yield TranscriptEvent(utterance_id="u1", text="Bon", is_final=False)
        yield TranslationEvent(utterance_id="u1", source_language="fr", target_language="en", text="Hello")
        yield TranscriptEvent(utterance_id="u1", text="Bonjour", is_final=True)

    assert asyncio.run(RealTranscriber(streamer=streamer).transcribe(b"audio", "audio/wav")) == "Bonjour"


def test_websocket_basic_auth_fallback_closes_with_policy_violation():
    sent = []

    async def scenario():
        async def app(scope, receive, send):
            pytest.fail("Unauthenticated request reached the app")

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        await BasicAuthMiddleware(app, "user:password")(
            {"type": "websocket", "path": "/api/health", "headers": []}, receive, send
        )

    asyncio.run(scenario())
    assert sent == [{"type": "websocket.accept"}, {"type": "websocket.close", "code": 1008}]
