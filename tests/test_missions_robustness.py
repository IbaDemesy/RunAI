"""W4 audit regressions: mission persistence, cancellation, H credits, closure errors, growth, leaks."""

import asyncio
import json
import time
from datetime import date
from functools import partial

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app
from runai.app.tasks import TripBrief
from runai.contracts.framing import FramingSummary, FramingTurn
from runai.framing.launch import LaunchPlan, StepPlan
from runai.models import Race, StepKind

AGENT_STEPS = (StepKind.registration, StepKind.accommodation, StepKind.transport)


def _plan(name="Tokyo 10K"):
    race = Race(name=name, city="Tokyo", country="JP", race_date=date(2028, 6, 12), distance_km=10)
    summary = FramingSummary(revision=1, race=race, origin_public="Lyon", nights=2,
                             date_range=(date(2028, 6, 11), date(2028, 6, 13)),
                             budget_eur=1000, transport_mode="flight", lines=[])
    plan = LaunchPlan(framing_id="w4-framing", revision=1, mode="demo", race=race,
                      brief=TripBrief(race_label=race.name, city=race.city, country=race.country),
                      steps={kind: StepPlan(kind=kind, automation="automated", task="Stop before payment")
                             for kind in AGENT_STEPS})
    return plan, summary


def _start(client, service, user_id=None):
    plan, summary = _plan()
    return client.portal.call(partial(service.create, plan, summary=summary, user_id=user_id,
                                      turns=[FramingTurn(role="user", text="Plan my Tokyo race", revision=1)]))


def _finish(client, mission_id):
    route = f"/api/missions/{mission_id}"
    for _ in range(400):
        snapshot = client.get(route).json()
        if snapshot["status"] in {"awaiting_human", "completed", "failed", "cancelled"}:
            return snapshot
        for question in snapshot["questions"]:
            if question["status"] == "open":
                client.post(f"{route}/questions/{question['question_id']}/answer", json={
                    "answer": question["choices"][0], "revision": question["revision"],
                    "idempotency_key": f"w4-{question['question_id']}",
                })
        time.sleep(.005)
    pytest.fail("Demo mission did not finish")


# --- M1 ------------------------------------------------------------------------------------------

def test_m1_user_id_round_trips_through_store_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    original = build_demo_service(delay=0)
    with TestClient(create_app(original)) as client:
        mission = _start(client, original, user_id="alice")
        _finish(client, mission.id)
        assert [item["mission_id"] for item in client.get("/api/missions?user_id=alice").json()] == [mission.id]
    stored = json.loads((tmp_path / "missions" / f"{mission.id}.json").read_text())
    assert stored["user_id"] == "alice"

    restored = build_demo_service(delay=0)
    with TestClient(create_app(restored)) as client:
        assert restored.missions[mission.id].user_id == "alice"
        listed = client.get("/api/missions?user_id=alice").json()
        assert [item["mission_id"] for item in listed] == [mission.id]
        assert client.get("/api/missions?user_id=bob").json() == []
        assert client.get("/api/prefill?user_id=alice").json()
