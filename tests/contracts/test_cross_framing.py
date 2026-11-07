import asyncio
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import (
    FramingConfirm,
    FramingCreate,
    FramingError,
    FramingReply,
    FramingStatus,
    RaceCandidate,
    SlotName,
)
from runai.contracts.mission import HumanAnswer, MissionSnapshot, QuestionStatus
from runai.framing.api import build_framing_router
from runai.framing.engine import FramingEngine
from runai.h.human_questions import HumanQuestionError, HumanQuestionRegistry
from runai.models import AgentQuestion, Source, StepKind, utcnow


class Discovery:
    def __init__(self, count=2):
        self.count = count
        self.cities = []

    async def find_candidates(self, slots, request_text: str | None = None):
        city = slots[SlotName.city].value
        self.cities.append(city)
        return [
            RaceCandidate(
                id=f"event-{i}",
                name=f"Course {city} {i}",
                city=city,
                country="",
                race_date=date(2028, 6, 12),
                distances_km=[10],
                sources=[Source(url="https://example.org/race")],
                provenance=Provenance(kind="fixture"),
            )
            for i in range(self.count)
        ]


def snapshot(session):
    return MissionSnapshot(
        mission_id=f"mission-{session.id}",
        framing_id=session.id,
        framing_revision=session.revision,
        mode=session.mode,
        status="running",
        sequence=0,
        steps=[],
    )


async def prepared(engine, channel="text"):
    session = await engine.create(
        FramingCreate(
            text="une course à Tokyo depuis Lyon, 800 euros, 2 nuits, en avion",
            channel=channel,
        )
    )
    assert session.summary is None
    return await engine.reply(
        session.id,
        FramingReply(
            revision=session.revision,
            choice_id="event-0",
            channel=channel,
        ),
    )


@pytest.mark.parametrize(
    "city",
    [
        "Lisbonne",
        "Berlin",
        "Milan",
        "Tokyo",
        "Nairobi",
        "Chicago",
        "Sydney",
        "Kigali",
        "Ushuaïa",
    ],
)
def test_discovery_accepts_unlisted_cities_without_guessing(city):
    async def run():
        search = Discovery()
        engine = FramingEngine(search, DataMode.demo)
        session = await engine.create(FramingCreate(text=f"une course à {city}"))
        assert search.cities == [city]
        assert session.status == FramingStatus.choosing_candidate
        assert {k: s.value for k, s in session.slots.items() if s.is_known} == {
            SlotName.city: city
        }
        assert session.summary is None and session.selected_candidate_id is None
        session = await engine.reply(
            session.id, FramingReply(revision=1, choice_id="event-1")
        )
        assert session.selected_candidate_id == "event-1"
        asked = {s for q in session.open_questions for s in q.slots}
        assert {
            SlotName.origin,
            SlotName.nights,
            SlotName.budget,
            SlotName.transport_mode,
        } <= asked
        assert (
            not {SlotName.city, SlotName.race, SlotName.race_date, SlotName.distance_km}
            & asked
        )
        session = await engine.reply(
            session.id, FramingReply(revision=2, corrections={SlotName.origin: "Lyon"})
        )
        assert SlotName.origin not in {
            s for q in session.open_questions for s in q.slots
        }

    asyncio.run(run())


def test_empty_discovery_asks_date_distance_and_origin():
    async def run():
        session = await FramingEngine(Discovery(0)).create(
            FramingCreate(text="une course à Lisbonne")
        )
        assert {SlotName.race_date, SlotName.distance_km, SlotName.origin} <= {
            s for q in session.open_questions for s in q.slots
        }
        assert session.slots[SlotName.origin].value is None

    asyncio.run(run())


