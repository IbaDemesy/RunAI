"""LLM-first framing: the model proposes slot updates, the engine validates each of them offline."""

import asyncio
from datetime import date

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import (
    FramingCreate,
    FramingReply,
    RaceCandidate,
    SlotName,
)
from runai.framing.engine import FramingEngine, _sanitize_ack
from runai.framing.holo import TemplatePhraser


class Search:
    async def find_candidates(self, slots, request_text=None):
        return [RaceCandidate(
            id="c1", name="Lisbon Half Marathon", city="Lisbon", country="PT",
            race_date=date(2027, 3, 14), distances_km=[21.0975],
            provenance=Provenance(kind="linkup", label="stub"),
        )]


class ScriptedLLM(TemplatePhraser):
    """Fake model: pops one scripted decision per call and records what it was sent."""

    def __init__(self, *decisions):
        self.decisions = list(decisions)
        self.calls = []

    async def decide(self, text, known, turns=(), pending=""):
        self.calls.append({"text": text, "known": dict(known), "pending": pending})
        return self.decisions.pop(0) if self.decisions else None


def run(coro):
    return asyncio.run(coro)


def engine(*decisions):
    llm = ScriptedLLM(*decisions)
    return FramingEngine(Search(), DataMode.demo, llm), llm


def update(slot, value, evidence, replaces=False):
    return {"slot": slot, "value": value, "evidence": evidence, "replaces_previous": replaces}


def start(eng, text="I want a half marathon in Lisbon in March 2027"):
    return run(eng.create(FramingCreate(text=text)))


def pending(session, slot):
    return next(q for q in session.open_questions if slot in q.slots)


def test_correction_changes_city_not_the_pending_origin():
    eng, _ = engine(
        {"intent": "answer", "updates": [update("city", "Lisbon", "Lisbon"), update("distance_km", 21.0975, "half marathon")],
         "message": "Got it."},
        {"intent": "correction", "updates": [update("city", "Porto", "plutôt Porto", replaces=True)],
         "message": "Switching to Porto."},
    )
    session = start(eng)
    question = pending(session, SlotName.origin)
    session = run(eng.reply(session.id, FramingReply(
        revision=session.revision, text="en fait plutôt Porto", question_id=question.id)))
    assert session.slots[SlotName.city].value == "Porto"
    assert not session.slots[SlotName.origin].is_known


def test_invented_evidence_is_rejected():
    eng, _ = engine(
        {"intent": "answer", "updates": [update("budget", 5000, "five thousand euros")], "message": "Noted."},
    )
    session = start(eng, "I would like a half marathon in Lisbon")
    assert not session.slots[SlotName.budget].is_known


def test_number_words_come_from_the_model_and_are_validated():
    eng, _ = engine(
        {"intent": "answer", "updates": [update("city", "Lisbon", "Lisbon")], "message": "Great."},
        {"intent": "answer", "updates": [update("nights", 2, "deux nuits")], "message": "Two nights."},
        {"intent": "answer", "updates": [update("nights", 999, "deux nuits")], "message": ""},
    )
    session = start(eng)
    question = pending(session, SlotName.nights)
    session = run(eng.reply(session.id, FramingReply(
        revision=session.revision, text="deux nuits", question_id=question.id)))
    assert session.slots[SlotName.nights].value == 2


def test_out_of_range_values_never_reach_the_slots():
    eng, _ = engine(
        {"intent": "answer", "updates": [update("nights", 999, "999 nuits")], "message": "Hmm."},
    )
    session = start(eng, "999 nuits à Lisbonne")
    assert not session.slots[SlotName.nights].is_known


def test_non_answer_keeps_the_question_and_writes_nothing():
    eng, _ = engine(
        {"intent": "answer", "updates": [update("city", "Lisbon", "Lisbon")], "message": "Great."},
        {"intent": "unclear", "updates": [], "message": "No problem, take your time."},
    )
    session = start(eng)
    question = pending(session, SlotName.origin)
    after = run(eng.reply(session.id, FramingReply(
        revision=session.revision, text="je sais pas encore", question_id=question.id)))
    assert not after.slots[SlotName.origin].is_known
    assert any(q.slots == [SlotName.origin] for q in after.open_questions)
    assert after.turns[-1].role == "assistant"
    assert "take your time" in after.turns[-1].text


def test_advice_message_is_followed_by_the_pending_question():
    eng, _ = engine(
        {"intent": "answer", "updates": [update("city", "Lisbon", "Lisbon")], "message": "Great."},
        {"intent": "advice", "updates": [],
         "message": "I would suggest arriving the day before. Which hotel? See https://evil.example"},
    )
    session = start(eng)
    question = pending(session, SlotName.nights)
    after = run(eng.reply(session.id, FramingReply(
        revision=session.revision, text="how many nights do you advise?", question_id=question.id)))
    last = after.turns[-1].text
    assert "arriving the day before" in last
    assert "evil.example" not in last
    assert last.count("?") == 1 and last.endswith("?")


def test_origin_address_is_masked_before_the_model_and_in_the_slot():
    eng, llm = engine(
        {"intent": "answer", "updates": [update("city", "Lisbon", "Lisbon")], "message": "Great."},
        {"intent": "answer", "updates": [update("origin", "12 rue de la Paix, 75002 Paris", "Paris")],
         "message": "Noted."},
    )
    session = start(eng)
    question = pending(session, SlotName.origin)
    after = run(eng.reply(session.id, FramingReply(
        revision=session.revision, text="12 rue de la Paix, 75002 Paris", question_id=question.id)))
    assert "12 rue" not in llm.calls[-1]["text"]
    assert after.slots[SlotName.origin].value == "Paris"


def test_model_failure_falls_back_to_the_deterministic_path():
    eng, llm = engine(None, None)
    session = start(eng, "A half marathon in Lisbon in March 2027")
    assert llm.calls, "the model was tried first"
    assert session.slots[SlotName.city].is_known  # heuristics still understood the request


def test_flag_disables_the_model(monkeypatch):
    monkeypatch.setenv("RUNAI_FRAMING_LLM", "0")
    eng, llm = engine({"intent": "answer", "updates": [], "message": ""})
    start(eng)
    assert llm.calls == []


def test_sanitize_ack_strips_links_questions_and_length():
    assert _sanitize_ack("Nice. Where from? Visit http://x.y now.", allow_question=False) == "Nice. Visit now."
    assert _sanitize_ack(None, allow_question=False) == ""
    assert len(_sanitize_ack("word " * 200, allow_question=False)) <= 322
