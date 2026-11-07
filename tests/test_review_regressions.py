import asyncio
from datetime import date

import pytest

from runai.contracts.common import DataMode
from runai.contracts.framing import (
    FramingCreate,
    FramingReply,
    FramingStatus,
    RaceCandidate,
    SlotName,
)
from runai.framing.engine import FramingEngine
from runai.framing.launch import plan_launch


class Search:
    async def find_candidates(self, slots):
        return [RaceCandidate(id="race", name="Course de Rome", city="Rome", country="IT",
                              race_date=date(2028, 6, 12), distances_km=[10],
                              registration_url="https://in.njuko.com/race", provenance={"kind": "fixture"})]


@pytest.mark.parametrize("origin,public", [
    ("12 rue des Lilas, 75011 Paris", "Paris"),
    ("12 rue d'\"Austerlitz\", 75011 Paris", "Paris"),
    ("12 rue des Lilas", None),
    ("Paris 11e", "Paris 11e"),
])
def test_origin_is_public_before_storage_exposure_and_agent_task(origin, public):
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(FramingCreate(text="course à Rome depuis Lyon, 800 euros, 2 nuits, en train"))
        session = await engine.reply(session.id, FramingReply(revision=session.revision, choice_id="race"))
        session = await engine.reply(session.id, FramingReply(revision=session.revision, corrections={"origin": origin}))
        assert session.slots[SlotName.origin].value == public
        assert "12 rue" not in engine.get(session.id).model_dump_json()
        if public is None:
            assert session.summary is None
            assert any(SlotName.origin in q.slots for q in session.open_questions)
        else:
            assert session.summary.origin_public == public
            session.status = FramingStatus.confirmed
            session.confirmed_revision = session.revision
            session.summary.origin_public = "12 rue des Lilas, 75011 Paris"
            plan = plan_launch(session)
            assert plan.brief.origin == "Paris"
            assert "12 rue des Lilas" not in " ".join(s.task or "" for s in plan.steps.values())
    asyncio.run(run())


def test_dated_candidate_button_label_is_not_a_date_correction():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo)
        session = await engine.create(FramingCreate(text="course à Rome depuis Lyon, 800 euros, 2 nuits, en train"))
        question = session.open_questions[0]
        choice = question.choices[0]
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, question_id=question.id, choice_id=choice.id,
            text=choice.label, channel="buttons"))
        assert session.selected_candidate_id == "race"
        assert session.summary.race.race_date == date(2028, 6, 12)
        assert session.status == FramingStatus.ready_to_confirm
    asyncio.run(run())


@pytest.mark.parametrize("city", ["", "   "])
def test_candidate_without_city_keeps_city_unknown_and_requests_it(city):
    class MissingCitySearch(Search):
        async def find_candidates(self, slots):
            candidates = await super().find_candidates(slots)
            candidates[0].city = city
            return candidates

    async def run():
        engine = FramingEngine(MissingCitySearch(), DataMode.demo)
        session = await engine.create(FramingCreate(text="une course depuis Lyon, 800 euros, 2 nuits, en train"))
        session = await engine.reply(session.id, FramingReply(revision=session.revision, corrections={"race": "Épreuve officielle"}))
        session = await engine.reply(session.id, FramingReply(revision=session.revision, choice_id="race"))
        assert not session.slots[SlotName.city].is_known
        assert session.summary is None
        question = next(q for q in session.open_questions if SlotName.city in q.slots)
        session = await engine.reply(session.id, FramingReply(revision=session.revision, question_id=question.id, text="Rome"))
        session = await engine.reply(session.id, FramingReply(revision=session.revision, choice_id="race"))
        assert session.summary.race.city == "Rome"
        session.status = FramingStatus.confirmed
        session.confirmed_revision = session.revision
        assert plan_launch(session).brief.city == "Rome"
    asyncio.run(run())
