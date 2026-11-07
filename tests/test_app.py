import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import FakeBrowserAgents, FakeRaceSearch, FakeTranscriber
from runai.app.mission import Mission, MissionService, MissionStatus
from runai.app.server import MAX_AUDIO_BYTES, build_demo_service, create_app
from runai.app.tasks import (
    HUMAN_ACTIONS,
    build_task,
    extract_budget_per_night,
)
from runai.models import (
    AgentQuestion,
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


async def answer_fake_questions(service, mission):
    expected_questions = 4 - (
        extract_budget_per_night(mission.query, require_context=True) is not None
    )
    while len(mission.questions) < expected_questions or any(
        question.answer is None for question in mission.questions
    ):
        for question in mission.questions:
            if question.answer is None:
                service.answer_question(
                    mission.id, question.id, question.options[0]
                )
        await asyncio.sleep(0)


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

    async def start(
        self, kind, task, race, profile, on_event, ask_user, mission_id=None, query=""
    ):
        outcome = self.results[kind]
        if isinstance(outcome, Exception):
            return ScriptedRun(kind, error=outcome)
        return ScriptedRun(kind, result=outcome)


def test_build_task_is_guarded_and_uses_fake_profile():
    race = Race(name="Milano Marathon", city="Milan", country="IT")
    for kind in AGENT_KINDS:
        task = build_task(kind, race, RunnerProfile())
        assert task.endswith(STOP_INSTRUCTIONS)
        assert "ask_user" in task
        assert "au plus 2 questions" in task
        assert "BLOCAGE CAPTCHA/ANTI-BOT" in task
    registration = build_task(StepKind.registration, race, RunnerProfile())
    accommodation = build_task(StepKind.accommodation, race, RunnerProfile())
    transport = build_task(StepKind.transport, race, RunnerProfile())
    assert "camille.test@example.com" in registration
    assert "Milano Marathon" in registration
    assert "en invité" in registration
    assert "certificat médical" in registration
    assert "revendeur" in registration
    assert "Milan (IT)" in accommodation
    assert "PRIX_TOTAL_2_NUITS" in accommodation
    assert "Paris → Milan" in transport
    budget_task = build_task(
        StepKind.accommodation,
        race,
        RunnerProfile(),
        query="Marathon de Milan, budget hôtel max 150 € par nuit",
    )
    assert "150 € par nuit" in budget_task and "300 € maximum" in budget_task
    assert extract_budget_per_night("150 €") == 150
    assert extract_budget_per_night("Budget max 1 200,50 euros par nuit") == 1200.5
    with pytest.raises(ValueError):
        build_task(StepKind.search, race, RunnerProfile())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("300 € au total", 150),
        ("300 € pour les deux nuits", 150),
        ("150 € par nuit", 150),
        ("150 €", 150),
    ],
)
def test_extract_budget_per_night_normalizes_two_night_totals(text, expected):
    assert extract_budget_per_night(text) == expected


def test_hotel_budget_overrun_is_marked_failed():
    mission = Mission(
        id="budget-test",
        query="Marathon de Milan",
        steps={kind: StepResult(kind=kind) for kind in AGENT_KINDS},
        questions=[
            AgentQuestion(
                id="budget",
                kind=StepKind.accommodation,
                question="Budget max par nuit ?",
                options=["100 €", "150 €", "200 €"],
                answer="150 €",
            ),
            AgentQuestion(
                id="hotel-choice",
                kind=StepKind.accommodation,
                question="Quel hôtel choisissez-vous ?",
                options=["Ibis 180 €", "Novotel 210 €"],
                answer="Novotel 210 €",
            ),
        ],
    )
    result = StepResult(
        kind=StepKind.accommodation,
        status=StepStatus.stopped_before_commitment,
        summary="Novotel disponible.",
        price_eur=350,
    )

    filtered = MissionService._validate_hotel_budget(mission, result)

    assert filtered.status is StepStatus.failed
    assert filtered.data["budget_max_total_eur"] == 300
    assert filtered.data["over_budget"] is True
    assert "HORS BUDGET" in filtered.summary


