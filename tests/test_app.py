import asyncio
import json
import threading
import time
from datetime import date
from types import SimpleNamespace
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from runai.app.candidates import FixtureCandidateSearch
from runai.app.fakes import (
    DEMO_RACES,
    FakeBrowserAgents,
    FakeRaceSearch,
    FakeTranscriber,
)
from runai.app.mission import Mission, MissionService, MissionStatus
from runai.app.server import MAX_AUDIO_BYTES, create_app
from runai.app.tasks import (
    HUMAN_ACTIONS,
    STEP_LABELS,
    TripBrief,
    build_task,
    extract_budget_per_night,
)
from runai.contracts.common import DataMode
from runai.contracts.framing import (
    FramingConfirm,
    FramingCreate,
    FramingReply,
    FramingTurn,
)
from runai.contracts.mission import HumanAnswer
from runai.framing.engine import FramingEngine
from runai.framing.launch import LaunchPlan, StepPlan
from runai.h.runner import HRun
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


@pytest.mark.anyio
async def test_country_only_demo_request_offers_only_recorded_alternatives():
    candidate_search = FixtureCandidateSearch(
        list(DEMO_RACES.values()), DataMode.demo
    )
    result = await candidate_search.search(
        {}, request_text="A half marathon in China"
    )
    assert {candidate.name for candidate in result.candidates} == {
        race.name for race in DEMO_RACES.values()
    }
    assert len(result.candidates) == len(DEMO_RACES)
    assert all(any(limit.code == "close_match" for limit in candidate.limitations)
               for candidate in result.candidates)
    assert [limit.code for limit in result.limitations] == ["demo_closest"]


def test_live_h_progress_and_separate_views_reach_snapshot_and_sse(tmp_path, monkeypatch):
    monkeypatch.setenv("HAI_API_KEY_2", "FAKE-H-PROGRESS-SENTINEL")
    service = make_service(tmp_path)
    mission = Mission(id="live-progress", query="course", status=MissionStatus.running,
                      race=DEMO_RACES["milan"], plan=unit_plan(),
                      steps={kind: StepResult(kind=kind, status=StepStatus.running) for kind in AGENT_KINDS})
    service.missions[mission.id] = mission
    service._writers[mission.id] = TraceWriter(mission.id, traces_dir=tmp_path)
    service._runs[(mission.id, StepKind.registration)] = SimpleNamespace(
        session_id="h-session", live_view_url="https://live.example.org/browser",
        agent_view_url="https://platform.hcompany.ai/agent-view/test",
        browser_observation={"revision": 1, "url": "https://example.com/", "title": "Page H"},
    )
    event = TraceEvent(source="h", type="action", message="Lecture FAKE-H-PROGRESS-SENTINEL",
                       data={"step": "registration", "h_session_id": "h-session"})
    service._record(mission, event)
    metrics = TraceEvent(source="h", type="MetricsUpdateEvent", data={"step": "registration"})
    service._record(mission, metrics)
    service._record(mission, TraceEvent(source="h", type="AgentRunStatusChangeEvent", message="running",
                                       data={"step": "registration"}))
    mission.steps[StepKind.registration].data["events"] = 2
    service._record(mission, TraceEvent(source="human", type="answer", message="Réponse privée",
                                       data={"step": "registration"}))
    snapshot = service.snapshot(mission.id).model_dump(mode="json")
    step = snapshot["steps"][0]
    assert step["live_view_url"] == "https://live.example.org/browser"
    assert step["agent_view_url"] == "https://platform.hcompany.ai/agent-view/test"
    assert step["data"]["last_action"] == "Lecture [REDACTED]"
    assert step["data"]["history"] == [
        {"at": event.at.isoformat(), "message": "Lecture [REDACTED]", "type": "action"},
        {"at": metrics.at.isoformat(), "message": None, "type": "MetricsUpdateEvent"},
        {"at": mission.events[2].at.isoformat(), "message": "running", "type": "AgentRunStatusChangeEvent"},
    ]
    assert step["data"]["events"] == 2
    assert step["data"]["browser_observation"] == {"revision": 1, "url": "https://example.com/", "title": "Page H"}
    assert snapshot["steps"][1]["data"]["history"] == []
    state = next(envelope for envelope in reversed(mission.envelopes) if envelope.type == "step")
    assert state.payload["steps"][0]["live_view_url"] == step["live_view_url"]
    assert state.payload["steps"][0]["agent_view_url"] == step["agent_view_url"]
    assert state.payload["steps"][0]["data"]["browser_observation"] == step["data"]["browser_observation"]
    assert "FAKE-H-PROGRESS-SENTINEL" not in state.to_sse()


