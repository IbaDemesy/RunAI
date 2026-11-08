import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app

GOLDEN = Path(__file__).parent / "golden"
FORBIDDEN = {"screenshot", "png", "image_base64", "authorization"}


def key_paths(value, prefix=""):
    paths = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths.update(key_paths(item, path))
    elif isinstance(value, list):
        path = f"{prefix}[]"
        paths.add(path)
        for item in value:
            paths.update(key_paths(item, path))
    return paths


def compare_golden(name, actual, update):
    path = GOLDEN / name
    if path.exists():
        expected = json.loads(path.read_text())
        removed_types = set(expected) - set(actual)
        assert not removed_types, f"{name}: removed event types/sections: {sorted(removed_types)}"
        for section, keys in expected.items():
            removed = set(keys) - set(actual[section])
            assert not removed, f"{name}: {section}: removed key paths: {sorted(removed)}"
        for section, keys in actual.items():
            additions = set(keys) - set(expected.get(section, []))
            if additions:
                print(f"{name}: {section}: added key paths: {sorted(additions)}")
    else:
        assert update, f"Missing {name}; generate it with --update-golden"
    if update:
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")


@pytest.fixture(scope="module")
def demo_contract(tmp_path_factory):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path_factory.mktemp("contract-traces")
    with TestClient(create_app(service)) as client:
        response = client.post("/api/framings", json={
            "text": "A race in Milan, 42.195 km on 2027-04-11, from Lyon, 900 euros, 2 nights, train",
        })
        assert response.status_code == 201, response.text
        session = response.json()
        assert session["candidates"], session
        route = f"/api/framings/{session['id']}"
        response = client.post(f"{route}/replies", json={
            "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
        })
        assert response.status_code == 200, response.text
        session = response.json()
        response = client.post(f"{route}/replies", json={
            "revision": session["revision"], "corrections": {
                "origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "train",
            },
        })
        assert response.status_code == 200, response.text
        session = response.json()
        response = client.post(f"{route}/confirm", json={
            "revision": session["revision"], "idempotency_key": "contract-snapshot-confirm",
        })
        assert response.status_code == 200, response.text
        mid = response.json()["mission_id"]
        route = f"/api/missions/{mid}"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = client.get(route)
            assert response.status_code == 200, response.text
            snapshot = response.json()
            for question in snapshot["questions"]:
                if question["status"] == "open":
                    answer = client.post(f"{route}/questions/{question['question_id']}/answer", json={
                        "revision": question["revision"],
                        "idempotency_key": f"contract-answer-{question['question_id']}",
                        "answer": question["choices"][0],
                    })
                    assert answer.status_code == 200, answer.text
            if snapshot["status"] in {"awaiting_human", "failed", "completed", "cancelled"}:
                break
            time.sleep(.005)
        else:
            pytest.fail("Demo mission did not reach its pre-payment halt within 10 seconds")
        assert snapshot["status"] == "awaiting_human", snapshot
        response = client.get(f"{route}/events")
        assert response.status_code == 200, response.text
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        final = client.get(route)
        assert final.status_code == 200, final.text
        return events, final.json()


def steps(events):
    return [step for event in events if event["type"] == "step" for step in event["payload"]["steps"]]


def test_contract_key_snapshots(demo_contract, request):
    events, snapshot = demo_contract
    actual = {}
    for event in events:
        assert event["schema_version"] == "events.v1"
        actual.setdefault(event["type"], set()).update(key_paths(event["payload"]))
    update = request.config.getoption("--update-golden")
    compare_golden("events_v1_keys.json", {key: sorted(value) for key, value in actual.items()}, update)
    assert snapshot["schema_version"] == "mission.v2"
    compare_golden("mission_v2_keys.json", {"mission.v2": sorted(key_paths(snapshot))}, update)


def test_live_view_supported_invariants(demo_contract):
    events, _ = demo_contract
    assert events
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert steps(events), "Demo must emit step payloads"
    assert any(event["type"] == "question_opened" for event in events)
    assert any(event["type"] == "trace" for event in events)
    for step in steps(events):
        assert {"kind", "status"} <= step.keys()
        provenance = step["data"].get("provenance")
        if provenance is not None:
            assert provenance["mode"] in {"demo", "live", "replay"}
    for event in events:
        if event["type"] == "question_opened":
            assert {"question_id", "step", "text", "choices", "revision", "expires_at"} <= event["payload"].keys()
        if event["type"] == "trace":
            assert_no_forbidden_keys(event["payload"])


def assert_no_forbidden_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key.lower() not in FORBIDDEN, f"Trace contains forbidden key: {key}"
            assert_no_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_forbidden_keys(item)


@pytest.mark.xfail(strict=True, reason="backend gap: pending SSE steps have neither headline nor summary")
def test_every_step_has_headline_or_summary(demo_contract):
    for step in steps(demo_contract[0]):
        assert step.get("headline") or step["data"].get("headline") or step.get("summary")


@pytest.mark.xfail(strict=True, reason="backend gap: pending SSE steps have no data.provenance.mode")
def test_every_step_has_provenance(demo_contract):
    for step in steps(demo_contract[0]):
        assert step["data"].get("provenance", {}).get("mode") in {"demo", "live", "replay"}


def test_stopped_steps_have_human_action(demo_contract):
    stopped = [step for step in steps(demo_contract[0]) if step["status"] == "stopped_before_commitment"]
    assert stopped, "Demo must exercise the pre-payment halt"
    for step in stopped:
        assert step.get("human_action")


@pytest.mark.parametrize(("value", "expected"), [
    ({}, set()),
    ({"items": []}, {"items", "items[]"}),
    ({"items": [{"name": "one"}, {"price": 2}]}, {"items", "items[]", "items[].name", "items[].price"}),
])
def test_key_paths(value, expected):
    assert key_paths(value) == expected


def test_trace_guard_rejects_nested_forbidden_keys():
    with pytest.raises(AssertionError, match="Authorization"):
        assert_no_forbidden_keys({"data": [{"Authorization": "redacted"}]})


def test_golden_additions_and_update(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN", tmp_path)
    compare_golden("keys.json", {"step": ["kind"]}, True)
    original = (tmp_path / "keys.json").read_text()
    actual = {"step": ["kind", "status"], "trace": ["data"]}
    compare_golden("keys.json", actual, False)
    assert "added key paths: ['status']" in capsys.readouterr().out
    assert (tmp_path / "keys.json").read_text() == original
    compare_golden("keys.json", actual, True)
    assert json.loads((tmp_path / "keys.json").read_text()) == actual


@pytest.mark.parametrize(("actual", "message"), [
    ({}, "removed event types/sections: ['step']"),
    ({"step": []}, "removed key paths: ['kind']"),
])
def test_golden_removals_fail_even_when_updating(tmp_path, monkeypatch, actual, message):
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN", tmp_path)
    compare_golden("keys.json", {"step": ["kind"]}, True)
    with pytest.raises(AssertionError) as error:
        compare_golden("keys.json", actual, True)
    assert message in str(error.value)


def test_empty_and_missing_golden(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN", tmp_path)
    with pytest.raises(AssertionError, match="Missing keys.json"):
        compare_golden("keys.json", {}, False)
    compare_golden("keys.json", {}, True)
    compare_golden("keys.json", {}, False)
