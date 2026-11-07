import json
import time
from concurrent.futures import ThreadPoolExecutor

TERMINAL = {"awaiting_human", "completed", "failed", "cancelled"}


def checked(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def reply(client, session, **values):
    return checked(client.post(f"/api/framings/{session['id']}/replies", json={
        "revision": session["revision"], **values,
    }))


def prepare(client, city="Milan", channel="text"):
    session = checked(client.post("/api/framings", json={
        "text": f"A race in {city}", "channel": channel,
    }), 201)
    session = reply(client, session, corrections={
        "city": "Lisbonne" if city == "Lisbon" else city,
        "distance_km": 42.195 if city == "Milan" else 10,
        "date_window": {"Milan": "2027-04", "Lisbon": "2027-03", "Tokyo": "2028-06"}[city],
        "origin": "Lyon", "budget": 800, "nights": 2,
        "transport_mode": "train" if city == "Milan" else "flight",
    }, channel=channel)
    assert session["candidates"], session
    session = reply(client, session, choice_id=session["candidates"][0]["id"], channel=channel)
    session = reply(client, session, corrections={
        "origin": "Lyon", "budget": 800, "nights": 2,
        "transport_mode": "train" if city == "Milan" else "flight",
    }, channel=channel)
    assert session["status"] == "ready_to_confirm", session
    assert any(t["channel"] == channel and t["role"] == "user" for t in session["turns"])
    return session


def events(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def run_mission(client, city="Milan", channel="text"):
    started = time.monotonic()
    framing = prepare(client, city, channel)
    snapshot = checked(client.post(f"/api/framings/{framing['id']}/confirm", json={
        "revision": framing["revision"], "idempotency_key": "judge-confirm",
    }))
    base = f"/api/missions/{snapshot['mission_id']}"
    answered = set()
    # TestClient buffers SSE until EOF, so a second HTTP consumer answers questions.
    with ThreadPoolExecutor(max_workers=1) as pool:
        stream = pool.submit(client.get, base + "/events")
        while time.monotonic() - started < 4:
            snapshot = checked(client.get(base))
            for question in snapshot["questions"]:
                if question["status"] == "open":
                    checked(client.post(base + f"/questions/{question['question_id']}/answer", json={
                        "revision": question["revision"],
                        "idempotency_key": "judge-" + question["question_id"],
                        "answer": question["choices"][0],
                    }))
                    answered.add(question["question_id"])
            if snapshot["status"] in TERMINAL:
                break
            time.sleep(.001)
        else:
            client.post(base + "/cancel")
            raise AssertionError("Mission did not terminate within four seconds")
        streamed = events(stream.result(timeout=1))
    envelopes = events(client.get(base + "/events"))
    assert streamed == envelopes[:len(streamed)]
    assert snapshot["status"] == "awaiting_human", snapshot
    opened = {e["payload"]["question_id"] for e in envelopes if e["type"] == "question_opened"}
    assert opened == answered, (opened - answered, answered - opened)
    assert any(e["type"] == "mission_status" and e["payload"]["status"] in TERMINAL for e in envelopes)
    journey = checked(client.get(base + "/journey"))
    html = client.get(base + "/recap.html")
    calendar = client.get(base + "/recap.ics")
    assert html.status_code == calendar.status_code == 200
    assert "BEGIN:VCALENDAR" in calendar.text
    assert time.monotonic() - started < 5
    return snapshot, journey, html.text, envelopes
