import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from runai.app.fakes import QUESTIONS
from runai.app.server import build_service, create_app
from runai.models import StepKind
from runai.safety import STOP_INSTRUCTIONS


@pytest.fixture
def demo(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNAI_MODE", "demo")
    monkeypatch.setenv("RUNAI_DEMO_DELAY", "0.01")

    def offline(*args, **kwargs):
        raise AssertionError("External HTTP is forbidden")

    monkeypatch.setattr(httpx.AsyncClient, "send", offline)
    service = build_service()
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        yield client, service


def launch(client):
    session = client.post("/api/framings", json={
        "text": "Tokyo",
    }).json()
    base = f"/api/framings/{session['id']}"
    session = client.post(base + "/replies", json={
        "revision": session["revision"],
        "corrections": {"city": "Tokyo", "distance_km": 10, "race_date": "2028-06-12",
                        "origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "flight"},
    }).json()
    session = client.post(base + "/replies", json={
        "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
    }).json()
    session = client.post(base + "/replies", json={
        "revision": session["revision"],
        "corrections": {"origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "flight"},
    }).json()
    response = client.post(base + "/confirm", json={
        "revision": session["revision"], "idempotency_key": "redteam-confirm",
    })
    assert response.status_code == 200, response.text
    return response.json()["mission_id"]


def poll(client, mid, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/missions/{mid}").json()
        if predicate(snapshot):
            return snapshot
        time.sleep(.002)
    pytest.fail("Demo mission did not progress")


def payload(q):
    return {"answer": q["choices"][0], "revision": q["revision"], "idempotency_key": "redteam-answer"}


def error(response, code):
    assert response.status_code == code, response.text
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"].strip()


def finish(client, mid):
    def advance(snapshot):
        for q in snapshot["questions"]:
            if q["status"] == "open":
                assert client.post(f"/api/missions/{mid}/questions/{q['question_id']}/answer", json=payload(q)).status_code == 200
        return snapshot["status"] in {"awaiting_human", "completed", "failed", "cancelled"}

    result = poll(client, mid, advance)
    assert result["status"] == "awaiting_human"
    return result


def test_answers_and_concurrent_duplicate(demo):
    client, _ = demo
    mid = launch(client)
    snapshot = poll(client, mid, lambda s: any(q["status"] == "open" for q in s["questions"]))
    q = next(q for q in snapshot["questions"] if q["status"] == "open")
    url = f"/api/missions/{mid}/questions/{q['question_id']}/answer"
    error(client.post(url, json={**payload(q), "answer": "not-an-option"}), 409)
    error(client.post(url, json={**payload(q), "revision": -1}), 409)
    error(client.post(f"/api/missions/{mid}/questions/unknown/answer", json=payload(q)), 409)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post(url, json=payload(q)), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert client.post(url, json=payload(q)).status_code == 200
    error(client.post(url, json={**payload(q), "answer": "different answer"}), 409)
    final = finish(client, mid)
    assert next(s for s in final["steps"] if s["kind"] == q["step"])["status"] == "stopped_before_commitment"


def test_controls_messages_and_cancel(demo):
    client, service = demo
    mid = launch(client)
    poll(client, mid, lambda s: bool(s["questions"]))
    base = f"/api/missions/{mid}"
    step = base + "/steps/registration"
    for action in ("resume", "pause", "pause", "resume"):
        assert client.post(step + "/" + action).status_code == 200
    error(client.post(step + "/message", json={"text": "x" * 501}), 422)
    error(client.post(step + "/message", json={"text": '<script>\n"pay now with card"'}), 409)
    text = '<script>\n"prefer the 10 km distance"'
    assert client.post(step + "/message", json={"text": text}).status_code == 200
    run = service._runs[(mid, StepKind.registration)].run
    assert run.received[-1].endswith(STOP_INSTRUCTIONS)
    assert text in run.received[-1]
    assert client.post(base + "/cancel").status_code == 200
    count = len(service.agents.agents.runs)
    for path in ("/pause", "/resume", "/steps/registration/pause", "/steps/registration/resume"):
        error(client.post(base + path), 409)
    error(client.post(step + "/message", json={"text": "hello"}), 409)
    error(client.post(base + "/questions/unknown/answer", json={
        "answer": "yes", "revision": 1, "idempotency_key": "cancelled-answer",
    }), 409)
    assert client.get(base).json()["status"] == "cancelled"
    assert len(service.agents.agents.runs) == count
    stream = client.get(base + "/events").text
    events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
    assert any(text in e["payload"].get("message", "") for e in events)
    assert '\\n' in stream and '\\"prefer the 10 km distance\\"' in stream


def test_competing_valid_answers_have_one_effect(demo):
    client, _ = demo
    mid = launch(client)
    snapshot = poll(client, mid, lambda s: bool(s["questions"]))
    q = snapshot["questions"][0]
    url = f"/api/missions/{mid}/questions/{q['question_id']}/answer"
    requests = [{**payload(q), "answer": choice} for choice in q["choices"][:2]]
    assert len(requests) == 2
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda body: client.post(url, json=body), requests))
    assert sorted(r.status_code for r in responses) == [200, 409]
    error(next(r for r in responses if r.status_code == 409), 409)
    winner = requests[next(i for i, r in enumerate(responses) if r.status_code == 200)]["answer"]
    final = finish(client, mid)
    assert next(item for item in final["questions"] if item["question_id"] == q["question_id"])["answer"] == winner
    events = client.get(f"/api/missions/{mid}/events").text
    resolved = [json.loads(line[6:]) for line in events.splitlines() if line.startswith("data: ")]
    assert sum(e["type"] == "question_resolved" and e["payload"]["question_id"] == q["question_id"] for e in resolved) == 1


def test_empty_options_allow_free_text(demo, monkeypatch):
    client, _ = demo
    monkeypatch.setitem(QUESTIONS, StepKind.registration, [("Preferred start time?", [])])
    mid = launch(client)
    snapshot = poll(client, mid, lambda s: bool(s["questions"]))
    q = snapshot["questions"][0]
    response = client.post(f"/api/missions/{mid}/questions/{q['question_id']}/answer", json={
        "answer": "morning", "revision": q["revision"], "idempotency_key": "free-text-answer",
    })
    assert response.status_code == 200
    finish(client, mid)


def test_unknown_and_bad_cursors(demo):
    client, _ = demo
    error(client.get("/api/missions/unknown"), 404)
    mid = launch(client)
    for cursor in ("abc", "-1", mid + ":" + "9" * 5000):
        error(client.get(f"/api/missions/{mid}/events", headers={"Last-Event-ID": cursor}), 400)


def test_ten_concurrent_missions_and_replay(demo):
    client, _ = demo
    with ThreadPoolExecutor(10) as pool:
        mids = list(pool.map(lambda _: launch(client), range(10)))
        results = list(pool.map(lambda mid: finish(client, mid), mids))
    assert len({r["mission_id"] for r in results}) == 10
    for mid in mids:
        url = f"/api/missions/{mid}/events"
        ids = [line[4:] for line in client.get(url).text.splitlines() if line.startswith("id: ")]
        index = len(ids) // 2
        replay = client.get(url, headers={"Last-Event-ID": ids[index]})
        resumed = [line[4:] for line in replay.text.splitlines() if line.startswith("id: ")]
        assert resumed == ids[index + 1:]
        assert len(resumed) == len(set(resumed))
