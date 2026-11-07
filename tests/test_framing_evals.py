import asyncio
import json
import sys

import httpx
import pytest

from runai.contracts.framing import SlotName
from runai.framing.interpret import extract_slots
from scripts.eval_framing import (
    SLOTS,
    TODAY,
    equal,
    live_predictions,
    load_cases,
    main,
    score,
)

# Measured on origin/main at harness creation: 39 exact matches out of 50 cases.
BASELINE = 0.78


def test_fixture_sanity():
    cases = load_cases()
    assert len(cases) >= 40
    assert len({case["id"] for case in cases}) == len(cases)
    assert set(SLOTS) <= {slot.value for slot in SlotName}
    for case in cases:
        assert isinstance(case["text"], str)
        assert set(case["expected"]) <= set(SLOTS)
        assert ("en" in case["tags"]) != ("fr" in case["tags"])
    assert {"Un marathon au printemps, depuis Lyon", "Lisbon",
            "Milan marathon in April 2027", "Tokyo 10K from London",
            "Marathon de Milan"} <= {case["text"] for case in cases}
    assert {"jury", "voice", "negation", "multi_city", "combo", "must_not_misfill"} <= {
        tag for case in cases for tag in case["tags"]}


def test_offline_baseline():
    cases = load_cases()
    result = score(cases, lambda text: extract_slots(text, today=TODAY))
    assert result["exact_match"] >= BASELINE
    assert not [case for case in result["failures"] if "pending_u1" not in case["tags"]]
    safe = [case for case in cases if "must_not_misfill" in case["tags"]
            and "pending_u1" not in case["tags"]]
    assert safe
    assert score(safe, lambda text: extract_slots(text, today=TODAY))["wrong_fills"] == 0


def test_score_normalization_and_wrong_values():
    cases = [{"id": "normalized", "text": "one", "expected": {"city": "Évry", "budget": None,
              "distance_km": 42.195}, "tags": ["must_not_misfill"]},
             {"id": "wrong", "text": "two", "expected": {"city": "Paris", "origin": "Lyon"},
              "tags": ["pending_u1"]}]
    predictions = {"one": {"city": "  EVRY ", "budget": None, "distance_km": 42.2},
                   "two": {"city": "Berlin", "transport_mode": "train"}}
    result = score(cases, predictions.__getitem__)
    assert result["exact_match"] == 0.5
    assert result["wrong_fills"] == 2
    assert result["missing"] == 1
    assert result["per_slot"]["city"] == {"tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5}
    assert result["must_not_misfill"]["exact_match"] == 1
    assert result["non_pending_u1"]["wrong_fills"] == 0
    assert result["non_pending_u1"]["exact_match"] == 1
    assert not equal(True, 1)
    assert not equal("42", 42)
    assert not equal(42, 43)


def test_empty_cases_and_empty_prediction():
    assert score([], lambda text: {})["exact_match"] == 0
    result = score([{"id": "empty", "text": "", "expected": {}, "tags": []}], lambda text: {})
    assert result["exact_match"] == 1
    assert result["wrong_fills"] == result["missing"] == 0


def test_predictor_error_is_not_scored_as_empty():
    def broken(text):
        raise RuntimeError("predictor unavailable")

    with pytest.raises(RuntimeError, match="predictor unavailable"):
        score([{"id": "error", "text": "", "expected": {}, "tags": []}], broken)


@pytest.mark.parametrize("status", [200, 429])
def test_live_transport_without_network(monkeypatch, status):
    monkeypatch.setenv("HAI_API_KEY", "test-key")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(status, json={"choices": [{"message": {"content": '{"city":"Milan"}'}}]})

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda: httpx.MockTransport(handler))
    if status == 429:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            asyncio.run(live_predictions([{"text": "Milan"}]))
    else:
        predictions, model = asyncio.run(live_predictions([{"text": "Milan"}]))
        assert predictions == {"Milan": {"city": "Milan"}}
        assert model == bodies[0]["model"] == "holo4-35b-a3b"


@pytest.mark.parametrize("ci", [False, True])
def test_live_requires_key_and_is_forbidden_in_ci(monkeypatch, capsys, ci):
    monkeypatch.setattr(sys, "argv", ["eval_framing", "--live", "--no-history"])
    monkeypatch.delenv("HAI_API_KEY", raising=False)
    monkeypatch.delenv("CI", raising=False)
    if ci:
        monkeypatch.setenv("CI", "true")
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert ("forbidden in CI" if ci else "requires HAI_API_KEY") in capsys.readouterr().err