def test_observation_trace_stores_a_friendly_headline_and_keeps_raw_action(tmp_path):
    service = make_service(tmp_path)
    mission = Mission(
        id="observation-headline",
        query="course",
        status=MissionStatus.running,
        race=DEMO_RACES["milan"],
        plan=unit_plan(),
        steps={kind: StepResult(kind=kind, status=StepStatus.running) for kind in AGENT_KINDS},
    )
    service.missions[mission.id] = mission
    service._writers[mission.id] = TraceWriter(mission.id, traces_dir=tmp_path)
    service._record(
        mission,
        TraceEvent(
            source="h",
            type="AgentEvent.observation_event",
            message="Title — https://www.example.com/",
            data={
                "step": "registration",
                "event": {
                    "type": "AgentEvent",
                    "data": {
                        "kind": "observation_event",
                        "metadata": {
                            "title": "Title",
                            "url": "https://www.example.com/",
                        },
                    },
                },
            },
        ),
    )

    step = mission.steps[StepKind.registration]
    assert step.data["headline"] == "On example.com · Title"
    assert step.data["last_action"] == "Title — https://www.example.com/"


@pytest.mark.anyio
@pytest.mark.parametrize("raises", [False, True])
async def test_agent_question_uses_framing_phraser_with_known_context(tmp_path, raises):
    class RecordingPhraser:
        calls: ClassVar[list] = []

        async def phrase(self, turns, question, known):
            self.calls.append((list(turns), question, dict(known)))
            if raises:
                raise RuntimeError("phrasing unavailable")
            return "Phrase naturelle"

    phraser = RecordingPhraser()
    service = make_service(tmp_path)
    service.phraser = phraser
    turns = [FramingTurn(role="user", text="Je prépare Milan", revision=1)]
    mission = Mission(
        id="phrased-question",
        query="course",
        status=MissionStatus.running,
        race=DEMO_RACES["milan"],
        plan=unit_plan(budget_total_eur=500, budget_per_night_eur=250),
        framing_turns=turns,
        steps={kind: StepResult(kind=kind, status=StepStatus.running) for kind in AGENT_KINDS},
    )
    service.missions[mission.id] = mission
    service._writers[mission.id] = TraceWriter(mission.id, traces_dir=tmp_path)
    asking = asyncio.create_task(
        service.ask(mission.id, StepKind.registration, "Quel sas ?", ["Discovery", "Performance"])
    )
    while not mission.questions:
        await asyncio.sleep(0)
    question = mission.questions[0]
    wrapped = service.questions.get(question.id)

    assert question.question == "Quel sas ?"
    assert question.display_text == ("Quel sas ?" if raises else "Phrase naturelle")
    assert wrapped.text == "Quel sas ?"
    assert wrapped.display_text == question.display_text
    assert phraser.calls == [(turns, "Quel sas ?", {
        "course": "Wizz Air Milano Marathon 2027",
        "dates": "2027-04-11 ; 2027-04-03 → 2027-04-05",
        "origin": "Paris",
        "budget": "500 € total, 250 € per night",
        "transport": "train",
    })]
    service.answer_question(
        mission.id,
        question.id,
        HumanAnswer(answer="Discovery", revision=mission.plan.revision, idempotency_key="test-answer"),
    )
    await asking


