import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from runai.app.history import build_headline, list_summaries, summarize
from runai.app.mission import Mission, MissionStatus
from runai.app.server import build_demo_service, create_app
from runai.models import StepKind, StepResult, StepStatus, utcnow

TERMINAL = {"awaiting_human", "failed", "completed", "cancelled"}


def launch(client, user_id, key):
    text = "une course à Milan, 42.195 km en avril 2027, depuis Lyon, 900 euros, 2 nuits, train"
    body = {"text": text, "channel": "text"}
    if user_id is not None:
        body["user_id"] = user_id
    response = client.post("/api/framings", json=body)
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["user_id"] == user_id
    session = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], "choice_id": session["candidates"][0]["id"],
    }).json()
    session = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"],
        "corrections": {"origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "train"},
    }).json()
    assert session["status"] == "ready_to_confirm", session
    response = client.post(f"/api/framings/{session['id']}/confirm", json={
        "revision": session["revision"], "idempotency_key": f"history-{key}",
    })
    assert response.status_code == 200, response.text
    return response.json()["mission_id"]


def finish(client, mission_id):
    for _ in range(400):
        mission = client.get(f"/api/missions/{mission_id}").json()
        for question in mission["questions"]:
            if question["status"] == "open":
                client.post(
                    f"/api/missions/{mission_id}/questions/{question['question_id']}/answer",
                    json={"revision": question["revision"], "answer": question["choices"][0],
                          "idempotency_key": f"answer-{question['question_id']}"},
                )
        if mission["status"] in TERMINAL:
            return mission
        time.sleep(.005)
    pytest.fail("Mission did not finish")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as test_client:
        yield test_client


def test_history_lists_missions_per_user_with_summary_fields(client):
    first = launch(client, "runner-a", 1)
    second = launch(client, "runner_b", 2)
    snapshots = {mid: finish(client, mid) for mid in (first, second)}

    mine = client.get("/api/missions", params={"user_id": "runner-a"})
    assert mine.status_code == 200
    [item] = mine.json()
    assert item["mission_id"] == first
    assert item["user_id"] == "runner-a"
    assert item["mode"] == "demo"
    assert item["framing_id"]
    assert item["status"] == snapshots[first]["status"] == "awaiting_human"
    assert item["finished_at"] and item["finished_at"] >= item["created_at"]
    assert item["race"]["city"] == "Milan"
    assert item["origin"] == "Lyon"
    assert item["budget_eur"] == 900
    assert len(item["date_range"]) == 2
    prices = [s["price_eur"] for s in snapshots[first]["steps"] if s["price_eur"] is not None]
    assert prices
    assert item["total_price_eur"] == pytest.approx(sum(prices))
    assert {s["kind"] for s in item["steps"]} == {"registration", "accommodation", "transport"}
    assert all(s["status"] == "stopped_before_commitment" for s in item["steps"])
    assert item["headline"] == "Prepared up to payment on 3 of 3 steps"
    assert item["replay_available"] is True

    assert [m["mission_id"] for m in client.get("/api/missions", params={"user_id": "runner_b"}).json()] == [second]
    assert client.get("/api/missions", params={"user_id": "nobody"}).json() == []
    everyone = client.get("/api/missions").json()
    assert [m["mission_id"] for m in everyone] == [second, first]

    summary = client.get(f"/api/missions/{first}/summary")
    assert summary.status_code == 200
    assert summary.json() == item


def test_history_is_newest_first_limited_and_filtered_by_status(client):
    ids = [launch(client, "runner-a", n) for n in range(3)]
    for mid in ids:
        finish(client, mid)
    listed = client.get("/api/missions", params={"user_id": "runner-a", "limit": 2}).json()
    assert [m["mission_id"] for m in listed] == [ids[2], ids[1]]
    assert client.get("/api/missions", params={"status": "awaiting_human"}).json()
    assert client.get("/api/missions", params={"status": "running"}).json() == []


def test_history_rejects_bad_input_and_unknown_mission(client):
    assert client.get("/api/missions/doesnotexist/summary").status_code == 404
    assert client.get("/api/missions", params={"user_id": "bad id!"}).status_code == 422
    assert client.get("/api/missions", params={"user_id": "x" * 65}).status_code == 422
    assert client.get("/api/missions", params={"limit": 0}).status_code == 422
    assert client.get("/api/missions", params={"status": "paid"}).status_code == 422
    assert client.post("/api/framings", json={"text": "a race", "user_id": "a/b"}).status_code == 422
    assert client.post("/api/framings", json={"text": "a race", "user_id": ""}).status_code == 422
    assert client.get("/api/missions").json() == []


def mission(mid, status, statuses, *, user_id=None, created_delta=0, prices=()):
    steps = {}
    for index, (kind, step_status) in enumerate(zip(
        (StepKind.registration, StepKind.accommodation, StepKind.transport), statuses
    )):
        price = prices[index] if index < len(prices) else None
        steps[kind] = StepResult(kind=kind, status=step_status, price_eur=price)
    return Mission(
        id=mid, query="q", status=status, steps=steps, user_id=user_id,
        created_at=utcnow() + timedelta(seconds=created_delta),
    )


def test_headlines_and_totals_for_every_outcome():
    stop, run, fail = StepStatus.stopped_before_commitment, StepStatus.running, StepStatus.failed
    assert build_headline(mission("a", MissionStatus.running, [stop, run, run])) == "In progress: 1 of 3 steps prepared so far"
    assert build_headline(mission("b", MissionStatus.cancelled, [stop, stop, run])) == "Cancelled after preparing 2 of 3 steps"
    assert build_headline(mission("c", MissionStatus.failed, [fail, fail, fail])) == "Failed before reaching any payment page"
    assert build_headline(mission("d", MissionStatus.awaiting_human, [stop, fail, stop])) == "Prepared up to payment on 2 of 3 steps"
    summary = summarize(mission("e", MissionStatus.awaiting_human, [stop, stop, stop], prices=(45.5, 120, 80.25)))
    assert summary.total_price_eur == pytest.approx(245.75)
    assert summary.race is None and summary.framing_id is None
    assert summarize(mission("f", MissionStatus.running, [run, run, run])).total_price_eur is None


def test_list_summaries_orders_by_creation_time_not_insertion():
    old = mission("old", MissionStatus.completed, [], user_id="u", created_delta=-60)
    new = mission("new", MissionStatus.completed, [], user_id="u", created_delta=0)
    other = mission("other", MissionStatus.completed, [], user_id="v", created_delta=30)
    assert [s.mission_id for s in list_summaries([new, old, other], user_id="u")] == ["new", "old"]
    assert [s.mission_id for s in list_summaries([new, old, other], limit=1)] == ["other"]
