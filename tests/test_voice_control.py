import asyncio

import pytest
from fastapi.testclient import TestClient

from runai.app.candidates import FixtureCandidateSearch
from runai.app.fakes import (
    DEMO_RACES,
    QUESTIONS,
    FakeBrowserAgents,
    FakeRaceSearch,
    FakeTranscriber,
)
from runai.app.mission import AGENT_STEPS, MissionService
from runai.app.server import create_app
from runai.app.voice_control import CANCEL_PROMPT, PAUSED_PROMPT, VoiceMissionController
from runai.contracts.common import DataMode
from runai.contracts.framing import FramingConfirm, FramingCreate, FramingReply
from runai.contracts.mission import HumanAnswer
from runai.framing.engine import FramingEngine
from runai.models import StepKind, StepStatus
from runai.voice.models import TranscriptEvent


def make_service(tmp_path, delay=0.05):
    return MissionService(
        FakeRaceSearch(delay=0), FakeBrowserAgents(delay=delay), FakeTranscriber(delay=0),
        traces_dir=tmp_path, simulated=True,
    )


async def running_mission(service):
    engine = FramingEngine(FixtureCandidateSearch([DEMO_RACES["milan"]], DataMode.demo), DataMode.demo)
    session = await engine.create(FramingCreate(
        text="une course à Milan, 42.195 km en avril 2027, depuis Lyon, 900 euros, 2 nuits, train"
    ))
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, choice_id=session.candidates[0].id,
    ))
    session = await engine.reply(session.id, FramingReply(revision=session.revision, corrections={
        "origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "train",
    }))
    snapshot = await engine.confirm(
        session.id, FramingConfirm(revision=session.revision, idempotency_key="voice-confirm"), service.confirm,
    )
    mission = service.get(snapshot.mission_id)
    for _ in range(2000):
        for question in list(mission.questions):
            wrapped = service.questions.get(question.id)
            if wrapped.status.value == "open":
                service.answer_question(mission.id, question.id, HumanAnswer(
                    answer=question.options[0], revision=wrapped.revision,
                    idempotency_key=f"answer-{question.id}",
                ))
        if len(mission.questions) >= sum(map(len, QUESTIONS.values())) and all(q.answer is not None for q in mission.questions) and all(
            mission.steps[kind].status is StepStatus.running for kind in AGENT_STEPS
        ):
            return mission
        await asyncio.sleep(0.001)
    pytest.fail("Agents never all running")


def said(text, utterance_id, *, final=True):
    return TranscriptEvent(text=text, is_final=final, utterance_id=utterance_id, language="en")


def statuses(mission):
    return {kind: mission.steps[kind].status for kind in AGENT_STEPS}


def voice_events(mission, type_):
    return [event for event in mission.events if event.source == "voice" and event.type == type_]


@pytest.mark.anyio
async def test_partial_stop_pauses_once_then_explicit_resume(tmp_path):
    service = make_service(tmp_path)
    controller = VoiceMissionController(service)
    mission = await running_mission(service)

    result = await controller.handle(mission.id, said("Stop", "u1", final=False))
    assert result.applied == ["pause"]
    assert result.events[0].early
    assert set(statuses(mission).values()) == {StepStatus.paused}
    (requested,) = voice_events(mission, "voice.pause_requested")
    (confirmed,) = voice_events(mission, "voice.pause_confirmed")
    assert requested.data["steps"] == confirmed.data["steps"] == [kind.value for kind in AGENT_STEPS]
    assert mission.events.index(requested) < mission.events.index(confirmed)

    again = await controller.handle(mission.id, said("Stop wait", "u1", final=False))
    assert again.applied == [] and again.events == []
    assert len(voice_events(mission, "voice.pause_requested")) == 1

    final = await controller.handle(mission.id, said("Stop, let me think", "u1"))
    assert final.applied == []
    assert final.pending_confirmation == PAUSED_PROMPT
    assert set(statuses(mission).values()) == {StepStatus.paused}

    resumed = await controller.handle(mission.id, said("Resume", "u2"))
    assert resumed.applied == ["resume"] and resumed.pending_confirmation is None
    assert set(statuses(mission).values()) == {StepStatus.running}
    assert len(voice_events(mission, "voice.resume")) == 1

    duplicate = await controller.handle(mission.id, said("Resume", "u2"))
    assert duplicate.applied == [] and duplicate.ignored_reason
    await service.cancel(mission.id)


@pytest.mark.anyio
async def test_correction_reaches_only_the_matching_agent(tmp_path):
    service = make_service(tmp_path)
    controller = VoiceMissionController(service)
    mission = await running_mission(service)

    result = await controller.handle(mission.id, said("Actually a hotel closer to the start", "u1"))
    assert result.applied == ["correction:accommodation"]
    runs = {run.kind: run for run in service.agents.runs}
    assert len(runs[StepKind.accommodation].received) == 1
    assert runs[StepKind.accommodation].received[0].startswith("Actually a hotel closer to the start")
    assert runs[StepKind.registration].received == runs[StepKind.transport].received == []
    assert mission.steps[StepKind.accommodation].data["messages"] == ["Actually a hotel closer to the start"]

    budget = await controller.handle(mission.id, said("Actually change the budget", "u2"))
    assert budget.applied == [] and "Framing is closed" in budget.ignored_reason

    other = await controller.handle(mission.id, said("I'd like to run the Milan marathon", "u3"))
    assert other.applied == [] and other.ignored_reason
    await service.cancel(mission.id)


@pytest.mark.anyio
async def test_cancel_and_negated_stop_change_nothing(tmp_path):
    service = make_service(tmp_path)
    controller = VoiceMissionController(service)
    mission = await running_mission(service)
    before = statuses(mission)

    cancel = await controller.handle(mission.id, said("Cancel everything", "u1"))
    assert cancel.applied == [] and cancel.pending_confirmation == CANCEL_PROMPT
    assert mission.status.value == "running" and statuses(mission) == before

    for final in (False, True):
        negated = await controller.handle(mission.id, said("don't stop", "u2", final=final))
        assert negated.applied == [] and negated.events == []
    assert statuses(mission) == before
    assert not [event for event in mission.events if event.source == "voice"]
    await service.cancel(mission.id)


def test_voice_endpoint_unknown_mission_is_404(tmp_path):
    with TestClient(create_app(make_service(tmp_path))) as client:
        response = client.post("/api/missions/nope/voice", json={
            "text": "Stop", "is_final": False, "utterance_id": "u1",
        })
        assert response.status_code == 404
        invalid = client.post("/api/missions/nope/voice", json={"text": "", "is_final": True})
        assert invalid.status_code == 422


@pytest.mark.anyio
async def test_stop_while_an_agent_is_starting_is_retried_on_the_final(tmp_path):
    service = make_service(tmp_path)
    controller = VoiceMissionController(service)
    mission = await running_mission(service)
    starting = service._runs.pop((mission.id, StepKind.transport))

    early = await controller.handle(mission.id, said("Stop", "u1", final=False))
    assert early.applied == ["pause"] and "transport" in early.ignored_reason
    assert mission.steps[StepKind.transport].status is StepStatus.running
    assert mission.steps[StepKind.registration].status is StepStatus.paused

    service._runs[(mission.id, StepKind.transport)] = starting
    final = await controller.handle(mission.id, said("Stop please", "u1"))
    assert final.applied == ["pause"] and final.ignored_reason is None
    assert set(statuses(mission).values()) == {StepStatus.paused}
    assert final.pending_confirmation == PAUSED_PROMPT
    await service.cancel(mission.id)
