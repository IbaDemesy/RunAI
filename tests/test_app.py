import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import FakeBrowserAgents, FakeRaceSearch, FakeTranscriber
from runai.app.mission import MissionService, MissionStatus
from runai.app.server import create_app
from runai.app.tasks import HUMAN_ACTIONS, build_task
from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
    TraceEvent,
)
from runai.safety import STOP_INSTRUCTIONS
from runai.tracing import TraceWriter

AGENT_KINDS = (StepKind.registration, StepKind.accommodation, StepKind.transport)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_service(tmp_path, agents=None, search=None, delay=0.0):
    return MissionService(
        search or FakeRaceSearch(delay=delay),
        agents or FakeBrowserAgents(delay=delay),
        FakeTranscriber(delay=0),
        traces_dir=tmp_path,
        simulated=True,
    )


class ScriptedRun:
    def __init__(self, kind, result=None, error=None):
        self.session_id = f"scripted-{kind.value}"
        self.live_view_url = f"https://live.example.org/{kind.value}"
        self._result = result
        self._error = error

    async def pause(self):
        pass

    async def resume(self):
        pass

    async def send_message(self, text):
        pass

    async def wait(self):
        await asyncio.sleep(0)
        if self._error:
            raise self._error
        return self._result


class ScriptedAgents:
    def __init__(self, results):
        self.results = results

    async def start(self, kind, task, race, profile, on_event):
        outcome = self.results[kind]
        if isinstance(outcome, Exception):
            return ScriptedRun(kind, error=outcome)
        return ScriptedRun(kind, result=outcome)


def test_build_task_is_guarded_and_uses_fake_profile():
    race = Race(name="Milano Marathon", city="Milan", country="IT")
    for kind in AGENT_KINDS:
        task = build_task(kind, race, RunnerProfile())
        assert task.endswith(STOP_INSTRUCTIONS)
        assert "camille.test@example.com" in task
    assert "Booking.com" in build_task(StepKind.accommodation, race, RunnerProfile())
    with pytest.raises(ValueError):
        build_task(StepKind.search, race, RunnerProfile())


def test_every_stop_point_has_a_human_action():
    assert set(HUMAN_ACTIONS) == set(StopPoint)


@pytest.mark.anyio
async def test_full_fake_mission_stops_before_commitment(tmp_path):
    agents = FakeBrowserAgents(delay=0)
    service = make_service(tmp_path, agents=agents)
    mission = await service.create("Marathon de Milan, je pars de Paris")
    mission = await service.wait(mission.id)

    assert mission.status is MissionStatus.awaiting_human
    assert mission.race.city == "Milan"
    snapshot = mission.snapshot()
    assert [step["kind"] for step in snapshot["steps"]] == [
        kind.value for kind in AGENT_KINDS
    ]
    for step in snapshot["steps"]:
        assert step["status"] == "stopped_before_commitment"
        assert step["stop_point"] in {"consent", "payment"}
        assert step["human_action"]
        assert step["data"]["live_view_path"].startswith("/demo/live?session=")
    assert all(run.task.endswith(STOP_INSTRUCTIONS) for run in agents.runs)
    trace = TraceWriter(mission.id, traces_dir=tmp_path).read()
    assert trace[0].type == "mission_created"
    assert trace[-1].type == "mission_done"
    assert any(event.source == "agent:registration" for event in trace)


@pytest.mark.anyio
async def test_lisbon_query_picks_lisbon_demo_race():
    race = await FakeRaceSearch(delay=0).find_race("Je veux courir à Lisboa")
    assert race.city == "Lisbonne"


@pytest.mark.anyio
async def test_pause_resume_and_message(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0.02))
    mission = await service.create("Milan")
    while mission.steps[StepKind.registration].status is not StepStatus.running:
        await asyncio.sleep(0.005)
    while service.get(mission.id).steps[StepKind.registration].h_session_id is None:
        await asyncio.sleep(0.005)

    await service.pause(mission.id, StepKind.registration)
    assert mission.steps[StepKind.registration].status is StepStatus.paused
    actions_before = len(mission.events)
    await asyncio.sleep(0.15)
    paused_actions = [
        event
        for event in mission.events[actions_before:]
        if event.source == "agent:registration" and event.type == "action"
    ]
    assert len(paused_actions) <= 1

    await service.send_message(
        mission.id, StepKind.registration, "Prends plutôt le 10 km"
    )
    await service.resume(mission.id, StepKind.registration)
    mission = await service.wait(mission.id)
    step = mission.steps[StepKind.registration]
    assert step.status is StepStatus.stopped_before_commitment
    assert "10 km" in step.summary
    assert step.data["messages"] == ["Prends plutôt le 10 km"]
    assert {event.type for event in mission.events} >= {
        "pause",
        "resume",
        "message",
        "message_ack",
    }


