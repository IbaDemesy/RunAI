"""Executable product journeys and acceptance criteria.

AC-01: Milan framing, idempotent confirmation and pre-commitment stops (U3).
AC-02: Every IDEAS chip reaches confirmation with one plausible reply (U3).
AC-03: English prompts extract city and distance (U2).
AC-04: Summary copy has no None, float artifacts or empty joins, and readable budgets (U4).
AC-05: User-facing framing, mission and event strings are English (U5 translation).
AC-06: An agent answer resumes its step and is retained in the summary.
AC-07: Cancellation prevents subsequent step_done events.
AC-08: Completed missions export HTML and calendar recaps.
AC-09: SSE reconnection does not replay sequence numbers.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app
from tests.journey_helpers import drive_framing, poll_mission

ANSWERS = {"origin": "Lyon", "budget": 900, "nights": 2, "transport_mode": "train", "race_date": "2027-04-11"}
TERMINAL = {"awaiting_human", "completed", "failed", "cancelled"}


@pytest.fixture
def client(tmp_path):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        yield client


def start(client, text="Marathon de Milan"):
    response = client.post("/api/framings", json={"text": text, "channel": "text"})
    assert response.status_code == 201, response.text
    return response.json()


def ready(client, text="une course à Milan, 42.195 km en avril 2027", **answers):
    session = drive_framing(client, start(client, text), ANSWERS | answers)
    assert session["status"] == "ready_to_confirm", session
    return session


def confirm(client, session):
    response = client.post(f"/api/framings/{session['id']}/confirm", json={
        "revision": session["revision"], "idempotency_key": "product-journey-confirm",
    })
    assert response.status_code == 200, response.text
    return response.json()["mission_id"]


def answer_agents(client, mid):
    answered = {}

    def progress(snapshot):
        for question in snapshot["questions"]:
            if question["status"] == "open" and question["session_id"]:
                answer = question["choices"][0]
                response = client.post(f"/api/missions/{mid}/questions/{question['question_id']}/answer", json={
                    "revision": question["revision"], "answer": answer,
                    "idempotency_key": f"product-{question['question_id']}",
                })
                assert response.status_code == 200, response.text
                answered[question["step"]] = answer
        return snapshot["status"] in TERMINAL

    return poll_mission(client, mid, progress), answered


def events(client, mid, cursor=None):
    response = client.get(f"/api/missions/{mid}/events", headers={"Last-Event-ID": cursor} if cursor else {})
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def completed(client):
    session = ready(client)
    mid = confirm(client, session)
    snapshot, answers = answer_agents(client, mid)
    return session, mid, snapshot, answers


def test_ac01_happy_path(client):
    session = ready(client, "Marathon de Milan")
    mid = confirm(client, session)
    assert confirm(client, session) == mid
    snapshot, _ = answer_agents(client, mid)
    assert snapshot["status"] == "awaiting_human"
    assert len(snapshot["steps"]) == 3
    for step in snapshot["steps"]:
        assert step["status"] == "stopped_before_commitment"
        assert step["stop_point"] and step["url"]


def test_ac01_sourced_milan_happy_path(client, completed):
    session, mid, snapshot, _ = completed
    assert confirm(client, session) == mid
    assert snapshot["status"] == "awaiting_human"
    assert len(snapshot["steps"]) == 3
    for step in snapshot["steps"]:
        assert step["status"] == "stopped_before_commitment"
        assert step["stop_point"] and step["url"]


IDEAS = ["Mon premier semi en octobre", "Un marathon au printemps, depuis Lyon", "Un trail en montagne cet été"]


@pytest.mark.parametrize("idea", IDEAS)
@pytest.mark.xfail(strict=True, reason="AC-02, unit U3")
def test_ac02_idea_with_one_reply(client, idea):
    source = Path("runai/app/static/app.js").read_text()
    assert idea in source
    session = start(client, idea)
    response = client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"],
        "text": "Milan, avril 2027, depuis Lyon, 900 euros, 2 nuits, train",
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready_to_confirm"


@pytest.mark.parametrize(("prompt", "city", "distance"), [
    ("Milan marathon in April 2027", "Milan", 42.195),
    ("Tokyo 10K from London", "Tokyo", 10),
])
def test_ac03_english_slots(client, prompt, city, distance):
    slots = start(client, prompt)["slots"]
    assert slots["city"]["value"] == city
    assert slots["distance_km"]["value"] == pytest.approx(distance)


@pytest.mark.parametrize("budget", [900, None])
def test_ac04_no_none(client, budget):
    assert "None" not in " ".join(ready(client, budget=budget)["summary"]["lines"])


def test_ac04_no_float_artifacts(client):
    lines = ready(client, "une course à Tokyo, 10 km en juin 2028")["summary"]["lines"]
    assert not re.search(r"\.0(?:\s|$)", " ".join(lines)), lines


def test_ac04_no_empty_joins(client):
    assert ": ." not in " ".join(ready(client)["summary"]["lines"])


@pytest.mark.parametrize("budget", [900, None])
def test_ac04_readable_budget(client, budget):
    line = ready(client, budget=budget)["summary"]["lines"][-1]
    if budget is None:
        assert any(word in line.lower() for word in ("no limit", "unlimited", "sans plafond", "no budget cap", "no cap"))
    else:
        assert "900" in line and any(unit in line for unit in ("€", "EUR", "euros")), line


def user_strings(value, key=""):
    """Walk copy fields, excluding identifiers, URLs and raw user input."""
    fields = {"text", "label", "message", "summary", "lines", "reason", "name", "choices", "headline", "last_action", "warnings"}
    if isinstance(value, dict):
        for name, child in value.items():
            if name != "slots" and name != "turns":
                yield from user_strings(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from user_strings(child, key)
    elif isinstance(value, str) and key in fields:
        yield value


def test_ac05_english_only(client, completed):
    session, mid, snapshot, _ = completed
    strings = list(user_strings([start(client), session, snapshot, events(client, mid)]))
    assert strings
    violations = [s for s in strings if any(marker in s for marker in (" le ", " la ", "é", "Pas de", "Démo"))]
    assert not violations, violations


def test_ac06_agent_answer_resumes_and_is_in_summary(client, completed):
    _, _, snapshot, answers = completed
    assert answers
    for kind, answer in answers.items():
        step = next(s for s in snapshot["steps"] if s["kind"] == kind)
        assert step["status"] == "stopped_before_commitment"
        assert answer in step["summary"]


def test_ac07_cancel_mid_mission(client):
    mid = confirm(client, ready(client))
    waiting = poll_mission(client, mid, lambda s: any(q["status"] == "open" and q["session_id"] for q in s["questions"]))
    assert waiting["status"] not in TERMINAL
    response = client.post(f"/api/missions/{mid}/cancel")
    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled["status"] == "cancelled"
    sequence = cancelled["sequence"]
    assert client.get(f"/api/missions/{mid}").json()["status"] == "cancelled"
    assert not [e for e in events(client, mid)
                if e["sequence"] > sequence and e["payload"].get("type") == "step_done"]


def test_ac08_recap_exports(client, completed):
    _, mid, snapshot, _ = completed
    assert snapshot["status"] == "awaiting_human"
    html = client.get(f"/api/missions/{mid}/recap.html")
    calendar = client.get(f"/api/missions/{mid}/recap.ics")
    assert html.status_code == calendar.status_code == 200
    assert "<html" in html.text.lower()
    assert "BEGIN:VCALENDAR" in calendar.text


def test_ac09_sse_reconnect(client, completed):
    _, mid, _, _ = completed
    original = events(client, mid)
    assert len(original) > 3
    cursor = original[len(original) // 2]
    resumed = events(client, mid, cursor["event_id"])
    assert resumed == [e for e in original if e["sequence"] > cursor["sequence"]]
    sequences = [e["sequence"] for e in original[:len(original) // 2 + 1] + resumed]
    assert len(sequences) == len(set(sequences))
    assert events(client, mid, original[-1]["event_id"]) == []
