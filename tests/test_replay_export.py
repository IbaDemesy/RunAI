import asyncio

from fastapi.testclient import TestClient

from runai.app.mission import Mission, MissionStatus
from runai.app.providers import DEFAULT_REPLAY_TRACE, build_providers
from runai.app.replay import ReplayBrowserAgents, ReplayTrace
from runai.app.replay_export import export_replay
from runai.app.server import build_demo_service, create_app
from runai.contracts.common import DataMode
from runai.contracts.framing import FramingTurn
from runai.models import RunnerProfile, StepKind, StepResult
from scripts.record_replay import confirm_marathon, finish_mission


def test_export_finished_demo_round_trip(tmp_path):
    service = build_demo_service(delay=0)
    with TestClient(create_app(service)) as client:
        mid = confirm_marathon(client)
        finish_mission(client, mid)
        mission = service.get(mid)
        trace = export_replay(mission)
        assert trace.label == f"Replay of {mission.race.name} recorded in demo"
        assert trace.race == mission.race
        assert trace.transcript is None
        assert str(mission.race.race_date) in trace.steps[StepKind.registration].result.summary
        path = tmp_path / "trace.json"
        trace.dump(path)
        loaded = ReplayTrace.load(path)
        assert loaded.model_dump() == trace.model_dump()

        async def replay():
            async def answer(question, options):
                return options[0] if options else "Continue"

            agents = ReplayBrowserAgents(loaded)
            for kind in mission.plan.automated_steps():
                run = await agents.start(
                    kind, "Replay", loaded.race, RunnerProfile(), lambda event: None, answer,
                )
                result = await run.wait()
                assert result.status == mission.steps[kind].status
                assert result.data["provenance"]["mode"] == "replay"
                assert result.live_view_url is None

        asyncio.run(replay())


def test_route_status_headers_and_redaction(monkeypatch):
    monkeypatch.setenv("HAI_API_KEY", "test-secret-for-export")
    service = build_demo_service(delay=0)
    mission = Mission(id="export-test", query="Demo", steps={})
    service.missions[mission.id] = mission
    with TestClient(create_app(service)) as client:
        assert client.get("/api/missions/unknown/replay.json").status_code == 404
        url = f"/api/missions/{mission.id}/replay.json"
        assert client.get(url).status_code == 409
        mission.status = MissionStatus.completed
        mission.framing_turns = [FramingTurn(
            role="user", channel="voice", revision=1,
            text="Email runner@example.com, phone +33 612345678, test-secret-for-export",
        )]
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.headers["content-disposition"] == 'attachment; filename="export-test.replay.json"'
        assert response.json()["steps"] == {}
        assert "runner@example.com" not in response.text
        assert "612345678" not in response.text
        assert "test-secret-for-export" not in response.text
        mission.framing_turns = []
        assert export_replay(mission).transcript is None


def test_voice_transcript_and_structured_personal_fields():
    mission = Mission(id="private", query="Demo", status=MissionStatus.completed, steps={
        StepKind.registration: StepResult(kind=StepKind.registration, data={
            "profile": {"first_name": "Private", "birth_date": "1990-01-02"},
        }),
    }, framing_turns=[
        FramingTurn(role="user", channel="voice", revision=1, text="A marathon"),
        FramingTurn(role="user", channel="text", revision=2, text="Not voice"),
        FramingTurn(role="user", channel="voice", revision=3, text="In Milan"),
    ])
    trace = export_replay(mission)
    assert trace.transcript == "A marathon"
    assert trace.steps[StepKind.registration].result.data["profile"] == {
        "first_name": "[REDACTED]", "birth_date": "[REDACTED]",
    }


def test_default_replay_boots_and_finishes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNAI_MODE", "replay")
    monkeypatch.setenv("RUNAI_DEMO_DELAY", "0")
    monkeypatch.delenv("RUNAI_REPLAY_TRACE", raising=False)
    providers = build_providers(DataMode.replay, env={})
    assert providers.search.trace == ReplayTrace.load(DEFAULT_REPLAY_TRACE)
    assert providers.health["replay"].detail == "Default demo replay trace"
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["mode"] == "replay"
        mid = confirm_marathon(client)
        mission = finish_mission(client, mid)
        assert mission["status"] in {"awaiting_human", "completed"}
        trace = ReplayTrace.model_validate(client.get(f"/api/missions/{mid}/replay.json").json())
        for kind in (StepKind.registration, StepKind.accommodation, StepKind.transport):
            assert trace.steps[kind].result.data["provenance"]["mode"] == "replay"


def test_urls_with_long_numeric_ids_are_kept():
    url = "https://in.njuko.com/race/123456789/step?id=98765432"
    mission = Mission(id="url", query="Demo", status=MissionStatus.completed, steps={
        StepKind.registration: StepResult(kind=StepKind.registration, data={"url": url}),
    })
    assert export_replay(mission).steps[StepKind.registration].result.data["url"] == url


def test_phone_numbers_after_separators_are_redacted():
    mission = Mission(id="tel", query="Demo", status=MissionStatus.completed, steps={
        StepKind.registration: StepResult(kind=StepKind.registration, data={
            "note": "phone=33612345678 tel:33612345678",
        }),
    })
    note = export_replay(mission).steps[StepKind.registration].result.data["note"]
    assert "33612345678" not in note