@pytest.mark.anyio
async def test_summary_mentioning_payment_is_treated_as_stop(tmp_path):
    agents = ScriptedAgents(
        {
            StepKind.registration: StepResult(
                kind=StepKind.registration,
                status=StepStatus.completed,
                summary="Proceed to payment",
            ),
            StepKind.accommodation: RuntimeError("H indisponible"),
            StepKind.transport: StepResult(
                kind=StepKind.transport,
                status=StepStatus.completed,
                summary="Horaires relevés",
            ),
        }
    )
    service = make_service(tmp_path, agents=agents)
    mission = await service.wait((await service.create("Milan")).id)

    registration = mission.steps[StepKind.registration]
    assert registration.status is StepStatus.stopped_before_commitment
    assert registration.stop_point is StopPoint.payment
    assert str(registration.live_view_url) == "https://live.example.org/registration"
    assert mission.steps[StepKind.accommodation].status is StepStatus.failed
    assert mission.steps[StepKind.accommodation].error == "H indisponible"
    assert mission.steps[StepKind.transport].status is StepStatus.completed
    assert mission.status is MissionStatus.awaiting_human


@pytest.mark.anyio
async def test_failed_search_fails_mission(tmp_path):
    class BrokenSearch:
        async def find_race(self, query):
            raise RuntimeError("Linkup indisponible")

    service = make_service(tmp_path, search=BrokenSearch())
    mission = await service.wait((await service.create("Milan")).id)
    assert mission.status is MissionStatus.failed
    assert "Linkup indisponible" in mission.error


@pytest.mark.anyio
async def test_events_from_another_thread_are_recorded(tmp_path):
    class ThreadedAgents(FakeBrowserAgents):
        async def start(self, kind, task, race, profile, on_event):
            thread = threading.Thread(
                target=on_event,
                args=(
                    TraceEvent(
                        source=f"agent:{kind.value}",
                        type="action",
                        message="depuis un thread",
                    ),
                ),
            )
            thread.start()
            thread.join()
            return await super().start(kind, task, race, profile, on_event)

    service = make_service(tmp_path, agents=ThreadedAgents(delay=0))
    mission = await service.wait((await service.create("Milan")).id)
    assert sum(event.message == "depuis un thread" for event in mission.events) == 3


@pytest.mark.anyio
async def test_subscribe_receives_final_state(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0.01))
    mission = await service.create("Milan")
    messages = [message async for message in service.subscribe(mission.id)]
    assert messages[0][0] == "snapshot"
    assert messages[-1][0] == "mission"
    assert messages[-1][1]["status"] == "awaiting_human"


def read_sse(response):
    events = []
    name = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((name, json.loads(line.removeprefix("data: "))))
    return events


def test_api_runs_a_demo_mission_with_sse(tmp_path):
    app = create_app(make_service(tmp_path, delay=0.01))
    with TestClient(app) as client:
        assert "RunAI" in client.get("/").text
        assert client.get("/api/health").json() == {"ok": True, "simulated": True}

        created = client.post("/api/missions", json={"query": "Marathon de Milan"})
        assert created.status_code == 201
        mission_id = created.json()["id"]

        with client.stream("GET", f"/api/missions/{mission_id}/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            events = read_sse(response)
        names = [name for name, _ in events]
        assert names[0] == "snapshot"
        assert "trace" in names
        assert names[-1] == "end"
        final = [data for name, data in events if name == "mission"][-1]
        assert final["status"] == "awaiting_human"

        mission = client.get(f"/api/missions/{mission_id}").json()
        session_id = mission["steps"][1]["h_session_id"]
        live = client.get(f"/api/live/{session_id}").json()
        assert live["label"] == "Hébergement"
        assert live["history"]
        assert client.get("/demo/live").status_code == 200

        assert (
            client.post(
                f"/api/missions/{mission_id}/steps/registration/pause"
            ).status_code
            == 409
        )
        assert client.get("/api/missions/inconnue").status_code == 404
        assert client.post("/api/missions", json={"query": ""}).status_code == 422


def test_api_transcribe_uses_voice_port(tmp_path):
    with TestClient(create_app(make_service(tmp_path))) as client:
        response = client.post(
            "/api/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"}
        )
        assert response.json() == {"text": FakeTranscriber.TEXT}
        assert client.post("/api/transcribe", content=b"").status_code == 400