@pytest.mark.parametrize("channel", ["text", "voice"])
def test_city_correction_invalidates_old_summary_and_candidate_question(channel):
    async def run():
        search = Discovery()
        engine = FramingEngine(search, DataMode.demo)
        initial = await engine.create(
            FramingCreate(
                text="une course à Tokyo depuis Lyon, 800 euros, 2 nuits, en avion",
                channel=channel,
            )
        )
        old_question = next(q for q in initial.open_questions if q.choices)
        ready = await engine.reply(
            initial.id,
            FramingReply(revision=initial.revision, choice_id="event-0", channel=channel),
        )
        assert ready.status is FramingStatus.ready_to_confirm
        corrected = await engine.reply(
            ready.id,
            FramingReply(
                revision=ready.revision,
                text="finalement une course à Nairobi",
                channel=channel,
            ),
        )
        assert search.cities == ["Tokyo", "Nairobi"]
        assert corrected.status is FramingStatus.choosing_candidate
        assert corrected.summary is None and corrected.selected_candidate_id is None
        assert all(c.city == "Nairobi" for c in corrected.candidates)
        for name in (SlotName.origin, SlotName.budget, SlotName.nights, SlotName.transport_mode):
            assert corrected.slots[name] == ready.slots[name]
        for name in (SlotName.race, SlotName.race_date, SlotName.distance_km):
            assert not corrected.slots[name].is_known
        with pytest.raises(FramingError, match="Question périmée"):
            await engine.reply(
                ready.id,
                FramingReply(
                    revision=corrected.revision,
                    question_id=old_question.id,
                    choice_id="event-0",
                    channel=channel,
                ),
            )
        launches = []

        async def launch(session):
            launches.append(session)
            return snapshot(session)

        for revision in (ready.revision, corrected.revision):
            with pytest.raises(FramingError):
                await engine.confirm(
                    ready.id,
                    FramingConfirm(revision=revision, idempotency_key="correct-city"),
                    launch,
                )
        assert not launches
        current = await engine.reply(
            ready.id,
            FramingReply(
                revision=corrected.revision, choice_id="event-1", channel=channel
            ),
        )
        assert current.summary.race.city == "Nairobi"
        assert current.summary.origin_public == "Lyon"
        assert current.summary.budget_eur == 800 and current.summary.nights == 2
        assert not launches
        await engine.confirm(
            current.id,
            FramingConfirm(revision=current.revision, idempotency_key="correct-city"),
            launch,
        )
        assert len(launches) == 1
        assert launches[0].status is FramingStatus.confirmed
        assert launches[0].confirmed_revision == current.revision
        assert launches[0].summary == current.summary

    asyncio.run(run())


def test_revision_concurrent_confirmation_cancellation_and_channel_parity():
    async def run():
        states = []
        for channel in ("text", "voice"):
            engine = FramingEngine(Discovery(), DataMode.demo)
            session = await prepared(engine, channel)
            old = session.summary
            session = await engine.reply(
                session.id,
                FramingReply(
                    revision=session.revision,
                    corrections={SlotName.budget: 950},
                    channel=channel,
                ),
            )
            assert session.revision == old.revision + 1
            assert session.summary != old and session.summary.budget_eur == 950
            calls = []

            async def launch(s, calls=calls):
                calls.append(s)
                await asyncio.sleep(0)
                return snapshot(s)

            with pytest.raises(FramingError):
                await engine.confirm(
                    session.id,
                    FramingConfirm(revision=old.revision, idempotency_key="same-key"),
                    launch,
                )
            request = FramingConfirm(
                revision=session.revision, idempotency_key="same-key"
            )
            results = await asyncio.gather(
                *(engine.confirm(session.id, request, launch) for _ in range(8))
            )
            assert all(m == results[0] for m in results) and len(calls) == 1
            with pytest.raises(FramingError):
                await engine.confirm(
                    session.id,
                    request.model_copy(update={"idempotency_key": "other-key"}),
                    launch,
                )
            cancelled = await prepared(engine, channel)
            await engine.cancel(cancelled.id)
            with pytest.raises(FramingError):
                await engine.confirm(
                    cancelled.id,
                    FramingConfirm(
                        revision=cancelled.revision, idempotency_key="cancel-key"
                    ),
                    launch,
                )
            with pytest.raises(FramingError):
                await engine.reply(
                    cancelled.id,
                    FramingReply(revision=cancelled.revision, text="budget 900 euros"),
                )
            assert len(calls) == 1
            states.append(
                (
                    {k: s.value for k, s in session.slots.items()},
                    session.status,
                    session.summary.lines,
                )
            )
        assert states[0] == states[1]

    asyncio.run(run())


