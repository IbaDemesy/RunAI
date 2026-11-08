import json

import pytest
from fastapi.testclient import TestClient

from runai.app.mission import MissionStatus
from runai.app.server import build_demo_service, create_app
from runai.contracts.journey import CostLine
from runai.models import StepKind, StepStatus
from tests.test_v2_backend import confirm, finish, prepare


def test_demo_trip_outcome_and_sse(tmp_path):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Milan")).json()["mission_id"]
        snapshot = finish(client, mid)
        outcome = snapshot["outcome"]
        assert outcome["state"] == "prepared"
        assert len(outcome["steps"]) == 3
        assert all(step["handoff_url"] and step["stop_point_label"] for step in outcome["steps"])
        assert all(step["provider"] == "demo" for step in outcome["steps"])
        assert outcome["total"] == "€293"
        assert outcome["total_eur"] == 293
        assert outcome["budget_cap_eur"] == 900
        assert outcome["budget_status"] == "unknown"
        assert outcome["recap_urls"] == {
            fmt: f"/api/missions/{mid}/recap.{fmt}?revision={snapshot['journey_revision']}"
            for fmt in ("html", "pdf", "ics")
        }
        assert outcome["elapsed_s"] >= 0
        events = client.get(f"/api/missions/{mid}/events")
        envelopes = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")]
        assert next(e for e in envelopes if e["type"] == "mission_outcome")["payload"] == outcome
        assert next(e for e in envelopes if e["type"] == "mission_status")["payload"]["outcome"] == outcome


def test_cancelling_after_completion_is_a_noop(tmp_path):
    """M2: a prepared (terminal) mission stays prepared; cancel emits nothing."""
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Milan")).json()["mission_id"]
        finish(client, mid)
        status = service.get(mid).status
        before = len(service.get(mid).envelopes)
        client.portal.call(service.cancel, mid)
        client.portal.call(service.cancel, mid)
        assert service.get(mid).envelopes[before:] == []
        assert service.get(mid).status is status
        assert client.get(f"/api/missions/{mid}").json()["outcome"]["state"] != "cancelled"


def test_cancelled_mission_emits_outcome(tmp_path):
    service = build_demo_service(delay=.03)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Milan")).json()["mission_id"]
        client.portal.call(service.cancel, mid)
        outcome = client.get(f"/api/missions/{mid}").json()["outcome"]
        assert outcome["state"] == "cancelled"
        assert service.get(mid).finished_at is not None
        events = client.get(f"/api/missions/{mid}/events")
        envelopes = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")]
        assert sum(e["type"] == "mission_outcome" for e in envelopes) == 1
        assert next(e for e in envelopes if e["type"] == "mission_outcome")["payload"] == outcome


@pytest.mark.parametrize(("status", "ready", "state"), [
    ("running", False, "in_progress"), ("failed", False, "failed"),
    ("failed", True, "partial"), ("cancelled", True, "cancelled"),
])
def test_outcome_incomplete_and_error_cases(tmp_path, status, ready, state):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Milan")).json()["mission_id"]
        finish(client, mid)
        mission = service.get(mid)
        mission.status = MissionStatus(status)
        mission.journey = None
        for step in mission.steps.values():
            step.price_eur = None
            step.status = StepStatus.failed
            step.url = None
            step.stop_point = None
        if ready:
            mission.steps[StepKind.registration].status = StepStatus.stopped_before_commitment
        outcome = service.snapshot(mid).outcome
        assert outcome.state == state
        assert outcome.total is None and outcome.total_eur is None
        assert outcome.budget_status == "unknown"
        assert outcome.recap_urls == {}
        assert outcome.steps[0].handoff_url == str(mission.race.registration_url)


@pytest.mark.parametrize(("cap", "expected"), [(None, "no_cap"), (200, "over_cap"), (293, "within_cap")])
def test_outcome_budget_caps(tmp_path, cap, expected):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Milan")).json()["mission_id"]
        finish(client, mid)
        mission = service.get(mid)
        mission.plan.brief.budget_total_eur = cap
        mission.journey.budget.lines = [line for line in mission.journey.budget.lines if line.money]
        assert service.snapshot(mid).outcome.budget_status == expected


@pytest.mark.parametrize(("fee", "cap", "expected"), [(20, 310, "over_cap"), (20, 400, "within_cap"),
                                                        (None, 400, "unknown"), (None, 200, "over_cap")])
def test_outcome_includes_journey_fee_lines(tmp_path, fee, cap, expected):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Milan")).json()["mission_id"]
        finish(client, mid)
        mission = service.get(mid)
        mission.plan.brief.budget_total_eur = cap
        budget = mission.journey.budget
        budget.lines = [line for line in budget.lines if line.money]
        money = budget.lines[0].money.model_copy(update={"amount": fee}) if fee is not None else None
        budget.lines.append(CostLine(id="extra-fee", category="other", label="Extra fee", money=money))
        outcome = service.snapshot(mid).outcome
        assert outcome.total_eur == 293 + (fee or 0)
        assert outcome.total == f"€{293 + (fee or 0)}"
        assert outcome.budget_status == expected


def test_manual_steps_do_not_count_as_prepared(tmp_path):
    service = build_demo_service(delay=0)
    service.traces_dir = tmp_path
    with TestClient(create_app(service)) as client:
        mid = confirm(client, prepare(client, "Tokyo")).json()["mission_id"]
        finish(client, mid)
        mission = service.get(mid)
        for kind in mission.plan.automated_steps():
            mission.steps[kind].status = StepStatus.failed
        outcome = service.snapshot(mid).outcome
        assert outcome.state == "failed"
        transport = next(step for step in outcome.steps if step.kind is StepKind.transport)
        assert transport.status is StepStatus.completed
        assert transport.headline == "Not automated — plan this step yourself"
        assert transport.stop_point_label == transport.headline