def test_create_app_reuses_the_same_framing_phraser(tmp_path):
    service = make_service(tmp_path)
    app = create_app(service)

    assert service.phraser is app.state.framing.phraser


@pytest.mark.parametrize("outcome", ["normal", "missing", "failure", "badpng", "oversized", "cross_session"])
def test_screenshot_proxy_uses_owning_sdk_and_never_exposes_source(tmp_path, outcome):
    calls = []
    png = b"\x89PNG\r\n\x1a\nimage"

    class Resources:
        async def get_session_resource(self, id, bucket, key):
            calls.append((id, bucket, key))
            if outcome == "failure":
                raise RuntimeError("FAKE-SCREENSHOT-TOKEN")
            yield b"x" * (8 * 1024 * 1024 + 1) if outcome == "oversized" else b"html" if outcome == "badpng" else png

    service = make_service(tmp_path)
    mission = Mission(id="capture-test", query="course", status=MissionStatus.completed, plan=unit_plan(),
                      steps={kind: StepResult(kind=kind) for kind in AGENT_KINDS})
    service.missions[mission.id] = mission
    owner = SimpleNamespace(client=SimpleNamespace(sessions=Resources()))
    run = HRun(None, owner, SimpleNamespace(id="s1"), StepKind.registration, TraceWriter("capture-test", traces_dir=tmp_path))
    sid = "other-session" if outcome == "cross_session" else "s1"
    if outcome != "missing":
        run._capture_reference(f"https://agp.eu.hcompany.ai/api/v1/trajectories/{sid}/resources/screens/{sid}/shot.png?token=FAKE-SCREENSHOT-TOKEN", {})
    service._capture_runs[(mission.id, StepKind.registration)] = run
    with TestClient(create_app(service)) as client:
        response = client.get("/api/missions/capture-test/steps/registration/screenshot")
        assert response.status_code == (404 if outcome in {"missing", "cross_session"} else 502 if outcome in {"failure", "badpng", "oversized"} else 200)
        assert "FAKE-SCREENSHOT-TOKEN" not in response.text
        if outcome == "normal":
            assert response.content == png
            assert response.headers["content-type"] == "image/png"
            assert response.headers["cache-control"] == "no-store"
        assert calls == ([] if outcome in {"missing", "cross_session"} else [("s1", "screens", "s1/shot.png")])
        assert client.get("/api/missions/unknown/steps/registration/screenshot").status_code == 404
        assert client.get("/api/missions/capture-test/steps/accommodation/screenshot").status_code == 404


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


def task_brief(**updates):
    values = {
        "race_label": "Wizz Air Milano Marathon 2027", "city": "Milan", "country": "IT",
        "race_date": date(2027, 4, 11), "distance_km": 42.195,
        "arrival": date(2027, 4, 3), "departure": date(2027, 4, 5), "nights": 2,
        "origin": "Paris", "transport_mode": "train",
        "hotel_landmarks": ["départ Corso Sempione", "retrait des dossards Via Moncucco 35"],
        "health_question": "Avez-vous une Runcard ou un certificat médical de compétition (ECG d'effort) ?",
        "registration_platform": "Njuko", "accommodation_site": "official Accor site",
        "accommodation_url": "https://all.accor.com", "transport_site": "trenitalia.com",
        "transport_url": "https://www.trenitalia.com",
    }
    return TripBrief(**(values | updates))


def unit_plan(**updates):
    return LaunchPlan(framing_id="unit-framing", revision=1, mode=DataMode.demo,
                      race=DEMO_RACES["milan"], brief=task_brief(**updates),
                      steps={k: StepPlan(kind=k, automation="automated") for k in AGENT_KINDS})