def test_hotel_choice_with_prices_per_night_does_not_raise_budget_ceiling():
    mission = Mission(
        id="hotel-choice-budget-test",
        query="Marathon de Milan",
        steps={kind: StepResult(kind=kind) for kind in AGENT_KINDS},
        questions=[
            AgentQuestion(
                id="budget",
                kind=StepKind.accommodation,
                question="Budget max par nuit ?",
                options=["150 €"],
                answer="150 €",
            ),
            AgentQuestion(
                id="hotel-choice",
                kind=StepKind.accommodation,
                question="Lequel ? Ibis 180 € par nuit ou Novotel 210 € par nuit",
                options=["Ibis 180 € par nuit", "Novotel 210 € par nuit"],
                answer="Novotel 210 € par nuit",
            ),
        ],
    )
    result = StepResult(
        kind=StepKind.accommodation,
        status=StepStatus.stopped_before_commitment,
        summary="Novotel disponible.",
        price_eur=350,
    )

    filtered = MissionService._validate_hotel_budget(mission, result)

    assert filtered.status is StepStatus.failed
    assert filtered.data["budget_max_per_night_eur"] == 150
    assert filtered.data["over_budget"] is True
    assert "HORS BUDGET" in filtered.summary


def test_rephrased_hotel_budget_question_sets_the_per_night_ceiling():
    mission = Mission(
        id="rephrased-budget-test",
        query="Marathon de Milan",
        steps={kind: StepResult(kind=kind) for kind in AGENT_KINDS},
        questions=[
            AgentQuestion(
                id="budget",
                kind=StepKind.accommodation,
                question="Quel prix maximum par nuit ?",
                options=[],
                answer="120",
            )
        ],
    )
    result = StepResult(
        kind=StepKind.accommodation,
        status=StepStatus.stopped_before_commitment,
        summary="Hôtel disponible.",
        price_eur=230,
    )

    filtered = MissionService._validate_hotel_budget(mission, result)

    assert filtered.status is StepStatus.stopped_before_commitment
    assert filtered.data["budget_max_per_night_eur"] == 120


def test_every_stop_point_has_a_human_action():
    assert set(HUMAN_ACTIONS) == set(StopPoint)


@pytest.mark.anyio
async def test_full_fake_mission_stops_before_commitment(tmp_path):
    agents = FakeBrowserAgents(delay=0)
    service = make_service(tmp_path, agents=agents)
    mission = await service.create("Marathon de Milan, je pars de Paris")
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)

    assert mission.status is MissionStatus.awaiting_human
    assert mission.race.city == "Milan"
    assert any(
        question.question == "Budget max par nuit ?" for question in mission.questions
    )
    snapshot = mission.snapshot()
    assert [step["kind"] for step in snapshot["steps"]] == [
        kind.value for kind in AGENT_KINDS
    ]
    for step in snapshot["steps"]:
        assert step["status"] == "stopped_before_commitment"
        assert step["stop_point"] in {"consent", "payment"}
        assert step["human_action"]
        assert "Réponses utilisateur :" in step["summary"]
        assert step["data"]["live_view_path"].startswith("/demo/live?session=")
    assert all(run.task.endswith(STOP_INSTRUCTIONS) for run in agents.runs)
    registration_step = next(
        step
        for step in snapshot["steps"]
        if step["kind"] == StepKind.registration.value
    )
    assert "Oui, j'ai les deux" in registration_step["summary"]
    registration_questions = [
        question
        for question in mission.questions
        if question.kind is StepKind.registration
    ]
    assert registration_questions[0].question == (
        "Avez-vous une Runcard ou un certificat médical de compétition (ECG d'effort) ?"
    )
    assert registration_questions[0].options == ["Oui, j'ai les deux", "Pas encore"]
    assert len(registration_questions) == 2
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
    agents = FakeBrowserAgents(delay=0.02)
    service = make_service(tmp_path, agents=agents)
    mission = await service.create("Milan")
    await answer_fake_questions(service, mission)
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
        mission.id, StepKind.registration, "Prends plutôt le 10 km\n\nPas le semi"
    )
    await service.resume(mission.id, StepKind.registration)
    mission = await service.wait(mission.id)
    step = mission.steps[StepKind.registration]
    assert step.status is StepStatus.stopped_before_commitment
    assert "10 km" in step.summary
    assert step.data["messages"] == ["Prends plutôt le 10 km\n\nPas le semi"]
    (run,) = [run for run in agents.runs if run.kind is StepKind.registration]
    assert run.received == [
        f"Prends plutôt le 10 km\n\nPas le semi\n\n{STOP_INSTRUCTIONS}"
    ]
    assert "Pas le semi" in step.summary
    assert {event.type for event in mission.events} >= {
        "pause",
        "resume",
        "message",
        "message_ack",
    }


