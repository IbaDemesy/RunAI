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
        assert "12 rue des Lilas" not in engine.get(session.id).model_dump_json()
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
