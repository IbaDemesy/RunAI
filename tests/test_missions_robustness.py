"""W4 audit regressions: mission persistence, cancellation, H credits, closure errors, growth, leaks."""

import asyncio
import json
import time
from datetime import date
from functools import partial
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runai.app.server import build_demo_service, create_app
from runai.app.tasks import TripBrief
from runai.contracts.framing import FramingSummary, FramingTurn
from runai.framing.launch import LaunchPlan, StepPlan
from runai.h import HAccount, HQuotaTimeout, HRunner
from runai.h.lifecycle import HCreditsExhausted, HLifecycle, RetryPolicy
from runai.models import Race, StepKind
from tests.test_h_lifecycle import RetryRunner

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


# --- M4 ------------------------------------------------------------------------------------------

def _credit_runner(accounts=1, max_concurrency=1, quota_timeout_s=5.0):
    async def never(**params):
        pytest.fail("No session must be created")

    return HRunner(accounts=[HAccount(f"K{i}", client=SimpleNamespace(sessions=SimpleNamespace(create_session=never)),
                                      max_concurrency=max_concurrency) for i in range(accounts)],
                   quota_poll_s=0.01, quota_timeout_s=quota_timeout_s)


def test_m4_create_without_local_slot_honours_the_quota_deadline():
    async def scenario():
        runner = _credit_runner(quota_timeout_s=0.05)
        runner.accounts[0].active = 1  # every local slot is busy and never released
        with pytest.raises(HQuotaTimeout):
            await asyncio.wait_for(runner._create({}), 1)
    asyncio.run(scenario())


def test_m4_job_blocked_on_local_slot_fails_fast_when_credits_run_out():
    async def scenario():
        runner = _credit_runner()
        account = runner.accounts[0]
        account.active = 1
        job = HLifecycle(runner).submit(StepKind.search, "Find a race")
        await asyncio.sleep(0.05)
        assert not job.done
        account.max_concurrency = 0  # another job hit insufficient_credit and released its slot
        runner._release(account)
        with pytest.raises(HCreditsExhausted):
            await asyncio.wait_for(job.wait(), 1)
    asyncio.run(scenario())


def test_m4_credit_retries_try_every_account_beyond_max_attempts():
    async def scenario():
        runner = RetryRunner(["insufficient_credit", "insufficient_credit", None], accounts=3)
        job = HLifecycle(runner, retry_policy=RetryPolicy(max_attempts=2)).submit(StepKind.search, "Find a race")
        result = await asyncio.wait_for(job.wait(), 1)
        assert result.status.value == "completed"
        assert [call[2] for call in runner.calls] == ["K0", "K1", "K2"]
    asyncio.run(scenario())


def test_m4_credit_block_expires_after_ttl():
    async def scenario():
        runner = RetryRunner(["insufficient_credit", None])
        runner.credit_block_s = 0.05
        lifecycle = HLifecycle(runner)
        first = lifecycle.submit(StepKind.search, "Find a race")
        with pytest.raises(HCreditsExhausted):
            await asyncio.wait_for(first.wait(), 1)
        assert runner.accounts[0].max_concurrency == 0
        await asyncio.sleep(0.06)
        second = lifecycle.submit(StepKind.search, "Find a race")
        assert (await asyncio.wait_for(second.wait(), 1)).status.value == "completed"
        assert runner.accounts[0].max_concurrency == 3
    asyncio.run(scenario())