@pytest.mark.anyio
async def test_agent_question_waits_for_answer_and_resumes(tmp_path):
    agents = FakeBrowserAgents(delay=0)
    service = make_service(tmp_path, agents=agents)
    mission = await service.create("Marathon de Milan")

    while not mission.questions:
        await asyncio.sleep(0)
    question = mission.questions[0]
    step = mission.steps[question.kind]
    assert step.status is StepStatus.waiting_for_user
    assert question.answer is None
    assert question.kind.value in {
        item["kind"]
        for item in mission.snapshot()["steps"]
        if item["status"] == StepStatus.waiting_for_user.value
    }

    answer = question.options[0]
    service.answer_question(mission.id, question.id, answer)
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)

    result = mission.steps[question.kind]
    assert result.status is StepStatus.stopped_before_commitment
    assert answer in result.summary
    assert question.answered_at is not None
    assert {event.type for event in mission.events} >= {"question", "answer"}
    trace = TraceWriter(mission.id, traces_dir=tmp_path).read()
    assert any(event.type == "question" for event in trace)
    assert any(event.type == "answer" for event in trace)


@pytest.mark.anyio
async def test_fake_mission_uses_query_hotel_budget_without_asking_again(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0))
    mission = await service.create("marathon de Milan, hôtel 120 € par nuit")
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)

    assert not any(
        question.kind is StepKind.accommodation for question in mission.questions
    )
    result = mission.steps[StepKind.accommodation]
    assert result.data["budget_max_per_night_eur"] == 120
    assert result.data["budget_max_total_eur"] == 240


@pytest.mark.anyio
async def test_question_sse_event_and_timeout_answer(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0), delay=0)
    service.question_timeout_s = 0.01
    mission = await service.create("Marathon de Milan")
    events = service.subscribe(mission.id)
    await anext(events)
    names = []
    while "question" not in names or "answer" not in names:
        name, _ = await asyncio.wait_for(anext(events), timeout=1)
        names.append(name)
    mission = await service.wait(mission.id)
    assert "question" in names
    assert "answer" in names
    assert all(question.answer is not None for question in mission.questions)
    assert all(
        "arrête-toi ici et résume" in question.answer
        for question in mission.questions
    )
    await events.aclose()


def test_question_answer_endpoint_validation_and_history(tmp_path):
    service = make_service(tmp_path, delay=0)
    service.question_timeout_s = 60
    with TestClient(create_app(service)) as client:
        _assert_question_answer_endpoint(client)


