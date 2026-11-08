"""Framing conversations survive a restart, expire after 24 h, and stale candidate notes do not follow the user."""

import asyncio
import os
import time
from datetime import date

from runai.contracts.common import DataMode, Limitation, Provenance
from runai.contracts.framing import (
    FramingCreate,
    FramingReply,
    FramingSession,
    RaceCandidate,
    SlotName,
)
from runai.framing.engine import FramingEngine
from runai.framing.holo import TemplatePhraser
from runai.framing.store import FramingStore


class Search:
    async def find_candidates(self, slots, request_text=None):
        return []


def make(tmp_path, **kwargs):
    return FramingEngine(Search(), DataMode.demo, TemplatePhraser(), store=FramingStore(tmp_path, **kwargs))


def test_conversation_survives_a_restart_and_can_continue(tmp_path):
    async def run():
        first = make(tmp_path)
        session = await first.create(FramingCreate(text="Half marathon in Lisbon on 2027-03-14"))
        restarted = make(tmp_path)  # new process, same folder
        restored = restarted.get(session.id)
        assert restored.slots[SlotName.city].value == "Lisbon"
        assert [t.text for t in restored.turns] == [t.text for t in session.turns]
        question = next(q for q in restored.open_questions if q.slots == [SlotName.origin])
        after = await restarted.reply(session.id, FramingReply(
            revision=restored.revision, text="Paris", question_id=question.id))
        assert after.slots[SlotName.origin].value == "Paris"

    asyncio.run(run())


def test_expired_and_foreign_files_are_dropped(tmp_path):
    store = FramingStore(tmp_path, retention_s=60)
    session = FramingSession(id="a" * 32, mode=DataMode.demo)
    store.save(session)
    old = tmp_path / f"{'b' * 32}.json"
    old.write_text(session.model_copy(update={"id": "b" * 32}).model_dump_json(), encoding="utf-8")
    past = time.time() - 3600
    os.utime(old, (past, past))
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    loaded = store.load()
    assert [s.id for s in loaded] == ["a" * 32]
    assert not old.exists()


def test_corrupt_file_is_skipped(tmp_path):
    (tmp_path / f"{'c' * 32}.json").write_text("{not json", encoding="utf-8")
    assert FramingStore(tmp_path).load() == []


def test_candidate_limitations_do_not_follow_to_the_next_candidate(tmp_path):
    note = Limitation(code="registration_url_unverified", message="Unofficial link for Lisbon")
    candidate = RaceCandidate(
        id="c1", name="Lisbon Half", city="Lisbon", country="PT", race_date=date(2027, 3, 14),
        distances_km=[21.0975], provenance=Provenance(kind="linkup", label="stub"), limitations=[note],
    )
    own = Limitation(code="manual_event", message="Entered by the user")
    session = FramingSession(id="d" * 32, mode=DataMode.demo, candidates=[candidate], limitations=[note, own])
    FramingEngine._drop_candidate_limitations(session)
    assert session.limitations == [own]
