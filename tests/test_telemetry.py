import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from runai import telemetry
from runai.app.server import build_demo_service, create_app
from runai.framing.holo import HoloPhraser, TemplatePhraser
from runai.search.candidates import LinkupCandidateSearch
from runai.telemetry import CallLog, ProviderCall, correlate, correlation_id, timed
from runai.voice.live import VoiceError, stream_transcripts

KEY = "fake-provider-key-123456"


@pytest.fixture(autouse=True)
def isolated_log(monkeypatch):
    monkeypatch.setattr(telemetry, "default_log", CallLog())
    monkeypatch.setenv("HAI_API_KEY", KEY)


class SearchClient:
    def search(self, **kwargs):
        return SimpleNamespace(data={"candidates": []}, sources=[{"url": "https://example.org"}])


def test_structured_search_and_thread_correlation():
    async def run():
        with correlate("framing-123"):
            await asyncio.to_thread(LinkupCandidateSearch(SearchClient())._search, "Find a race")
        assert correlation_id.get() is None

    asyncio.run(run())
    call, = telemetry.default_log.list(correlation_id="framing-123", provider="linkup")
    assert call.operation == "search.structured"
    assert call.duration_ms >= 0
    assert call.meta["n_sources"] == 1


def test_holo_success_usage_and_extract_operation():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }))
    phraser = HoloPhraser(KEY, model="test-model", transport=transport)
    assert asyncio.run(phraser.extract("Find a race", {})) == {}
    call, = telemetry.default_log.list()
    assert call.ok and call.operation == "chat.extract"
    assert call.meta == {"model": "test-model", "max_tokens": 200,
                         "prompt_tokens": 12, "completion_tokens": 3}


def test_holo_error_redacted_and_fallback_unchanged(caplog):
    transport = httpx.MockTransport(lambda request: httpx.Response(500, headers={"x-test": KEY}))
    phraser = HoloPhraser(KEY, transport=transport)
    question = "Which city?"
    with caplog.at_level("INFO", logger="runai.telemetry"):
        assert asyncio.run(phraser.phrase([], question, {})) == asyncio.run(
            TemplatePhraser().phrase([], question, {}))
        with pytest.raises(RuntimeError), timed("holo", "chat.phrase", model=KEY):
            raise RuntimeError(KEY)
    calls = telemetry.default_log.list()
    assert not calls[0].ok and "500" in calls[0].error
    assert calls[1].error == "[REDACTED]"
    assert KEY not in caplog.text
    client = TestClient(create_app(build_demo_service()))
    for endpoint in ("calls", "summary"):
        assert KEY not in client.get("/api/telemetry/" + endpoint).text


def test_api_summary_filters_and_auth(monkeypatch):
    for duration in (10, 20):
        telemetry.default_log.record(ProviderCall(
            provider="linkup", operation="search.structured", started_at=datetime.now(UTC),
            duration_ms=duration, ok=True, correlation_id="framing", meta={"est_cost_usd": .01},
        ))
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "user:password")
    client = TestClient(create_app(build_demo_service()))
    for endpoint in ("calls", "summary"):
        assert client.get("/api/telemetry/" + endpoint).status_code == 401
    response = client.get("/api/telemetry/summary", auth=("user", "password"))
    assert response.status_code == 200
    assert response.json()["linkup"] == {
        "count": 2, "p50": 10, "p95": 20, "error_rate": 0, "est_cost_usd": .02,
    }
    response = client.get("/api/telemetry/calls?provider=linkup&correlation_id=framing&limit=1",
                          auth=("user", "password"))
    assert len(response.json()) == 1
    assert response.json()[0]["duration_ms"] == 20


def test_empty_bounded_log_and_error():
    assert telemetry.default_log.summary() == {}
    assert telemetry.default_log.list(limit=0) == []
    log = CallLog(maxlen=2)
    for duration in (1, 2, 3):
        log.record(ProviderCall(provider="h", operation="test", started_at=datetime.now(UTC),
                                duration_ms=duration, ok=duration != 3))
    assert [call.duration_ms for call in log.list()] == [2, 3]
    assert log.summary()["h"]["error_rate"] == .5
    assert log.list(provider="gladia") == []
    assert log.list(correlation_id="absent") == []


@pytest.mark.parametrize("usage", [None, [], "unavailable"])
def test_optional_usage_does_not_change_completion(usage):
    phraser = HoloPhraser(KEY, transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": "Which city?"}}], "usage": usage})))
    assert asyncio.run(phraser.phrase([], "Which city?", {})) == "Which city?"
    assert telemetry.default_log.list()[0].ok


class GladiaSession:
    def __init__(self, code=1000, messages=True):
        self.listeners = {}
        self.code, self.messages = code, messages

    def on(self, event, callback):
        self.listeners[event] = callback

    def send_audio(self, chunk):
        pass

    def stop_recording(self):
        if self.messages:
            for final in (False, True):
                self.listeners["message"](SimpleNamespace(type="transcript", data=SimpleNamespace(
                    id="utterance", is_final=final, utterance=SimpleNamespace(
                        text="Hello", language="en", start=0, end=1, confidence=.9))))
        self.listeners["ended"](SimpleNamespace(code=self.code))

    def end_session(self):
        pass


@pytest.mark.parametrize("code,messages", [(1000, True), (1000, False), (1006, False)])
def test_gladia_stream(code, messages):
    async def audio():
        yield bytes(32000)

    async def run():
        client = SimpleNamespace(start_session=lambda options: GladiaSession(code, messages))
        return [event async for event in stream_transcripts(audio(), client=client)]

    if code != 1000:
        with pytest.raises(VoiceError):
            asyncio.run(run())
    else:
        assert len(asyncio.run(run())) == (2 if messages else 0)
    call, = telemetry.default_log.list()
    assert call.provider == "gladia" and call.operation == "live.transcribe"
    assert call.ok == (code == 1000)
    assert call.meta["audio_s"] == 1
    assert call.meta["n_final_utterances"] == int(messages)
    if messages:
        assert call.meta["time_to_first_partial_ms"] >= 0
    assert KEY not in json.dumps(call.model_dump(mode="json"))
