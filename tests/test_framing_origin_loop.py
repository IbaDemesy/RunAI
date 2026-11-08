"""An origin given only as a street address must not make the same question loop forever."""

import asyncio
from datetime import date

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import FramingCreate, FramingReply, RaceCandidate, SlotName
from runai.framing.engine import FramingEngine
from runai.framing.holo import TemplatePhraser


class Search:
    async def find_candidates(self, slots, request_text=None):
        return [RaceCandidate(
            id="c1", name="Lisbon Half Marathon", city="Lisbon", country="PT",
            race_date=date(2027, 3, 14), distances_km=[21.0975],
            provenance=Provenance(kind="linkup", label="stub"),
        )]


def origin_question(session):
    return next(q for q in session.open_questions if q.slots == [SlotName.origin])


def test_street_only_origin_asks_for_a_city_twice_then_moves_on():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo, TemplatePhraser())
        session = await engine.create(FramingCreate(text="Half marathon in Lisbon on 2027-03-14"))
        assert not session.slots[SlotName.origin].is_known
        for attempt in (1, 2):
            session = await engine.reply(session.id, FramingReply(
                revision=session.revision, text="12 rue de la Paix", question_id=origin_question(session).id))
            assert "city" in session.turns[-1].text.lower(), attempt
            assert not session.slots[SlotName.origin].is_known
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, text="12 rue de la Paix", question_id=origin_question(session).id))
        assert session.slots[SlotName.origin].is_known, "third attempt must not loop"
        assert "rue" not in str(session.slots[SlotName.origin].value)

    asyncio.run(run())


def test_a_real_city_after_a_miss_resets_the_counter():
    async def run():
        engine = FramingEngine(Search(), DataMode.demo, TemplatePhraser())
        session = await engine.create(FramingCreate(text="Half marathon in Lisbon on 2027-03-14"))
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, text="12 rue de la Paix", question_id=origin_question(session).id))
        session = await engine.reply(session.id, FramingReply(
            revision=session.revision, text="Paris 15", question_id=origin_question(session).id))
        assert session.slots[SlotName.origin].value == "Paris 15"

    asyncio.run(run())