async def create_confirmed(service, query):
    engine = FramingEngine(FixtureCandidateSearch([DEMO_RACES["milan"]], DataMode.demo), DataMode.demo)
    session = await engine.create(
        FramingCreate(
            text=(
                "une course à Milan, 42.195 km en avril 2027, depuis Paris, "
                "500 euros, 2 nuits, train"
            )
        )
    )
    session = await engine.reply(session.id, FramingReply(revision=session.revision, choice_id=session.candidates[0].id))
    budget = extract_budget_per_night(query, require_context=True)
    session = await engine.reply(session.id, FramingReply(revision=session.revision, corrections={
        "origin": "Paris", "budget": budget * 2 if budget is not None else None,
        "nights": 2, "transport_mode": "train",
    }))
    snapshot = await engine.confirm(session.id, FramingConfirm(revision=session.revision, idempotency_key="test-confirm"), service.confirm)
    return service.get(snapshot.mission_id)


def api_confirm(client, city="Milan"):
    distance = "42.195 km" if city == "Milan" else "10 km"
    period = "avril 2027" if city == "Milan" else "juin 2028"
    session = client.post("/api/framings", json={
        "text": (
            f"une course à {city}, {distance} en {period}, depuis Paris, "
            "500 euros, 2 nuits, train"
        )
    }).json()
    session = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
    }).json()
    session = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "corrections": {
            "origin": "Paris", "budget": None, "nights": 2, "transport_mode": "train",
        },
    }).json()
    return client.post(f"/api/framings/{session['id']}/confirm", json={
        "revision": session["revision"], "idempotency_key": "test-confirm",
    })


async def answer_fake_questions(service, mission):
    while len(mission.questions) < 2 or any(q.answer is None for q in mission.questions):
        for question in list(mission.questions):
            wrapped = service.questions.get(question.id)
            if wrapped.status.value == "open":
                service.answer_question(mission.id, question.id, HumanAnswer(
                    answer=question.options[0], revision=wrapped.revision,
                    idempotency_key=f"answer-{question.id}",
                ))
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
        self, kind, task, race, profile, on_event, ask_user, mission_id=None, query="", **kwargs
    ):
        outcome = self.results[kind]
        if isinstance(outcome, Exception):
            return ScriptedRun(kind, error=outcome)
        return ScriptedRun(kind, result=outcome)


def test_build_task_is_guarded_and_uses_fake_profile():
    race = Race(name="Milano Marathon", city="Milan", country="IT")
    for kind in AGENT_KINDS:
        task = build_task(kind, race, RunnerProfile(), brief=task_brief())
        assert task.endswith(STOP_INSTRUCTIONS)
        assert "ask_user" in task
        assert "au plus 2 questions" in task
        assert "BLOCAGE CAPTCHA/ANTI-BOT" in task
    registration = build_task(StepKind.registration, race, RunnerProfile(), brief=task_brief())
    accommodation = build_task(StepKind.accommodation, race, RunnerProfile(), brief=task_brief())
    transport = build_task(StepKind.transport, race, RunnerProfile(), brief=task_brief())
    assert "camille.test@example.com" in registration
    assert "Wizz Air Milano Marathon 2027" in registration
    assert "en invité" in registration
    assert "Runcard" not in registration and "ECG d'effort" not in registration
    assert "Avant de poursuivre, demande exactement avec ask_user" not in registration
    assert (
        "Ne pose aucune question de santé : le certificat médical ou le PPS "
        "sera fourni par l'utilisateur lui-même."
    ) in registration
    assert (
        "Ne redemande jamais une information déjà donnée ci-dessus "
        "(dates, budget, ville de départ, distance, mode de transport)."
    ) in registration
    assert (
        "Utilise ask_user uniquement pour un choix qui dépend du site "
        "(sas, taille de t-shirt, hôtel parmi plusieurs offres, horaire, tarif) ; "
        "pose au plus 2 questions."
    ) in registration
    assert "Klikego" in registration
    assert "ask_user" in registration
    assert "3 avril 2027" in accommodation and "5 avril 2027" in accommodation
    assert "all.accor.com" in accommodation
    assert "PRIX_TOTAL_2_NUITS" in accommodation
    assert all(
        site in accommodation
        for site in ("Booking.com", "Expedia", "Hotels.com", "Airbnb")
    )
    assert "Corso Sempione" in accommodation and "Via Moncucco 35" in accommodation
    assert "trenitalia.com" in transport and "Paris" in transport
    assert "jamais TAP" in transport
    budget_task = build_task(
        StepKind.accommodation,
        race,
        RunnerProfile(),
        brief=task_brief(budget_per_night_eur=150),
    )
    assert "150 € par nuit" in budget_task and "300 € maximum" in budget_task
    assert (
        "Pas de plafond de budget : propose les meilleures options qualité-prix "
        "et donne leur prix."
    ) in build_task(
        StepKind.accommodation,
        race,
        RunnerProfile(),
        brief=task_brief(budget_open=True),
    )
    assert "Budget max par nuit ?" in accommodation
    assert "Budget max par nuit ?" not in build_task(
        StepKind.accommodation,
        race,
        RunnerProfile(),
        brief=task_brief(budget_open=True),
    )
    assert extract_budget_per_night("150 €") == 150
    assert extract_budget_per_night("Budget max 1 200,50 euros par nuit") == 1200.5
    with pytest.raises(ValueError):
        build_task(StepKind.search, race, RunnerProfile(), brief=task_brief())


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
        plan=unit_plan(budget_per_night_eur=150),
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
    assert "OVER BUDGET" in filtered.summary


