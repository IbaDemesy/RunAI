import json
from calendar import month_name
from datetime import date

import httpx
import pytest

from runai.contracts.common import DataMode
from runai.contracts.framing import FramingCreate, FramingTurn
from runai.framing.engine import FramingEngine
from runai.framing.holo import (
    EXTRACT_PROMPT,
    HoloPhraser,
    TemplatePhraser,
    _history,
    clean_extraction,
)

TURNS = [FramingTurn(role="user", text="A marathon in spring", revision=1)]


class NoCandidates:
    async def find_candidates(self, slots, request_text: str | None = None):
        return []


class Recorder:
    def __init__(self):
        self.calls = []

    async def phrase(self, turns, question, known):
        self.calls.append((len(turns), question, dict(known)))
        return "Great plan! " + question


def transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_holo_phraser_calls_h_models_and_returns_reply():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Great! Which city?"}}]})

    phraser = HoloPhraser("hk-test", transport=transport(handler))
    reply = await phraser.phrase(TURNS, "Which city?", {"distance_km": "42.195"})
    assert reply == "Great! Which city?"
    assert seen["url"] == "https://api.hcompany.ai/v1/chat/completions"
    assert seen["auth"] == "Bearer hk-test"
    assert seen["body"]["model"] == "holo4-35b-a3b"
    assert seen["body"]["reasoning_effort"] == "none"
    assert "Which city?" in seen["body"]["messages"][1]["content"]
    assert "Runner: " in seen["body"]["messages"][1]["content"]


@pytest.mark.anyio
@pytest.mark.parametrize("response", [
    httpx.Response(500),
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, json={"choices": [{"message": {"content": "No question."}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": "Where? When?"}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": "Where? More text."}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": {"text": "Where?"}}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": "x?" * 400}}]}),
])
async def test_holo_phraser_falls_back_to_local_wording(response):
    phraser = HoloPhraser("hk-test", transport=transport(lambda request: response))
    reply = await phraser.phrase(TURNS, "Which city?", {})
    assert reply == await TemplatePhraser().phrase(TURNS, "Which city?", {})
    assert reply.endswith("Which city?")


@pytest.mark.anyio
async def test_engine_adds_one_assistant_turn_for_the_next_question():
    phraser = Recorder()
    engine = FramingEngine(NoCandidates(), DataMode.demo, phraser=phraser)
    session = await engine.create(FramingCreate(text="I want to run a marathon", channel="text"))
    assert [turn.role for turn in session.turns] == ["user", "assistant"]
    assistant = session.turns[-1]
    assert assistant.revision == session.revision
    assert assistant.text == "Great plan! " + session.open_questions[0].text
    assert phraser.calls[0][2]["distance_km"]


@pytest.mark.anyio
async def test_engine_without_phraser_keeps_turns_unchanged():
    session = await FramingEngine(NoCandidates(), DataMode.demo).create(
        FramingCreate(text="I want to run a marathon", channel="text")
    )
    assert [turn.role for turn in session.turns] == ["user"]


@pytest.mark.anyio
async def test_holo_extract_parses_and_cleans_json():
    content = 'Result: {"city": "Paris", "date_window": "April 2027", "budget": "a lot", "nights": 2, "transport_mode": "rocket", "origin": "75001"}'
    phraser = HoloPhraser("hk-test", transport=transport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    ))
    assert await phraser.extract("une course en avril, Paris de préférence", {}) == {
        "city": "Paris", "date_window": "April 2027", "nights": 2,
    }


@pytest.mark.parametrize("window", ["décembre 2026", "December 2026", "DEC 2026"])
def test_holo_and_local_extraction_use_the_same_english_month_format(window):
    assert clean_extraction({"date_window": window}) == {"date_window": "December 2026"}


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["a race in December 2026", "une course en décembre 2026"])
async def test_holo_extract_context_accepts_both_languages(text):
    def handler(request):
        messages = json.loads(request.content)["messages"]
        assert messages[0]["content"] == EXTRACT_PROMPT
        assert "French or English" in EXTRACT_PROMPT
        assert '"April 2027"' in EXTRACT_PROMPT
        assert "Today:" in messages[1]["content"]
        assert "Recent conversation:" in messages[1]["content"]
        assert "Known context:" in messages[1]["content"]
        assert f"New message to analyze: {text}" in messages[1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"date_window": "December 2026"}'}}]})

    phraser = HoloPhraser("hk-test", transport=transport(handler))
    assert await phraser.extract(text, {}, TURNS) == {"date_window": "December 2026"}


@pytest.mark.anyio
async def test_clean_extraction_ignores_unhashable_transport():
    assert clean_extraction({"transport_mode": ["train"], "nights": 1}) == {"nights": 1}


def test_clean_extraction_keeps_numbered_race_names_but_not_numbered_cities():
    assert clean_extraction({"race": "UTMB 2027", "city": "75001"}) == {"race": "UTMB 2027"}


@pytest.mark.anyio
async def test_holo_extract_failure_returns_nothing():
    phraser = HoloPhraser("hk-test", transport=transport(lambda request: httpx.Response(503)))
    assert await phraser.extract("Paris", {}) == {}
    assert await TemplatePhraser().extract("Paris", {}) == {}


@pytest.mark.parametrize("distance", [10, 21.0975, 42.195, 400])
def test_clean_extraction_keeps_race_details(distance):
    year = date.today().year
    assert clean_extraction({
        "distance_km": distance, "race_date": f"{year}-04-18", "edition": year,
    }) == {"distance_km": distance, "race_date": f"{year}-04-18", "edition": str(year)}


