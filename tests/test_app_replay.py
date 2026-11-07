import asyncio
import json
import subprocess
import sys

import httpx
import pytest

from runai.app.providers import ProviderUnavailableError, build_providers
from runai.app.replay import ReplayRaceSearch, ReplayTrace, ReplayTranscriber
from runai.config import ROOT
from runai.contracts.common import DataMode
from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    TraceEvent,
)
from runai.tracing import TraceWriter
from scripts.record_replay import main as record_replay

SNAPSHOT = {
    "id": "m1",
    "race": {"name": "Nairobi fixture race", "city": "Nairobi", "country": "KE"},
    "steps": [
        {
            "kind": "accommodation",
            "label": "Accommodation",
            "human_action": "Complete payment yourself",
            "status": "stopped_before_commitment",
            "summary": "TOTAL_PRICE_3_NIGHTS: 420 EUR",
            "price_eur": 420,
            "h_session_id": "h-real-1",
            "live_view_url": "https://platform.hcompany.ai/sessions/h-real-1",
            "data": {"provenance": {"mode": "live", "kind": "h_agent"}},
        }
    ],
    "questions": [
        {"kind": "accommodation", "question": "Budget?", "options": ["150 EUR"]}
    ],
    "events": [
        {
            "source": "agent:accommodation",
            "type": "action",
            "message": "Open Accor",
            "data": {"step": "accommodation"},
        },
        {"source": "app", "type": "step_started", "data": {"step": "transport"}},
    ],
}


def run_step(trace, kind):
    providers_trace = trace
    events, asked = [], []

    async def scenario():
        from runai.app.replay import ReplayBrowserAgents

        async def ask(question, options):
            asked.append(question)
            return options[0]

        agents = ReplayBrowserAgents(providers_trace)
        run = await agents.start(kind, "t", None, RunnerProfile(), events.append, ask)
        assert run.live_view_url is None
        return await run.wait()

    return asyncio.run(scenario()), events, asked


def test_replay_from_snapshot_is_labeled_and_never_live(tmp_path):
    trace = ReplayTrace.from_mission_snapshot(SNAPSHOT, label="Nairobi")
    path = tmp_path / "trace.json"
    trace.dump(path)
    loaded = ReplayTrace.load(path)
    assert loaded.recorded_mode is DataMode.live

    result, events, asked = run_step(loaded, StepKind.accommodation)
    assert (
        result.status is StepStatus.stopped_before_commitment
        and result.price_eur == 420
    )
    assert result.data["provenance"]["mode"] == "replay"
    assert result.data["provenance"]["kind"] == "replay"
    assert result.data["provenance"]["label"] == "Replay of “Nairobi” (recorded in live)"
    assert result.data["replay_of"] == "h-real-1"
    assert (
        result.h_session_id == "replay-accommodation" and result.live_view_url is None
    )
    assert [e.message for e in events] == ["Open Accor"]
    assert events[0].data["mode"] == "replay"
    assert asked == ["Budget?"]


def test_replay_missing_step_fails_honestly():
    trace = ReplayTrace.from_mission_snapshot(SNAPSHOT)
    result, _, _ = run_step(trace, StepKind.transport)
    assert result.status is StepStatus.failed
    assert result.error == "Step missing from the replayed trace."
    assert result.data["provenance"]["mode"] == "replay"


def test_replay_provider_set_reads_trace_file(tmp_path):
    trace = ReplayTrace(
        label="Lisbon",
        race=Race(name="Fixture race", city="Lisbon", country="PT"),
        transcript="a race in Lisbon",
        steps={
            StepKind.transport: {
                "result": StepResult(kind=StepKind.transport),
                "events": [TraceEvent(source="x", type="y")],
            }
        },
    )
    path = tmp_path / "t.json"
    trace.dump(path)
    providers = build_providers(
        env={"RUNAI_MODE": "replay", "RUNAI_REPLAY_TRACE": str(path)}, delay=0
    )
    assert providers.mode is DataMode.replay and providers.simulated
    assert asyncio.run(providers.search.find_race("x")).city == "Lisbon"
    assert (
        asyncio.run(providers.transcriber.transcribe(b"", "audio/wav"))
        == "a race in Lisbon"
    )
    assert providers.health_payload()["mode"] == "replay"