def test_hotel_choice_with_prices_per_night_does_not_raise_budget_ceiling():
    mission = Mission(
        id="hotel-choice-budget-test",
        query="Marathon de Milan",
        plan=unit_plan(budget_per_night_eur=150),
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
    assert "OVER BUDGET" in filtered.summary


def test_rephrased_hotel_budget_question_sets_the_per_night_ceiling():
    mission = Mission(
        id="rephrased-budget-test",
        query="Marathon de Milan",
        plan=unit_plan(budget_per_night_eur=120),
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
@pytest.mark.parametrize("kind", [StepKind.accommodation, StepKind.registration])
async def test_fake_summary_omits_empty_answers_and_instructions(kind):
    async def answer(question, options):
        return options[0]

    agents = FakeBrowserAgents(delay=0)
    run = await agents.start(kind, "test", DEMO_RACES["milan"], RunnerProfile(), lambda event: None, answer)
    result = await run.wait()

    assert ("Your answers:" in result.summary) == (kind is StepKind.registration)
    assert "Instructions applied:" not in result.summary
    assert " : ." not in result.summary
    assert ": ." not in result.summary


@pytest.mark.anyio
async def test_full_fake_mission_stops_before_commitment(tmp_path):
    agents = FakeBrowserAgents(delay=0)
    service = make_service(tmp_path, agents=agents)
    mission = await create_confirmed(service, "Marathon de Milan, je pars de Paris")
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)

    assert mission.status is MissionStatus.awaiting_human
    assert mission.race.city == "Milan"
    assert not any(question.kind is StepKind.accommodation for question in mission.questions)
    snapshot = mission.snapshot()
    assert [step["kind"] for step in snapshot["steps"]] == [
        kind.value for kind in AGENT_KINDS
    ]
    for step in snapshot["steps"]:
        assert step["status"] == "stopped_before_commitment"
        assert step["stop_point"] in {"consent", "payment"}
        assert step["human_action"]
        assert ("Your answers:" in step["summary"]) == (step["kind"] != StepKind.accommodation.value)
        assert step["data"]["live_view_path"].startswith("/demo/live?session=")
    assert all(run.task.endswith(STOP_INSTRUCTIONS) for run in agents.runs)
    registration_step = next(
        step
        for step in snapshot["steps"]
        if step["kind"] == StepKind.registration.value
    )
    assert "Under 3h30" in registration_step["summary"]
    registration_questions = [
        question
        for question in mission.questions
        if question.kind is StepKind.registration
    ]
    assert registration_questions[0].question == (
        "Which start corral should I pick?"
    )
    assert registration_questions[0].options == ["Under 3h30", "3h30–4h", "Over 4h"]
    assert len(registration_questions) == 1
    trace = TraceWriter(mission.id, traces_dir=tmp_path).read()
    assert trace[0].type == "mission_created"
    assert trace[-1].type == "mission_done"
    assert any(event.source == "agent:registration" for event in trace)


@pytest.mark.anyio
async def test_lisbon_query_picks_lisbon_demo_race():
    race = await FakeRaceSearch(delay=0).find_race("Je veux courir à Lisboa")
    assert race.city == "Lisbon"


@pytest.mark.anyio
async def test_pause_resume_and_message(tmp_path):
    agents = FakeBrowserAgents(delay=0.02)
    service = make_service(tmp_path, agents=agents)
    mission = await create_confirmed(service, "Milan")
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
    mission = await create_confirmed(service, "Marathon de Milan")

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
    service.answer_question(mission.id, question.id, HumanAnswer(answer=answer, revision=mission.plan.revision, idempotency_key='test-answer'))
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
    mission = await create_confirmed(service, "marathon de Milan, hôtel 120 € par nuit")
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)

    assert not any(
        question.kind is StepKind.accommodation for question in mission.questions
    )
    result = mission.steps[StepKind.accommodation]
    assert result.data["budget_max_total_eur"] == 240
    assert result.data["budget_max_total_eur"] == 240


