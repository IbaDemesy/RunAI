import json

import httpx
import pytest

from runai.contracts.common import DataMode
from runai.contracts.framing import FramingCreate, FramingTurn
from runai.framing.engine import FramingEngine
from runai.framing.holo import HoloPhraser, TemplatePhraser

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
