import json
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app

from .helpers import checked, events, prepare, reply, run_mission


@pytest.fixture
def client(tmp_path):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as http:
        yield http


@pytest.fixture
def mission(client):
    return run_mission(client)


@pytest.mark.parametrize("city", ["Milan", "Lisbon", "Tokyo"])
@pytest.mark.parametrize("channel", ["text", "voice"])
def test_judge_journey(client, city, channel):
    snapshot, journey, html, envelopes = run_mission(client, city, channel)
    base = f"/api/missions/{snapshot['mission_id']}"
    assert snapshot["race"]["city"] == city
    assert journey["revision"] == snapshot["journey_revision"]
    for step in snapshot["steps"]:
        if step["data"]["automation"] == "automated":
            assert step["status"] == "stopped_before_commitment" or snapshot["limitations"]
        assert not re.search(
            r"payment (?:confirmed|successful|completed)|paid successfully|paiement (?:confirmé|effectué)|réservation confirmée",
            step["summary"], re.IGNORECASE,
        )
        if step.get("h_session_id"):
            live = checked(client.get(f"/api/live/{step['h_session_id']}"))
            assert live["mission_id"] == snapshot["mission_id"]
            assert live["step"]["kind"] == step["kind"]
    assert [e["sequence"] for e in envelopes] == list(range(1, len(envelopes) + 1))
    assert all(e["schema_version"] == "events.v1" for e in envelopes)
    cursor = len(envelopes) // 2
    resumed = events(client.get(base + "/events", headers={"Last-Event-ID": envelopes[cursor]["event_id"]}))
    assert resumed == envelopes[cursor + 1:]
    assert client.get(base + "/events", headers={"Last-Event-ID": "invalid:2"}).status_code == 409
    assert events(client.get(base + "/events", headers={"Last-Event-ID": envelopes[-1]["event_id"]})) == []
    public = json.dumps([snapshot, envelopes])
    assert not re.search(r"sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|(?:api_key|password)\s*[=:]\s*[^\s]+", public, re.IGNORECASE)
    assert "text/html" in client.get(base + "/recap.html").headers["content-type"]
    assert html and journey["mission_id"] == snapshot["mission_id"]


def test_optional_pdf(client, mission):
    if not (shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")):
        pytest.skip("No local Chrome PDF renderer")
    response = client.get(f"/api/missions/{mission[0]['mission_id']}/recap.pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")


@pytest.mark.xfail(strict=False, reason="GAP-W1-1: mission.v2 snapshot steps (StepResult) do not expose human_action for stop points")
def test_stop_points_expose_human_action(client, mission):
    snapshot = checked(client.get(f"/api/missions/{mission[0]['mission_id']}"))
    stopped = [step for step in snapshot["steps"] if step["stop_point"]]
    assert stopped
    for step in stopped:
        assert (step.get("human_action") or "").strip(), "Stop point is missing its HTTP human_action"


@pytest.mark.xfail(strict=False, reason="JURY-W1-1: display an integral euro budget without a decimal suffix")
def test_budget_display(mission):
    snapshot, _, html, _ = mission
    assert snapshot["budget"]["cap"] == 800
    assert "€800" in html
    assert "800.0" not in html


@pytest.mark.xfail(strict=False, reason="JURY-W1-2: omit empty user-answer summaries")
def test_no_empty_answers(mission):
    assert all(not re.search(r"(?:Réponses utilisateur|User answers)\s*:\s*\.", s["summary"]) for s in mission[0]["steps"])


@pytest.mark.xfail(strict=False, reason="JURY-W1-3: ask about the start pen only once per step")
def test_no_duplicate_start_pen(mission):
    questions = mission[0]["questions"]
    for step in mission[0]["steps"]:
        topics = [q for q in questions if q["step"] == step["kind"] and re.search(r"\bsas\b|start pen", q["text"], re.IGNORECASE)]
        assert len(topics) <= 1


@pytest.mark.xfail(strict=False, reason="JURY-W1-4: a known race date resolves the period question")
def test_known_date_resolves_period(client):
    session = prepare(client)
    session = reply(client, session, corrections={"race_date": "2027-04-11"})
    assert session["slots"]["race_date"]["value"] == "2027-04-11"
    assert not any("date_window" in q["slots"] for q in session["open_questions"])
    assert not any(re.search(r"Période\s*\?|period.*unknown", line, re.IGNORECASE) for line in session["summary"]["lines"])


@pytest.mark.xfail(strict=False, reason="JURY-W1-5: parse an English month as a period, never as the city")
def test_english_month_is_not_city(client):
    session = checked(client.post("/api/framings", json={"text": "Milan marathon in April 2027"}), 201)
    assert session["slots"]["city"]["value"] == "Milan"
    assert session["candidates"]


@pytest.mark.xfail(strict=False, reason="JURY-W1-6: city reply after a marathon chip offers the nearest demo fixture")
def test_chip_city_nearest_fixture(client):
    session = checked(client.post("/api/framings", json={"text": "marathon from Lyon"}), 201)
    session = reply(client, session, text="Lisbon")
    assert session["candidates"], session
    assert any(c["city"] == "Lisbonne" for c in session["candidates"])


@pytest.mark.xfail(strict=False, reason="JURY-W1-7: journey and recap reflect selected race, hotel and transport cards (jury-2 #5)")
def test_journey_recap_consistent_with_cards(mission):
    snapshot, journey, html, _ = mission
    assert snapshot["race"]["name"] in html
    hotel = next(s for s in snapshot["steps"] if s["kind"] == "accommodation")
    assert hotel["status"] == "stopped_before_commitment"
    assert any(s["kind"] == "hotel" and not re.search(r"non choisi|not chosen|unknown|inconnu", s["label"], re.IGNORECASE) for s in journey["stops"])
    assert not re.search(r"hôtel non choisi|hotel not chosen", html, re.IGNORECASE)
    transport = next(s for s in snapshot["steps"] if s["kind"] == "transport")
    assert transport["status"] == "stopped_before_commitment"
    assert any(s["mode"] == "train" and s["cost"] for s in journey["segments"])