@pytest.mark.anyio
async def test_question_sse_event_and_timeout_answer(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0), delay=0)
    service.question_timeout_s = 0.01
    mission = await create_confirmed(service, "Marathon de Milan")
    events = service.subscribe(mission.id)
    await anext(events)
    names = []
    async for name, _ in events:
        names.append(name)
    mission = await service.wait(mission.id)
    assert "question" in names
    assert "answer" in names
    assert all(service.questions.get(q.id).status.value == "expired" for q in mission.questions)
    assert mission.status is MissionStatus.awaiting_human
    assert mission.steps[StepKind.registration].status is StepStatus.failed
    assert mission.steps[StepKind.transport].status is StepStatus.failed
    await events.aclose()


def test_question_answer_endpoint_validation_and_history(tmp_path):
    service = make_service(tmp_path, delay=0)
    service.question_timeout_s = 60
    with TestClient(create_app(service)) as client:
        _assert_question_answer_endpoint(client)


def _assert_question_answer_endpoint(client):
    created = api_confirm(client)
    assert created.status_code == 200
    mission_id = created.json()["mission_id"]
    payload = {"answer": "Not an option", "revision": created.json()["framing_revision"], "idempotency_key": "test-answer"}
    assert client.post(f"/api/missions/{mission_id}/questions/not-a-question/answer", json=payload).status_code == 409
    assert client.post("/api/missions/unknown/questions/q1/answer", json=payload).status_code == 404
    for _ in range(100):
        snapshot = client.get(f"/api/missions/{mission_id}").json()
        if snapshot["questions"]:
            break
        time.sleep(0.01)
    question = snapshot["questions"][0]
    url = f"/api/missions/{mission_id}/questions/{question['question_id']}/answer"
    assert client.post(url, json=payload).status_code == 409
    payload = payload | {"answer": question["choices"][0]}
    assert client.post(url, json=payload | {"answer": "x" * 501}).status_code == 422
    assert client.post(url, json=payload | {"answer": " "}).status_code == 422
    assert client.post(url, json=payload | {"revision": -1}).status_code == 409
    answered = client.post(url, json=payload)
    assert answered.status_code == 200
    assert answered.json()["questions"][0]["answer"] == question["choices"][0]
    assert client.post(url, json=payload).status_code == 200
    assert client.post(url, json=payload | {"answer": question["choices"][1]}).status_code == 409
    for _ in range(1000):
        snapshot = client.get(f"/api/missions/{mission_id}").json()
        for pending in snapshot["questions"]:
            if pending["status"] == "open":
                response = client.post(f"/api/missions/{mission_id}/questions/{pending['question_id']}/answer", json={
                    "answer": pending["choices"][0], "revision": pending["revision"],
                    "idempotency_key": f"answer-{pending['question_id']}",
                })
                assert response.status_code == 200
        if snapshot["status"] in {"awaiting_human", "failed"}:
            break
        time.sleep(0.01)
    assert snapshot["status"] == "awaiting_human"


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
    mission = await service.wait((await create_confirmed(service, "Milan")).id)

    registration = mission.steps[StepKind.registration]
    assert registration.status is StepStatus.stopped_before_commitment
    assert registration.stop_point is StopPoint.payment
    assert str(registration.live_view_url) == "https://live.example.org/registration"
    assert registration.data["headline"] == "Ready: finish it yourself on the official site"
    assert mission.steps[StepKind.accommodation].status is StepStatus.failed
    assert mission.steps[StepKind.accommodation].error == "H indisponible"
    assert mission.steps[StepKind.transport].data["headline"] == "Done"
    assert mission.steps[StepKind.transport].status is StepStatus.completed
    assert mission.status is MissionStatus.awaiting_human


