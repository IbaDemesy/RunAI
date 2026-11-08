import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app
from runai.metrics import MissionMetrics, compute
from runai.models import StepResult, TraceEvent
from runai.tracing import TraceWriter, iter_traces
from tests.test_v2_backend import confirm, finish, prepare

FIXTURE = Path(__file__).parent / "fixtures" / "metrics_traces" / "sample_mission.jsonl"


def fixture_events():
    return TraceWriter(FIXTURE.stem, FIXTURE.parent).read()


def test_fixture_metrics_and_result_fallback():
    report = compute("sample_mission", fixture_events(), {
        "registration": StepResult(kind="registration", status="stopped_before_commitment", stop_point="payment",
                                   data={"steps":99, "total_cost":99}),
        "accommodation": StepResult(kind="accommodation", status="completed", data={"steps":3, "total_cost":.05}),
    })
    registration = report.steps["registration"]
    assert registration.duration_s == 10
    assert registration.h_steps == 7
    assert registration.total_cost_usd == .125
    assert registration.unique_hosts == ["tickets.example.com"]
    assert registration.human_wait_s == 4
    assert registration.questions == 1
    assert registration.stop_point == "payment"
    assert registration.h_session_id == "sample-session"
    assert registration.h_key == "primary" and registration.max_steps == 30
    hotel = report.steps["accommodation"]
    assert hotel.duration_s == 10
    assert hotel.h_steps == 3 and hotel.total_cost_usd == .05
    assert hotel.unique_hosts == ["example.org"]
    assert hotel.human_wait_s == 0
    assert report.human_wait_s == 4
    assert report.totals.h_steps == 10
    assert report.totals.h_cost_usd == pytest.approx(.175)
    assert report.wall_s == 14
    assert report.time_to_first_agent_event_s == 2
    assert report.status == "awaiting_human" and report.ended_at is not None


def test_empty_running_and_failed_metrics():
    empty = compute("empty", [])
    assert empty.status == "pending" and empty.started_at is None
    assert empty.steps == {} and empty.totals.agents == 0
    assert empty.ended_at is None and empty.wall_s == 0
    events = fixture_events()[:8]
    running = compute("running", events)
    assert running.ended_at is None
    assert running.steps["registration"].duration_s == 8
    assert running.steps["registration"].status == "running"
    assert running.steps["accommodation"].h_steps is None
    assert running.steps["accommodation"].total_cost_usd is None
    events.append(TraceEvent(at=fixture_events()[-1].at, source="app", type="step_failed",
                             data={"step":"registration"}))
    failed = compute("failed", events)
    assert failed.status == "failed" and failed.ended_at is not None
    assert failed.steps["registration"].status == "failed"


def test_redaction_invalid_urls_and_unmatched_answers(monkeypatch):
    secret = "sample-sensitive-key"
    monkeypatch.setenv("HAI_API_KEY", secret)
    events = fixture_events()
    events.insert(-1, TraceEvent(at=events[-2].at, source="h", type="AgentEvent.observation_event", data={
        "step":"registration", "event":{"data":{"metadata":{"url":"https://[broken"}}},
    }))
    events.insert(-1, TraceEvent(at=events[-2].at, source="human", type="answer", data={
        "step":"registration", "question_id":"unknown",
    }))
    report = compute(secret, events, {"registration": StepResult(kind="registration", h_session_id=secret)})
    assert secret not in report.model_dump_json()
    assert report.mission_id == "[REDACTED]"
    assert report.steps["registration"].unique_hosts == ["tickets.example.com"]
    assert report.human_wait_s == 4


def test_metrics_api_finished_demo_and_unknown(tmp_path):
    service = build_demo_service(delay=.005)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        session = prepare(client, "Milan")
        mid = confirm(client, session).json()["mission_id"]
        finished = finish(client, mid)
        response = client.get(f"/api/missions/{mid}/metrics")
        assert response.status_code == 200
        report = MissionMetrics.model_validate(response.json())
        assert report.status == finished["status"]
        assert len(report.steps) == 3
        assert all(step.duration_s > 0 and step.status for step in report.steps.values())
        assert client.get("/api/missions/unknown/metrics").status_code == 404


def cli(*args):
    return subprocess.run([sys.executable, "-m", "runai.trace_report", *map(str, args)],
                          check=False, capture_output=True, text=True)


def test_cli_json_all_and_markdown():
    result = cli(FIXTURE, "--json")
    assert result.returncode == 0, result.stderr
    report = MissionMetrics.model_validate_json(result.stdout)
    assert report.mission_id == "sample_mission" and len(report.steps) == 2
    all_reports = cli("--all", FIXTURE.parent, "--json")
    assert all_reports.returncode == 0, all_reports.stderr
    assert [MissionMetrics.model_validate(row).mission_id for row in json.loads(all_reports.stdout)] == ["sample_mission"]
    assert next(iter_traces(FIXTURE.parent))[0] == "sample_mission"
    markdown = cli(FIXTURE, "--md")
    assert markdown.returncode == 0 and "| Agent | Status |" in markdown.stdout
    assert "tickets.example.com" in markdown.stdout and "?token" not in markdown.stdout
    plain = cli(FIXTURE)
    assert plain.returncode == 0 and "Duration (s)" in plain.stdout


def test_cli_empty_and_error_cases(tmp_path, monkeypatch):
    empty = cli("--all", tmp_path, "--json")
    assert empty.returncode == 0 and json.loads(empty.stdout) == []
    missing = cli(tmp_path / "missing.jsonl")
    assert missing.returncode == 2 and "Trace path does not exist" in missing.stderr
    malformed = tmp_path / "malformed.jsonl"
    secret = "sensitive-malformed-trace"
    monkeypatch.setenv("HAI_API_KEY", secret)
    malformed.write_text(secret, encoding="utf-8")
    invalid = cli(malformed)
    assert invalid.returncode == 2 and "Cannot read trace" in invalid.stderr
    assert secret not in invalid.stderr