def _assert_question_answer_endpoint(client):
    created = client.post(
        "/api/missions", json={"query": "Marathon de Milan, départ de Paris"}
    )
    assert created.status_code == 201
    mission_id = created.json()["id"]
    assert (
        client.post(
            f"/api/missions/{mission_id}/questions/not-a-question/answer",
            json={"answer": "150 €"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/missions/unknown/questions/q1/answer",
            json={"answer": "150 €"},
        ).status_code
        == 404
    )

    question = None
    for _ in range(100):
        snapshot = client.get(f"/api/missions/{mission_id}").json()
        question = next(
            (item for item in snapshot["questions"] if item["answer"] is None),
            None,
        )
        if question:
            break
        time.sleep(0.01)
    assert question is not None
    assert (
        client.post(
            f"/api/missions/{mission_id}/questions/{question['id']}/answer",
            json={"answer": "x" * 501},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/missions/{mission_id}/questions/{question['id']}/answer",
            json={"answer": " "},
        ).status_code
        == 422
    )

    answered = client.post(
        f"/api/missions/{mission_id}/questions/{question['id']}/answer",
        json={"answer": "150 €"},
    )
    assert answered.status_code == 200
    saved_question = next(
        item
        for item in answered.json()["questions"]
        if item["id"] == question["id"]
    )
    assert saved_question["answer"] == "150 €"
    assert saved_question["answered_at"] is not None
    assert (
        client.post(
            f"/api/missions/{mission_id}/questions/{question['id']}/answer",
            json={"answer": "200 €"},
        ).status_code
        == 409
    )
    for _ in range(1000):
        snapshot = client.get(f"/api/missions/{mission_id}").json()
        if len(snapshot["questions"]) == 4:
            break
        time.sleep(0.01)
    assert len(snapshot["questions"]) == 4
    for pending in snapshot["questions"]:
        if pending["answer"] is None:
            assert (
                client.post(
                    f"/api/missions/{mission_id}/questions/{pending['id']}/answer",
                    json={"answer": pending["options"][0]},
                ).status_code
                == 200
            )
    for _ in range(1000):
        final_snapshot = client.get(f"/api/missions/{mission_id}").json()
        if final_snapshot["status"] in {
            MissionStatus.awaiting_human.value,
            MissionStatus.failed.value,
        }:
            break
        time.sleep(0.01)
    assert final_snapshot["status"] in {
        MissionStatus.awaiting_human.value,
        MissionStatus.failed.value,
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
async def test_partial_failure_without_stop_fails_mission(tmp_path):
    agents = ScriptedAgents(
        {
            StepKind.registration: StepResult(
                kind=StepKind.registration,
                status=StepStatus.completed,
                summary="Infos relevées",
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
    assert mission.status is MissionStatus.failed


@pytest.mark.anyio
async def test_trace_write_failure_does_not_strand_mission(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    mission = await service.create("Milan")

    def broken_write(self, event):
        raise OSError("disque plein")

    monkeypatch.setattr(TraceWriter, "write", broken_write)
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)
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
        async def start(
            self,
            kind,
            task,
            race,
            profile,
            on_event,
            ask_user,
            mission_id=None,
            query="",
        ):
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
            return await super().start(
                kind, task, race, profile, on_event, ask_user, mission_id, query=query
            )

    service = make_service(tmp_path, agents=ThreadedAgents(delay=0))
    mission = await service.create("Milan")
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)
    assert sum(event.message == "depuis un thread" for event in mission.events) == 3


@pytest.mark.anyio
async def test_subscribe_receives_final_state(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0.01))
    mission = await service.create("Milan")
    answers = asyncio.create_task(answer_fake_questions(service, mission))
    messages = [message async for message in service.subscribe(mission.id)]
    await answers
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


def answer_questions_from_thread(service, mission):
    handled = set()
    loop = service._loop
    while not mission.is_terminal:
        for question in mission.questions:
            if question.answer is None and question.id not in handled:
                loop.call_soon_threadsafe(
                    service.answer_question,
                    mission.id,
                    question.id,
                    question.options[0],
                )
                handled.add(question.id)
        time.sleep(0.01)


def test_api_runs_a_demo_mission_with_sse(tmp_path):
    service = make_service(tmp_path, delay=0.01)
    app = create_app(service)
    with TestClient(app) as client:
        assert "RunAI" in client.get("/").text
        assert client.get("/api/health").json() == {
            "ok": True,
            "mode": "demo",
            "simulated": True,
        }

        created = client.post("/api/missions", json={"query": "Marathon de Milan"})
        assert created.status_code == 201
        mission_id = created.json()["id"]
        mission = service.get(mission_id)
        answers = threading.Thread(
            target=answer_questions_from_thread,
            args=(service, mission),
            daemon=True,
        )
        answers.start()

        with client.stream("GET", f"/api/missions/{mission_id}/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            events = read_sse(response)
        answers.join(timeout=2)
        assert not answers.is_alive()
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
        oversized = b"0" * (MAX_AUDIO_BYTES + 1)
        assert client.post("/api/transcribe", content=oversized).status_code == 413


@pytest.mark.anyio
async def test_demo_missions_do_not_wait_for_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    service = build_demo_service(delay=0)
    first = await service.create("Marathon de Milan")
    second = await service.create("Marathon de Milan")

    async def all_waiting(mission):
        while not all(
            step.status is StepStatus.waiting_for_user
            for step in mission.steps.values()
        ):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(
        asyncio.gather(all_waiting(first), all_waiting(second)), timeout=2
    )
    for mission in (first, second):
        await answer_fake_questions(service, mission)
        assert (await service.wait(mission.id)).status is MissionStatus.awaiting_human


def test_basic_auth_protects_everything_but_health(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "equipe:secret")
    with TestClient(create_app(make_service(tmp_path, delay=0))) as client:
        assert client.get("/api/health").status_code == 200
        denied = client.get("/")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"].startswith("Basic")
        assert client.post("/api/missions", json={"query": "Milan"}).status_code == 401
        assert client.get("/", auth=("equipe", "faux")).status_code == 401
        assert client.get("/", auth=("equipe", "secret")).status_code == 200
        assert client.get("/static/app.js", auth=("equipe", "secret")).status_code == 200


def test_basic_auth_rejects_malformed_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "sans-deux-points")
    with pytest.raises(ValueError), TestClient(create_app(make_service(tmp_path))) as client:
        client.get("/")


def test_public_real_mode_requires_a_password(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_PUBLIC", "1")
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    real = make_service(tmp_path)
    real.simulated = False
    with pytest.raises(RuntimeError):
        create_app(real)
    create_app(make_service(tmp_path))
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "equipe:secret")
    create_app(real)