@pytest.mark.anyio
async def test_step_failure_keeps_raw_error_and_publishes_friendly_copy(tmp_path):
    raw_error = "Traceback (most recent call last):\nAPI returned 403 Forbidden"
    agents = ScriptedAgents(
        {
            StepKind.registration: StepResult(
                kind=StepKind.registration,
                status=StepStatus.completed,
                summary="Inscription vérifiée",
            ),
            StepKind.accommodation: RuntimeError(raw_error),
            StepKind.transport: StepResult(
                kind=StepKind.transport,
                status=StepStatus.completed,
                summary="Horaires relevés",
            ),
        }
    )
    service = make_service(tmp_path, agents=agents)
    mission = await service.wait((await create_confirmed(service, "Milan")).id)
    step = mission.steps[StepKind.accommodation]
    user_error = "The agent service is currently unavailable."

    assert step.error == raw_error
    assert step.data["error_user"] == user_error
    assert step.data["headline"] == user_error
    limitation = next(item for item in mission.limitations if item.step == "accommodation")
    assert limitation.message == user_error
    failure = next(
        event for event in mission.events
        if event.type == "step_failed" and event.data.get("step") == "accommodation"
    )
    assert failure.message == f"{STEP_LABELS[StepKind.accommodation]}: {user_error}"
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
    mission = await service.wait((await create_confirmed(service, "Milan")).id)
    assert mission.status is MissionStatus.failed


@pytest.mark.anyio
async def test_trace_write_failure_does_not_strand_mission(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    mission = await create_confirmed(service, "Milan")

    def broken_write(self, event):
        raise OSError("disque plein")

    monkeypatch.setattr(TraceWriter, "write", broken_write)
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)
    assert mission.status is MissionStatus.awaiting_human


@pytest.mark.anyio
async def test_unconfirmed_creation_is_rejected(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(Exception, match="Confirmed framing"):
        await service.create("Milan")
    assert not service.missions


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
            **kwargs,
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
                kind, task, race, profile, on_event, ask_user, mission_id, query=query, **kwargs
            )

    service = make_service(tmp_path, agents=ThreadedAgents(delay=0))
    mission = await create_confirmed(service, "Milan")
    await answer_fake_questions(service, mission)
    mission = await service.wait(mission.id)
    assert sum(event.message == "depuis un thread" for event in mission.events) == 3


@pytest.mark.anyio
async def test_subscribe_receives_final_state(tmp_path):
    service = make_service(tmp_path, agents=FakeBrowserAgents(delay=0.01))
    mission = await create_confirmed(service, "Milan")
    answers = asyncio.create_task(answer_fake_questions(service, mission))
    messages = [message async for message in service.subscribe(mission.id)]
    await answers
    assert messages[0][0] == "snapshot"
    assert messages[-1][0] == "mission"
    assert messages[-1][1]["status"] == "awaiting_human"