@pytest.mark.parametrize("value", [0, -1, 400.1, True, "10K", None, float("inf"), float("nan")])
def test_clean_extraction_drops_invalid_distances(value):
    assert clean_extraction({"distance_km": value}) == {}


@pytest.mark.parametrize("value", ["2027-02-30", "2027-04", "20270418", "April 18", True, None,
                                   f"{date.today().year + 4}-04-18", f"{date.today().year - 4}-04-18"])
def test_clean_extraction_drops_invalid_dates(value):
    assert clean_extraction({"race_date": value}) == {}


@pytest.mark.parametrize("value", [True, None, 2027.5, "next year", date.today().year - 4, date.today().year + 4])
def test_clean_extraction_drops_invalid_editions(value):
    assert clean_extraction({"edition": value}) == {}


def test_date_window_uses_english_month_and_infers_next_occurrence():
    today = date.today()
    for month in range(1, 13):
        year = today.year + (month < today.month)
        assert clean_extraction({"date_window": month_name[month]}) == {
            "date_window": f"{month_name[month]} {year}",
        }
    assert clean_extraction({"date_window": "April 2027"}) == {"date_window": "April 2027"}
    assert clean_extraction({"date_window": "not a month"}) == {}
    assert clean_extraction({"date_window": f"April {today.year + 4}"}) == {}


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["{}", "not JSON", "{broken}", "[]"])
async def test_holo_extract_empty_or_malformed_output(content):
    phraser = HoloPhraser("hk-test", transport=transport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    ))
    assert await phraser.extract("Hello", {}) == {}


@pytest.mark.anyio
async def test_engine_fills_new_slots_from_mocked_holo_transport():
    year = date.today().year
    details = {"distance_km": 21.0975, "race_date": f"{year}-04-18", "edition": str(year)}
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        content = json.dumps(details) if "Extract travel" in body["messages"][0]["content"] else "Which city?"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    engine = FramingEngine(NoCandidates(), DataMode.demo, phraser=HoloPhraser("hk-test", transport=transport(handler)))
    session = await engine.create(FramingCreate(text="Please help me plan my event", channel="text"))
    for name, value in details.items():
        assert session.slots[name].is_known
        assert session.slots[name].value == value
    assert any("Today:" in call["messages"][1]["content"] for call in seen)


@pytest.mark.anyio
async def test_agent_follow_up_preserves_options_without_framing_question():
    question = "Which start wave: Discovery (4h30) or Performance (3h30)?"
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Got it. " + question}}]})

    phraser = HoloPhraser("hk-test", transport=transport(handler))
    assert await phraser.phrase([], question, {"course": "Runner's chosen race"}) == "Got it. " + question
    assert "keep those options verbatim and never add new ones" in seen[0]["messages"][0]["content"]
    assert "agent follow-up" in seen[0]["messages"][0]["content"]
    assert question in seen[0]["messages"][1]["content"]
    assert "Runner's chosen race" in seen[0]["messages"][1]["content"]


@pytest.mark.anyio
async def test_template_openers_and_history_are_english():
    turns = [*TURNS, FramingTurn(role="assistant", text="Which city?", revision=1), *TURNS]
    assert await TemplatePhraser().phrase([], "Which city?", {}) == "Let's plan this together. Which city?"
    assert await TemplatePhraser().phrase(turns, "Which city?", {}) == "Got it. Which city?"
    assert "Holo: Which city?" in _history(turns)


class Extractor(Recorder):
    def __init__(self, values):
        super().__init__()
        self.values = values

    async def extract(self, text, known, turns=()):
        return self.values


@pytest.mark.anyio
async def test_engine_fills_only_unknown_slots_from_holo():
    phraser = Extractor({"city": "Paris", "distance_km": 10, "nights": -3, "unknown_slot": "x"})
    engine = FramingEngine(NoCandidates(), DataMode.demo, phraser=phraser)
    session = await engine.create(FramingCreate(text="Un marathon en décembre en France (Paris de préférence)", channel="text"))
    assert session.slots["city"].value == "Paris"
    assert session.slots["distance_km"].value == 42.195
    assert not session.slots["nights"].is_known
    assert not any(q.slots == ["city"] for q in session.open_questions)


class TwoCandidates:
    async def find_candidates(self, slots, request_text: str | None = None):
        from runai.app.candidates import FixtureCandidateSearch
        from runai.app.fakes import DEMO_RACES
        return (
            await FixtureCandidateSearch(list(DEMO_RACES.values()), DataMode.demo)
            .find_candidates(slots, request_text=request_text)
        )[:2]


class LegacyCandidateSearch:
    async def find_candidates(self, slots):
        return []


@pytest.mark.anyio
async def test_engine_does_not_pass_request_text_to_legacy_finders():
    engine = FramingEngine(LegacyCandidateSearch(), DataMode.demo)
    session = await engine.create(
        FramingCreate(
            text=(
                "une course à Milan, 42.195 km en avril 2027, depuis Lyon, "
                "300 euros, 2 nuits, train"
            ),
            channel="text",
        )
    )
    assert not session.candidates


@pytest.mark.anyio
async def test_candidate_question_is_announced_plainly_not_rephrased():
    phraser = Recorder()
    engine = FramingEngine(TwoCandidates(), DataMode.demo, phraser=phraser)
    session = await engine.create(
        FramingCreate(
            text=(
                "une course à Milan, 42.195 km en avril 2027, depuis Lyon, "
                "300 euros, 2 nuits, train"
            ),
            channel="text",
        )
    )
    if not session.candidates:
        pytest.skip("no demo candidates for Milan")
    assert session.turns[-1].role == "assistant"
    assert "found" in session.turns[-1].text and "below" in session.turns[-1].text
    assert phraser.calls == []
