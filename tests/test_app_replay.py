import asyncio

from runai.app.providers import build_providers
from runai.app.replay import ReplayTrace
from runai.contracts.common import DataMode
from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    TraceEvent,
)

SNAPSHOT = {
    "id": "m1",
    "race": {"name": "Course fictive de Nairobi", "city": "Nairobi", "country": "KE"},
    "steps": [
        {
            "kind": "accommodation",
            "label": "Hébergement",
            "human_action": "Payez vous-même",
            "status": "stopped_before_commitment",
            "summary": "PRIX_TOTAL_3_NUITS: 420 EUR",
            "price_eur": 420,
            "h_session_id": "h-real-1",
            "live_view_url": "https://platform.hcompany.ai/sessions/h-real-1",
            "data": {"provenance": {"mode": "live", "kind": "h_agent"}},
        }
    ],
    "questions": [
        {"kind": "accommodation", "question": "Budget ?", "options": ["150 €"]}
    ],
    "events": [
        {
            "source": "agent:accommodation",
            "type": "action",
            "message": "Ouvre Accor",
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
    assert "enregistré en live" in result.data["provenance"]["label"]
    assert result.data["replay_of"] == "h-real-1"
    assert (
        result.h_session_id == "replay-accommodation" and result.live_view_url is None
    )
    assert [e.message for e in events] == ["Ouvre Accor"]
    assert events[0].data["mode"] == "replay"
    assert asked == ["Budget ?"]


def test_replay_missing_step_fails_honestly():
    trace = ReplayTrace.from_mission_snapshot(SNAPSHOT)
    result, _, _ = run_step(trace, StepKind.transport)
    assert result.status is StepStatus.failed
    assert "absente" in result.error
    assert result.data["provenance"]["mode"] == "replay"


def test_replay_provider_set_reads_trace_file(tmp_path):
    trace = ReplayTrace(
        label="Lisbonne",
        race=Race(name="Corrida fictive", city="Lisbonne", country="PT"),
        transcript="une course à Lisbonne",
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
    assert asyncio.run(providers.search.find_race("x")).city == "Lisbonne"
    assert (
        asyncio.run(providers.transcriber.transcribe(b"", "audio/wav"))
        == "une course à Lisbonne"
    )
    assert providers.health_payload()["mode"] == "replay"
