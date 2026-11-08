"""LLM-only framing through the real HoloPhraser on a mocked HTTP transport: no regex ever interprets the runner."""

import asyncio
import json
from datetime import date

import httpx

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import (
    FramingCreate,
    FramingReply,
    FramingStatus,
    RaceCandidate,
    SlotName,
)
from runai.framing.engine import FramingEngine
from runai.framing.holo import DECIDE_PROMPT, EXTRACT_PROMPT, HoloPhraser


class Search:
    async def find_candidates(self, slots, request_text=None):
        return [
            RaceCandidate(id="c1", name="Lisbon Half Marathon", city="Lisbon", country="PT",
                          race_date=date(2027, 3, 14), distances_km=[21.0975],
                          provenance=Provenance(kind="linkup", label="stub")),
            RaceCandidate(id="c2", name="Lisbon Night Run", city="Lisbon", country="PT",
                          race_date=date(2027, 3, 20), distances_km=[10.0],
                          provenance=Provenance(kind="linkup", label="stub")),
        ]


def upd(slot, value, evidence, replaces=False):
    return {"slot": slot, "value": value, "evidence": evidence, "replaces_previous": replaces}


def phraser(*decisions, payloads=None, fail=False):
    queue = list(decisions)

    def handler(request):
        body = json.loads(request.content)
        if payloads is not None:
            payloads.append(body)
        if fail:
            return httpx.Response(500)
        system = body["messages"][0]["content"]
        assert system != EXTRACT_PROMPT, "the old extraction prompt is no longer used to read the runner"
        if system != DECIDE_PROMPT:  # only the wording of the next question
            return httpx.Response(200, json={"choices": [{"message": {"content": "Which one?"}}]})
        content = json.dumps(queue.pop(0) if queue else {"intent": "unclear", "updates": [], "message": "Sorry?"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return HoloPhraser("hk-test", transport=httpx.MockTransport(handler))


FIRST = {"intent": "answer", "message": "Great.", "updates": [
    upd("city", "Lisbon", "Lisbon"), upd("distance_km", 21.0975, "semi"),
    upd("date_window", "March 2027", "March 2027"), upd("origin", "Paris", "Paris"),
    upd("nights", 2, "deux nuits"), upd("transport_mode", "train", "TGV"), upd("budget", None, "sans plafond"),
]}


def start(llm, text="Un semi a Lisbon en March 2027 depuis Paris, deux nuits en TGV, sans plafond"):
    engine = FramingEngine(Search(), DataMode.demo, llm)
    return engine, asyncio.run(engine.create(FramingCreate(text=text)))


def test_everything_in_one_sentence_comes_from_the_model():
    _engine, session = start(phraser(FIRST))
    assert session.slots[SlotName.nights].value == 2
    assert session.slots[SlotName.transport_mode].value == "train"
    assert session.slots[SlotName.budget].status.value == "not_needed"
    assert session.status == FramingStatus.choosing_candidate


def test_runner_picks_a_race_with_words():
    pick = {"intent": "answer", "updates": [], "choice": "c2", "message": "The night run, good choice."}
    engine, session = start(phraser(FIRST, pick))
    after = asyncio.run(engine.reply(session.id, FramingReply(revision=session.revision, text="the one on the 20th please")))
    assert after.selected_candidate_id == "c2"
    assert after.slots[SlotName.race].value == "Lisbon Night Run"
    assert after.status == FramingStatus.ready_to_confirm


def test_a_correction_typed_in_the_form_is_read_by_the_model():
    fix = {"intent": "correction", "message": "Three nights.", "updates": [upd("nights", 3, "trois nuits", True)]}
    engine, session = start(phraser(FIRST, {"intent": "answer", "updates": [], "choice": "c1", "message": "ok"}, fix))
    session = asyncio.run(engine.reply(session.id, FramingReply(revision=session.revision, text="the first one")))
    after = asyncio.run(engine.reply(session.id, FramingReply(
        revision=session.revision, text="trois nuits", corrections={SlotName.nights: "trois nuits"})))
    assert after.slots[SlotName.nights].value == 3


def test_address_is_masked_before_the_model_sees_it_and_only_the_city_is_kept():
    payloads = []
    answer = {"intent": "answer", "message": "Noted.", "updates": [upd("origin", "12 rue de la Paix, 75002 Paris", "Paris")]}
    partial = {"intent": "answer", "message": "Great.", "updates": [upd("city", "Lisbon", "Lisbon")]}
    engine, session = start(phraser(partial, answer, payloads=payloads), "Half marathon in Lisbon")
    question = next(q for q in session.open_questions if q.slots == [SlotName.origin])
    after = asyncio.run(engine.reply(session.id, FramingReply(
        revision=session.revision, text="12 rue de la Paix, 75002 Paris", question_id=question.id)))
    sent = json.dumps(payloads)
    assert "12 rue" not in sent and "75002" not in sent
    assert after.slots[SlotName.origin].value == "Paris"
    assert "12 rue" not in after.model_dump_json()


def test_model_outage_gives_a_clear_message_and_writes_nothing():
    _engine, session = start(phraser(fail=True), "Half marathon in Lisbon in March 2027")
    assert not session.slots[SlotName.city].is_known
    assert "could not process" in session.turns[-1].text.lower()


def test_the_model_chooses_the_next_question_in_the_runners_language_and_records_preferences():
    first = {"intent": "answer", "language": "fr", "message": "Un premier semi, super.",
             "updates": [upd("city", "Lisbonne", "Lisbonne"), upd("distance_km", 21.0975, "semi"),
                         upd("preferences", "first half marathon, flat and scenic course", "parcours plat")],
             "ask_slot": "date_window", "next_question": "Tu es flexible sur la date, ou c'est un week-end précis ?"}
    _engine, session = start(phraser(first), "Mon premier semi à Lisbonne, parcours plat si possible")
    assert session.slots[SlotName.preferences].value == "first half marathon, flat and scenic course"
    assert session.open_questions[0].slots == [SlotName.date_window]
    assert session.turns[-1].text.endswith("Tu es flexible sur la date, ou c'est un week-end précis ?")
    assert "Select the race" not in session.turns[-1].text