def test_api_launch_is_explicit_and_conflicts_are_http_409():
    calls = []

    async def launch(session):
        calls.append(session)
        return snapshot(session)

    app = FastAPI()
    app.include_router(build_framing_router(FramingEngine(Discovery()), launch))
    with TestClient(app) as client:
        assert client.get("/api/framings/missing").status_code == 404
        response = client.post(
            "/api/framings",
            json={
                "text": "une course à Tokyo depuis Lyon, 800 euros, 2 nuits, en avion"
            },
        )
        assert response.status_code == 201
        base = f"/api/framings/{response.json()['id']}"
        assert (
            client.post(
                base + "/confirm", json={"revision": 1, "idempotency_key": "api-key-1"}
            ).status_code
            == 409
        )
        ready = client.post(
            base + "/replies", json={"revision": 1, "choice_id": "event-0"}
        )
        assert ready.status_code == 200 and not calls
        assert (
            client.post(
                base + "/replies", json={"revision": 1, "text": "budget 900 euros"}
            ).status_code
            == 409
        )
        payload = {"revision": ready.json()["revision"], "idempotency_key": "api-key-1"}
        first = client.post(base + "/confirm", json=payload)
        assert first.status_code == 200
        assert client.post(base + "/confirm", json=payload).json() == first.json()
        assert len(calls) == 1
        for endpoint in ("replies", "confirm", "cancel"):
            assert (
                client.post(
                    f"/api/framings/missing/{endpoint}",
                    json=payload
                    if endpoint != "replies"
                    else {"revision": 1, "text": "Tokyo"},
                ).status_code
                == 404
            )


def registry_question(text="Quelle option ?", **kwargs):
    registry = HumanQuestionRegistry()
    registry.open(
        AgentQuestion(id="cross-q", kind=StepKind.registration, question=text),
        "mission",
        4,
        **kwargs,
    )
    return registry


@pytest.mark.parametrize("case", ["revision", "expired", "duplicate", "cancelled"])
def test_obsolete_human_answers_are_rejected(case):
    registry = (
        registry_question(expires_at=utcnow() - timedelta(seconds=1))
        if case == "expired"
        else registry_question()
    )
    answer = HumanAnswer(answer="oui", revision=4, idempotency_key="first-key")
    if case == "revision":
        answer = answer.model_copy(update={"revision": 3})
    elif case == "duplicate":
        registry.answer("cross-q", "mission", answer)
        answer = answer.model_copy(update={"idempotency_key": "second-key"})
    elif case == "cancelled":
        registry.cancel_mission("mission")
    with pytest.raises(HumanQuestionError):
        registry.answer("cross-q", "mission", answer)


@pytest.mark.parametrize(
    "text",
    [
        "Effectuer le paiement ?",
        "Créer un compte ?",
        "Déclaration de santé ?",
        "Accepter le consentement ?",
        "Soumettre le formulaire ?",
    ],
)
def test_yes_keeps_human_safety_barrier(text):
    registry = registry_question(text)
    result = registry.answer(
        "cross-q",
        "mission",
        HumanAnswer(answer="oui", revision=4, idempotency_key="safety-key"),
    )
    assert result.status == QuestionStatus.refused
    assert registry.to_agent_question("cross-q").answer is None
    with pytest.raises(HumanQuestionError):
        asyncio.run(registry.wait_answer("cross-q", timeout=1))
