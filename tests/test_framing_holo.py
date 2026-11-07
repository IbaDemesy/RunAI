import json

import httpx
import pytest

from runai.contracts.common import DataMode
from runai.contracts.framing import FramingCreate, FramingTurn
from runai.framing.engine import FramingEngine
from runai.framing.holo import HoloPhraser, TemplatePhraser, clean_extraction

TURNS = [FramingTurn(role="user", text="Un marathon au printemps", revision=1)]


class NoCandidates:
    async def find_candidates(self, slots, request_text: str | None = None):
        return []


class Recorder:
    def __init__(self):
        self.calls = []

    async def phrase(self, turns, question, known):
        self.calls.append((len(turns), question, dict(known)))
        return "Super projet ! " + question


def transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_holo_phraser_calls_h_models_and_returns_reply():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "« Génial ! Dans quelle ville ? »"}}]})

    phraser = HoloPhraser("hk-test", transport=transport(handler))
    reply = await phraser.phrase(TURNS, "Dans quelle ville ?", {"distance_km": "42.195"})
    assert reply == "Génial ! Dans quelle ville ?"
    assert seen["url"] == "https://api.hcompany.ai/v1/chat/completions"
    assert seen["auth"] == "Bearer hk-test"
    assert seen["body"]["model"] == "holo4-35b-a3b"
    assert seen["body"]["reasoning_effort"] == "none"
    assert "Dans quelle ville ?" in seen["body"]["messages"][1]["content"]


@pytest.mark.anyio
@pytest.mark.parametrize("response", [
    httpx.Response(500),
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, json={"choices": [{"message": {"content": "Sans question."}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": {"text": "Où ?"}}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": "x?" * 400}}]}),
])
async def test_holo_phraser_falls_back_to_local_wording(response):
    phraser = HoloPhraser("hk-test", transport=transport(lambda request: response))
    reply = await phraser.phrase(TURNS, "Dans quelle ville ?", {})
    assert reply == await TemplatePhraser().phrase(TURNS, "Dans quelle ville ?", {})
    assert reply.endswith("Dans quelle ville ?")


@pytest.mark.anyio
async def test_engine_adds_one_assistant_turn_for_the_next_question():
    phraser = Recorder()
    engine = FramingEngine(NoCandidates(), DataMode.demo, phraser=phraser)
    session = await engine.create(FramingCreate(text="Je veux courir un marathon", channel="text"))
    assert [turn.role for turn in session.turns] == ["user", "assistant"]
    assistant = session.turns[-1]
    assert assistant.revision == session.revision
    assert assistant.text == "Super projet ! " + session.open_questions[0].text
    assert phraser.calls[0][2]["distance_km"]


@pytest.mark.anyio
async def test_engine_without_phraser_keeps_turns_unchanged():
    session = await FramingEngine(NoCandidates(), DataMode.demo).create(
        FramingCreate(text="Je veux courir un marathon", channel="text")
    )
    assert [turn.role for turn in session.turns] == ["user"]


@pytest.mark.anyio
async def test_holo_extract_parses_and_cleans_json():
    content = 'Voici : {"city": "Paris", "date_window": "décembre 2026", "budget": "beaucoup", "nights": 2, "transport_mode": "fusée", "origin": "75001"}'
    phraser = HoloPhraser("hk-test", transport=transport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    ))
    assert await phraser.extract("une course en décembre, Paris de préférence", {}) == {
        "city": "Paris", "date_window": "décembre 2026", "nights": 2,
    }


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


class Extractor(Recorder):
    def __init__(self, values):
        super().__init__()
        self.values = values

    async def extract(self, text, known):
        return self.values


@pytest.mark.anyio
async def test_engine_fills_only_unknown_slots_from_holo():
    phraser = Extractor({"city": "Paris", "distance_km": 10, "nights": -3, "unknown_slot": "x"})
    engine = FramingEngine(NoCandidates(), DataMode.demo, phraser=phraser)
    session = await engine.create(FramingCreate(text="Un marathon en décembre en France (Paris de préférence)", channel="text"))
    assert session.slots["city"].value == "Paris"
    assert session.slots["distance_km"].value == 42.195
    assert not session.slots["nights"].is_known
    assert not any("ville" in q.text.lower() and "partez" not in q.text.lower() for q in session.open_questions)


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
        FramingCreate(text="une course à Milan", channel="text")
    )
    assert not session.candidates


@pytest.mark.anyio
async def test_candidate_question_is_announced_plainly_not_rephrased():
    phraser = Recorder()
    engine = FramingEngine(TwoCandidates(), DataMode.demo, phraser=phraser)
    session = await engine.create(FramingCreate(text="une course à Milan", channel="text"))
    if not session.candidates:
        pytest.skip("aucun candidat de démonstration pour Milan")
    assert session.turns[-1].role == "assistant"
    assert "trouvé" in session.turns[-1].text and "ci-dessous" in session.turns[-1].text
    assert phraser.calls == []
