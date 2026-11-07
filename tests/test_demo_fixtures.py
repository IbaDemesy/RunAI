import re
from pathlib import Path

import pytest

from runai.app.candidates import FixtureCandidateSearch
from runai.app.fakes import (
    DEMO_RACES,
    _LISBON_WORDS,
    FakeBrowserAgents,
    FakeRaceSearch,
    FakeTranscriber,
)
from runai.contracts.common import DataMode
from runai.contracts.framing import (
    FramingCreate,
    FramingReply,
    FramingStatus,
    Slot,
    SlotName,
    SlotStatus,
)
from runai.framing.engine import FramingEngine
from runai.models import RunnerProfile, StepKind


def search():
    return FixtureCandidateSearch(list(DEMO_RACES.values()), DataMode.demo)


def slots(**values):
    return {SlotName(key): Slot(name=key, value=value, status=SlotStatus.answered)
            for key, value in values.items()}


def idea_chips():
    source = Path("runai/app/static/app.js").read_text()
    return re.findall(r'"([^"]+)"', re.search(r"const IDEAS = \[(.*?)\]", source)[1])


@pytest.mark.anyio
@pytest.mark.parametrize("alias", _LISBON_WORDS)
@pytest.mark.parametrize("slot_name", ["city", "race"])
async def test_lisbon_aliases_match_only_lisbon_without_fallback(alias, slot_name):
    result = await search().search(slots(**{slot_name: alias, "distance_km": 10}))
    assert [candidate.city for candidate in result.candidates] == ["Lisbon"]
    assert not result.limitations
    assert not result.candidates[0].limitations


@pytest.mark.anyio
async def test_search_refresh_clears_demo_fallback_warning():
    engine = FramingEngine(search(), DataMode.demo)
    session = await engine.create(FramingCreate(
        text="A race in Atlantis, 10 km on 2027-04-11, from Paris, 800 euros, 2 nights, train",
    ))
    assert any(limit.code == "demo_closest" for limit in session.limitations)
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision,
        corrections={SlotName.city: "Milan", SlotName.distance_km: 42.195},
    ))
    assert [candidate.city for candidate in session.candidates] == ["Milan"]
    assert not session.candidates[0].limitations
    assert not any(limit.code == "demo_closest" for limit in session.limitations)


@pytest.mark.anyio
@pytest.mark.parametrize("city", ["Valencia", "Milan", "Chamonix"])
async def test_idea_chip_reaches_confirmation(city):
    ideas = idea_chips()
    idea = ideas[["Valencia", "Milan", "Chamonix"].index(city)]
    engine = FramingEngine(search(), DataMode.demo)
    session = await engine.create(FramingCreate(text=idea))
    question = next(q for q in session.open_questions if q.slots == [SlotName.city])
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, question_id=question.id, text=city,
    ))
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision,
        corrections={SlotName.origin: "Lyon", SlotName.budget: 800,
                     SlotName.nights: 2, SlotName.transport_mode: "train",
                     SlotName.date_window: None,
                     **({SlotName.distance_km: 23} if city == "Chamonix" else {})},
    ))
    candidate = next(c for c in session.candidates if c.city == city)
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, choice_id=candidate.id,
    ))
    assert session.status is FramingStatus.ready_to_confirm
    assert session.summary.race.city == city


@pytest.mark.anyio
async def test_lisbon_then_milan_unblocks_conflicting_city_and_distance():
    engine = FramingEngine(search(), DataMode.demo)
    session = await engine.create(FramingCreate(text=idea_chips()[1]))
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, corrections={SlotName.city: "Lisbon",
        SlotName.budget: 800, SlotName.nights: 2, SlotName.transport_mode: "train",
        SlotName.date_window: None},
    ))
    assert [c.city for c in session.candidates] == ["Lisbon"]
    assert session.candidates[0].limitations[0].code == "close_match"
    question = session.open_questions[0]
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, question_id=question.id, text="Milan",
        corrections={SlotName.race: "Milan"},
    ))
    assert [c.city for c in session.candidates] == ["Milan"]
    session = await engine.reply(session.id, FramingReply(
        revision=session.revision, choice_id=session.candidates[0].id,
    ))
    assert session.status is FramingStatus.ready_to_confirm
    assert session.summary.race.city == "Milan"


@pytest.mark.anyio
@pytest.mark.parametrize("values", [{}, {"city": "nonsense"}, {"race": "nonsense"},
    {"city": "Lisbon", "distance_km": 42.195},
    {"city": "Milan", "race_date": "2099-01-01"},
    {"city": "Milan", "date_window": "October 2027"}])
async def test_demo_search_always_offers_recorded_candidates(values):
    result = await search().search(slots(**values), request_text="races in Atlantis")
    assert result.candidates
    if "nonsense" in values.values():
        assert len(result.candidates) == len(DEMO_RACES)
        assert result.limitations[0].code == "demo_closest"
        assert result.limitations[0].message == "Demo mode: no recorded race for that request — pick one of the recorded demo races below."
    if any(key in values for key in ("distance_km", "race_date", "date_window")):
        assert all(any(l.code == "close_match" for l in c.limitations) for c in result.candidates)


@pytest.mark.anyio
async def test_empty_demo_fixtures_and_unknown_fake_race_are_explicit_errors():
    with pytest.raises(ValueError, match="at least one"):
        FixtureCandidateSearch([], DataMode.demo)
    with pytest.raises(ValueError, match="No demo fixture"):
        await FakeRaceSearch(delay=0).find_race("Atlantis")


@pytest.mark.anyio
@pytest.mark.parametrize("kind", [StepKind.registration, StepKind.accommodation, StepKind.transport])
async def test_fake_actions_have_english_summaries_and_step_urls(kind):
    events, questions = [], []

    async def answer(question, options):
        questions.append(question)
        return options[0]

    race = DEMO_RACES["milan"]
    run = await FakeBrowserAgents(delay=0).start(
        kind, "Prepare demo", race, RunnerProfile(), events.append, answer,
    )
    result = await run.wait()
    assert result.data["headline"]
    assert "example.org" not in str(result.url)
    assert ("Your answers:" in result.summary) == bool(questions)
    if kind is StepKind.registration:
        assert questions == ["Which start corral should I pick?"]
        assert str(result.url) == str(race.registration_url) + "/rules"
        assert [e.data["url"] for e in events] == [
            str(race.registration_url) + suffix for suffix in ("", "/distance", "/runner", "/runner", "/rules")]
    assert FakeTranscriber.TEXT == "I want to run the Milan marathon, leaving from Paris."