@pytest.mark.anyio
@pytest.mark.parametrize("resume_sequence", [0, 1])
async def test_slow_event_consumer_drains_terminal_events_during_replay(tmp_path, resume_sequence):
    service = make_service(tmp_path)
    mission = Mission(id="slow-consumer", query="Test event replay", steps={}, status=MissionStatus.running)
    service.missions[mission.id] = mission
    for index in range(3):
        service._emit(mission, "trace", {"message": f"History event {index}"})
    cursor = f"{mission.id}:{resume_sequence}" if resume_sequence else None
    stream = service.subscribe_events(mission.id, cursor)
    first = await anext(stream)

    # The consumer pauses on history while the mission finishes and queues new events.
    mission.status = MissionStatus.completed
    service._emit(mission, "step", {"status": "completed"})
    service._emit(mission, "mission_status", {"status": "completed"})
    service._emit(mission, "trace", {"message": "Mission finished"})
    events = [first, *[event async for event in stream]]

    assert events == mission.envelopes[resume_sequence:]
    assert [event.sequence for event in events] == list(range(resume_sequence + 1, 7))
    assert any(event.type == "mission_status" for event in events)
    assert not service._event_subscribers[mission.id]


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
                    HumanAnswer(answer=question.options[0], revision=mission.plan.revision, idempotency_key=f"answer-{question.id}"),
                )
                handled.add(question.id)
        time.sleep(0.01)


def test_api_runs_a_demo_mission_with_sse(tmp_path):
    service = make_service(tmp_path, delay=0.01)
    app = create_app(service)
    with TestClient(app) as client:
        assert "RunAI" in client.get("/").text
        assert client.get("/api/health").json()["mode"] == "demo"

        created = api_confirm(client)
        assert created.status_code == 200
        mission_id = created.json()["mission_id"]
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
        assert names[0] == "journey_revised"
        assert "trace" in names
        final = [data["payload"] for name, data in events if name == "mission_status"][-1]
        assert final["status"] == "awaiting_human"

        mission = client.get(f"/api/missions/{mission_id}").json()
        session_id = mission["steps"][1]["h_session_id"]
        live = client.get(f"/api/live/{session_id}").json()
        assert live["label"] == STEP_LABELS[StepKind.accommodation]
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
        assert response.json() == {"text": FakeTranscriber.TEXT, "mode": "demo"}
        assert client.post("/api/transcribe", content=b"").status_code == 400
        oversized = b"0" * (MAX_AUDIO_BYTES + 1)
        assert client.post("/api/transcribe", content=oversized).status_code == 413


def test_basic_auth_protects_everything_but_health(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "equipe:secret")
    with TestClient(create_app(make_service(tmp_path, delay=0))) as client:
        assert client.get("/api/health").status_code == 200
        denied = client.get("/")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"].startswith("Basic")
        assert client.post("/api/framings", json={"text": "une course à Milan"}).status_code == 401
        assert client.get("/", auth=("equipe", "faux")).status_code == 401
        assert client.get("/", auth=("equipe", "secret")).status_code == 200
        assert client.get("/static/app.js", auth=("equipe", "secret")).status_code == 200


def test_basic_auth_rejects_malformed_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "sans-deux-points")
    with pytest.raises(ValueError), TestClient(create_app(make_service(tmp_path))) as client:
        client.get("/")


def test_public_live_mode_requires_a_password(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_PUBLIC", "1")
    monkeypatch.delenv("RUNAI_BASIC_AUTH", raising=False)
    live = make_service(tmp_path)
    live.simulated = False
    with pytest.raises(RuntimeError):
        create_app(live)
    create_app(make_service(tmp_path))
    monkeypatch.setenv("RUNAI_BASIC_AUTH", "equipe:secret")
    create_app(live)