def test_default_replay_trace_is_complete_and_runs_offline(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    trace = ReplayTrace.load(ROOT / "fixtures/replay/default.json")
    kinds = {StepKind.registration, StepKind.accommodation, StepKind.transport}
    assert trace.recorded_mode is DataMode.demo
    assert trace.race is not None and trace.transcript
    assert kinds <= trace.steps.keys()
    providers = build_providers(env={"RUNAI_MODE": "replay"}, delay=0)
    assert providers.health_payload()["mode"] == "replay"
    assert providers.search.trace == trace
    for kind in kinds:
        assert trace.steps[kind].events
        result, events, _ = run_step(trace, kind)
        assert result.status is StepStatus.stopped_before_commitment
        assert result.data["provenance"]["mode"] == "replay"
        assert "recorded in demo" in result.data["provenance"]["label"]
        assert events and all(e.data["mode"] == "replay" for e in events)


def test_default_replay_missing_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr("runai.config.ROOT", tmp_path)
    with pytest.raises(ValueError, match="default replay.v1 trace is missing"):
        build_providers(env={"RUNAI_MODE": "replay"})


def test_explicit_trace_takes_precedence_over_environment(tmp_path):
    path = tmp_path / "explicit.json"
    ReplayTrace(label="Explicit recording").dump(path)
    providers = build_providers(
        env={"RUNAI_MODE": "replay", "RUNAI_REPLAY_TRACE": str(tmp_path / "missing.json")},
        replay_trace=path,
    )
    assert providers.search.trace.label == "Explicit recording"


def test_invalid_environment_override_does_not_silently_use_default(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_providers(env={"RUNAI_MODE": "replay", "RUNAI_REPLAY_TRACE": str(tmp_path / "missing.json")})


def test_missing_replay_inputs_report_english_errors():
    trace = ReplayTrace(label="Empty recording")
    with pytest.raises(ProviderUnavailableError, match="no race details"):
        asyncio.run(ReplayRaceSearch(trace).find_race("race"))
    with pytest.raises(ProviderUnavailableError, match="no transcript"):
        asyncio.run(ReplayTranscriber(trace).transcribe(b"", "audio/wav"))


def test_record_cli_reads_v2_snapshot_and_jsonl_events(monkeypatch, tmp_path):
    secret = "recording-test-secret-value"
    monkeypatch.setenv("HAI_API_KEY", secret)
    writer = TraceWriter("m1", traces_dir=tmp_path)
    writer.write(TraceEvent(source="agent:accommodation", type="action", message=secret,
                            data={"step": "accommodation"}))
    snapshot = {
        "mission_id": "m1", "race": SNAPSHOT["race"], "steps": SNAPSHOT["steps"],
        "questions": [{"step": "accommodation", "text": "Budget?", "choices": ["150 EUR"]}],
    }

    def fetch(url, **kwargs):
        assert url == "http://localhost:8000/api/missions/m1"
        return httpx.Response(200, json=snapshot, request=httpx.Request("GET", url))

    monkeypatch.setattr("scripts.record_replay.httpx.get", fetch)
    path = tmp_path / "recorded.json"
    race = tmp_path / "race.json"
    race.write_text(json.dumps({"name": "Override race", "city": "Milan", "country": "IT"}))
    record_replay([
        "--mission", "m1", "--base-url", "http://localhost:8000/",
        "--traces-dir", str(tmp_path), "--output", str(path), "--label", "Test recording",
        "--transcript", "Run in Milan", "--race-json", str(race),
    ])
    trace = ReplayTrace.load(path)
    assert trace.label == "Test recording" and trace.race.name == "Override race"
    assert trace.transcript == "Run in Milan"
    assert trace.recorded_mode is DataMode.live
    assert trace.steps[StepKind.accommodation].questions[0].options == ["150 EUR"]
    assert trace.steps[StepKind.accommodation].events[0].message == "[REDACTED]"
    assert secret not in path.read_text()


def test_record_cli_uses_embedded_snapshot_events(tmp_path):
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(SNAPSHOT))
    path = tmp_path / "recorded.json"
    record_replay(["--snapshot", str(source), "--output", str(path)])
    trace = ReplayTrace.load(path)
    assert trace.label == "Mission m1"
    assert len(trace.steps[StepKind.accommodation].events) == 1


def test_record_cli_rejects_missing_events(tmp_path, capsys):
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps({**SNAPSHOT, "events": []}))
    with pytest.raises(SystemExit) as error:
        record_replay(["--snapshot", str(source), "--traces-dir", str(tmp_path),
                       "--output", str(tmp_path / "recorded.json")])
    assert error.value.code == 1
    assert "Could not record replay" in capsys.readouterr().err
    assert not (tmp_path / "recorded.json").exists()


def test_record_cli_help_runs_directly_outside_repo(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/record_replay.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert "Export a mission snapshot" in result.stdout
    assert "--mission" in result.stdout and "--race-json" in result.stdout
