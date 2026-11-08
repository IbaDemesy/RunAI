import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import FakeBrowserAgents, FakeRaceSearch, FakeTranscriber
from runai.app.mission import MissionService
from runai.app.server import create_app
from runai.logging_setup import JsonFormatter, configure_logging


@pytest.fixture
def json_logs(monkeypatch):
    monkeypatch.setenv("RUNAI_LOG_FORMAT", "json")
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    buffer = io.StringIO()
    capture = logging.StreamHandler(buffer)
    capture.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(capture)
    yield lambda: [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    root.removeHandler(capture)


def demo_client(agents=None):
    service = MissionService(FakeRaceSearch(delay=0), agents or FakeBrowserAgents(delay=0), FakeTranscriber(), simulated=True)
    return TestClient(create_app(service))


def test_request_without_id_gets_one_back_and_it_is_logged_with_latency(json_logs):
    with demo_client() as client:
        response = client.get("/api/health?probe=1")
    rid = response.headers["x-request-id"]
    assert rid
    lines = [line for line in json_logs() if line["msg"] == "request" and line.get("request_id") == rid]
    assert len(lines) == 1
    line = lines[0]
    assert line["path"] == "/api/health" and line["method"] == "GET" and line["status"] == 200
    assert isinstance(line["duration_ms"], float) and line["level"] == "INFO" and line["ts"]


def test_incoming_request_id_is_echoed(json_logs):
    with demo_client() as client:
        response = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"
    assert any(line.get("request_id") == "abc-123" for line in json_logs())


def test_secret_values_are_redacted_in_message_and_extras(json_logs, monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "hk-secret123")
    logging.getLogger("runai.test").warning("calling H with hk-secret123", extra={"provider": "h hk-secret123"})
    output = json.dumps(json_logs())
    assert "hk-secret123" not in output
    assert "[REDACTED]" in output


def test_configure_logging_is_idempotent(monkeypatch):
    monkeypatch.setenv("RUNAI_LOG_FORMAT", "text")
    first = configure_logging()
    second = configure_logging()
    assert first is second
    assert [h for h in logging.getLogger().handlers if h.get_name() == "runai"] == [first]
    assert not logging.getLogger("uvicorn").handlers


class FakeLifecycle:
    def slots(self):
        return {"HAI_API_KEY": {"active": 1, "max": 3}, "HAI_API_KEY_2": {"active": 0, "max": 3}}

    def queued(self):
        return [object()]

    async def aclose(self):
        pass


def test_health_reports_runtime_and_h_slots_without_key_values(monkeypatch):
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    monkeypatch.setenv("HAI_API_KEY", "hk-secret123")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef")
    agents = FakeBrowserAgents(delay=0)
    agents.lifecycle = FakeLifecycle()
    with demo_client(agents) as client:
        response = client.get("/api/health")
    health = response.json()
    assert response.status_code == 200
    assert {"ok", "mode", "simulated", "providers", "details"} <= set(health)
    assert health["mode"] == "demo" and health["ok"] is True
    assert health["uptime_s"] >= 0 and health["started_at"]
    assert health["version"] == "0123456"
    assert health["active_missions"] == 0
    assert health["h_slots"] == ["HAI_API_KEY", "HAI_API_KEY_2"]
    assert health["h_queued"] == 1
    assert "hk-secret123" not in response.text


def test_health_version_defaults_to_dev_and_no_slots_without_lifecycle(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    with demo_client() as client:
        health = client.get("/api/health").json()
    assert health["version"] == "dev"
    assert "h_slots" not in health


def test_sse_stream_logs_open_and_close(json_logs):
    from runai.app.mission import Mission, MissionStatus

    with demo_client() as client:
        service = client.app.state.service
        mission = Mission(id="m-log", query="test", steps={}, status=MissionStatus.completed)
        service.missions[mission.id] = mission
        client.get(f"/api/missions/{mission.id}/events")
    names = [line["msg"] for line in json_logs() if line.get("mission_id") == "m-log"]
    assert "sse_open" in names and "sse_close" in names
    close = next(line for line in json_logs() if line["msg"] == "sse_close")
    assert {"duration_s", "events_sent", "last_event_id"} <= set(close)
    assert not any(line["msg"] == "request" and line.get("path", "").endswith("/events") for line in json_logs())
