"""W4 audit regressions: mission persistence, cancellation, H credits, closure errors, growth, leaks."""

import asyncio
import json
import time
from datetime import date
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runai.app.mission import MissionStatus
from runai.app.server import build_demo_service, create_app
from runai.app.tasks import TripBrief
from runai.contracts.framing import FramingSummary, FramingTurn
from runai.contracts.mission import HumanAnswer, QuestionStatus
from runai.framing.launch import LaunchPlan, StepPlan
from runai.h import HAccount, HQuotaTimeout, HRunner
from runai.h.lifecycle import HCreditsExhausted, HLifecycle, RetryPolicy
from runai.models import Race, StepKind, StepStatus
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


# --- M6 ------------------------------------------------------------------------------------------

async def _drive_until_terminal(service, mission, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not mission.is_terminal and asyncio.get_running_loop().time() < deadline:
        for question in [q for q in service.questions.questions.values()
                         if q.mission_id == mission.id and q.status is QuestionStatus.open]:
            service.answer_question(mission.id, question.question_id, HumanAnswer(
                answer=question.choices[0], revision=question.revision,
                idempotency_key=f"w4-{question.question_id}"))
        await asyncio.sleep(0.005)
    return await asyncio.wait_for(service.wait(mission.id), 1)


def test_m6_closure_error_fails_the_mission_and_closes_the_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))

    async def scenario():
        service = build_demo_service(delay=0)

        def broken(step, result):
            raise RuntimeError("merge exploded")

        monkeypatch.setattr(service, "_merge_result", broken)
        plan, summary = _plan()
        mission = await service.create(plan, summary=summary)
        events = []

        async def consume():
            async for event in service.subscribe_events(mission.id):
                events.append(event)

        consumer = asyncio.create_task(consume())
        await _drive_until_terminal(service, mission)
        await asyncio.wait_for(consumer, 2)
        assert mission.status is MissionStatus.failed
        assert mission.error and "merge exploded" not in mission.error
        assert all(step.status not in {StepStatus.running, StepStatus.paused, StepStatus.pending,
                                       StepStatus.waiting_for_user} for step in mission.steps.values())
        assert [event.payload["status"] for event in events if event.type == "mission_status"][-1] == "failed"
        assert any(event.type == "mission_outcome" for event in events)
        assert not service._runs
        stored = json.loads((tmp_path / "missions" / f"{mission.id}.json").read_text())
        assert stored["snapshot"]["status"] == "failed"

    asyncio.run(scenario())


# --- M2 ------------------------------------------------------------------------------------------

def test_m2_cancel_on_terminal_mission_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))

    async def scenario():
        service = build_demo_service(delay=0)
        plan, summary = _plan()
        mission = await service.create(plan, summary=summary)
        await _drive_until_terminal(service, mission)
        assert mission.status is MissionStatus.awaiting_human
        statuses = sum(event.type == "mission_status" for event in mission.envelopes)
        await service.cancel(mission.id)
        assert mission.status is MissionStatus.awaiting_human
        assert service.snapshot(mission.id).outcome.state == "prepared"
        assert sum(event.type == "mission_status" for event in mission.envelopes) == statuses

    asyncio.run(scenario())


def test_m2_cancel_running_mission_leaves_no_active_step(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))

    async def scenario():
        service = build_demo_service(delay=0)
        plan, summary = _plan()
        mission = await service.create(plan, summary=summary)
        for _ in range(200):
            if any(step.status is StepStatus.waiting_for_user for step in mission.steps.values()):
                break
            await asyncio.sleep(0.005)
        await service.cancel(mission.id)
        assert mission.status is MissionStatus.cancelled
        assert all(step.status not in {StepStatus.running, StepStatus.paused, StepStatus.pending,
                                       StepStatus.waiting_for_user} for step in mission.steps.values())

    asyncio.run(scenario())


# --- M9 ------------------------------------------------------------------------------------------

def test_m9_directory_fsync_is_posix_only_and_failures_are_explained(tmp_path, monkeypatch, caplog):
    import runai.app.store as store_module

    real_open = store_module.os.open

    def no_directory_open(path, flags, *args, **kwargs):
        if Path(path).is_dir():
            raise PermissionError("directories cannot be opened on this platform")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    monkeypatch.setattr(store_module.os, "open", no_directory_open)
    monkeypatch.setattr(store_module, "_POSIX", False)

    async def scenario():
        service = build_demo_service(delay=0)
        plan, summary = _plan()
        mission = await service.create(plan, summary=summary)
        await service.cancel(mission.id)
        return mission

    mission = asyncio.run(scenario())
    stored = json.loads((tmp_path / "missions" / f"{mission.id}.json").read_text())
    assert stored["snapshot"]["status"] == "cancelled"

    monkeypatch.setattr(store_module, "_POSIX", True)
    caplog.clear()
    with caplog.at_level("WARNING", logger="runai.app.store"):
        mission = asyncio.run(scenario())
    assert any("PermissionError" in record.getMessage() for record in caplog.records)


# --- M8 ------------------------------------------------------------------------------------------

def test_m8_step_end_releases_capture_runs_and_dedup_state(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))

    async def scenario():
        service = build_demo_service(delay=0)
        plan, summary = _plan()
        mission = await service.create(plan, summary=summary)
        service.capture_store._seen.add((mission.id, "transport", 1))
        service.capture_store._locks[(mission.id, "transport")] = asyncio.Lock()
        service._capture_runs[(mission.id, StepKind.transport)] = object()
        await _drive_until_terminal(service, mission)
        assert not [key for key in service._capture_runs if key[0] == mission.id]
        assert not [key for key in service.capture_store._seen if key[0] == mission.id]
        assert not [key for key in service.capture_store._locks if key[0] == mission.id]

    asyncio.run(scenario())


def test_m8_old_terminal_missions_are_pruned_from_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNAI_TRACES_DIR", str(tmp_path))
    monkeypatch.setenv("RUNAI_MISSION_TTL_S", "0")

    async def scenario():
        service = build_demo_service(delay=0)
        plan, summary = _plan()
        first = await service.create(plan, summary=summary)
        await service.cancel(first.id)
        second = await service.create(plan, summary=summary)
        assert first.id not in service.missions and second.id in service.missions
        assert not [key for key in service._recaps if key[0] == first.id]
        assert first.id not in service._writers
        assert (tmp_path / "missions" / f"{first.id}.json").exists()
        await service.cancel(second.id)

    asyncio.run(scenario())
