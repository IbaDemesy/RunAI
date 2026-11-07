import asyncio
from types import SimpleNamespace

import pytest
from hai_agents.errors import ForbiddenError

from runai.h import HAccount, HRunner
from runai.h.lifecycle import (
    HAntiBotBlocked,
    HJobCancelled,
    HJobTimeout,
    HKeyMissing,
    HLifecycle,
    HQuotaSaturated,
    JobState,
)
from runai.models import StepKind, StepStatus


class SimulatedSessions:
    """Client H simulé : aucune session réelle, statuts pilotés par le test."""

    def __init__(self, limit=3, external_active=0, create_error=None):
        self.limit = limit
        self.external_active = external_active
        self.create_error = create_error
        self.status = {}
        self.answers = {}
        self.calls = []
        self.created = []

    def running(self):
        return [sid for sid, status in self.status.items() if status in ("pending", "running", "idle", "paused")]

    async def get_session_quota(self):
        active = self.external_active + len(self.running())
        return SimpleNamespace(scope="org", limit=self.limit, active=active, available=max(0, self.limit - active))

    async def create_session(self, **params):
        if self.create_error is not None:
            raise self.create_error
        self.created.append(params)
        sid = f"s{len(self.created)}"
        self.status[sid] = "running"
        return SimpleNamespace(id=sid, agent_view_url=None, status=SimpleNamespace(status="pending"))

    async def get_session_changes(self, session_id, from_index=0, include_events=True, wait_for_seconds=0):
        await asyncio.sleep(0.005)

    async def get_session_status(self, session_id):
        return SimpleNamespace(status=self.status[session_id], outcome=None, error=None, steps=1)

    async def get_session(self, session_id):
        return SimpleNamespace(id=session_id, latest_answer=self.answers.get(session_id), agent_view_url=None)

    async def pause_session(self, session_id):
        self.calls.append(("pause", session_id))
        self.status[session_id] = "paused"

    async def resume_session(self, session_id):
        self.calls.append(("resume", session_id))
        self.status[session_id] = "running"

    async def cancel_session(self, session_id):
        self.calls.append(("cancel", session_id))
        self.status[session_id] = "interrupted"


def make(tmp_path, *, max_concurrency=1, max_queue=4, quota_timeout_s=5.0, accounts=1, **fake):
    fakes = [SimulatedSessions(**fake) for _ in range(accounts)]
    runner = HRunner(
        accounts=[
            HAccount(f"K{i}", client=SimpleNamespace(sessions=f), max_concurrency=max_concurrency)
            for i, f in enumerate(fakes)
        ],
        quota_poll_s=0.01,
        quota_timeout_s=quota_timeout_s,
        traces_dir=tmp_path,
    )
    return HLifecycle(runner, max_queue=max_queue), fakes


async def until(predicate, timeout=2.0):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


def total_active(lifecycle):
    return sum(slot["active"] for slot in lifecycle.slots().values())


def test_bounded_queue_saturation_then_drain(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path, max_queue=1)
        first = lc.submit(StepKind.registration, "Inscription", mission_id="m1")
        await until(lambda: first.state is JobState.running)
        second = lc.submit(StepKind.accommodation, "Hôtel", mission_id="m1")
        await until(lambda: second.state is JobState.queued)
        with pytest.raises(HQuotaSaturated) as excinfo:
            lc.submit(StepKind.transport, "Train", mission_id="m1")
        assert excinfo.value.code == "h_quota_saturated"
        assert len(fake.created) == 1 and total_active(lc) == 1

        fake.status["s1"] = "completed"
        assert (await first.wait()).status is StepStatus.completed
        await until(lambda: second.state is JobState.running)
        fake.status["s2"] = "completed"
        await second.wait()
        assert total_active(lc) == 0
        assert [p["queue"] for p in fake.created] == [False, False]

    asyncio.run(scenario())


def test_real_quota_saturated_times_out_without_orphan_slot(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path, max_concurrency=3, quota_timeout_s=0.05, external_active=3)
        job = lc.submit(StepKind.search, "Recherche")
        with pytest.raises(HQuotaSaturated):
            await job.wait()
        assert job.state is JobState.failed
        assert fake.created == []
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_double_cancel_running_and_queued(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        running = lc.submit(StepKind.registration, "Inscription")
        await until(lambda: running.state is JobState.running)
        queued = lc.submit(StepKind.accommodation, "Hôtel")
        await until(lambda: queued.state is JobState.queued)

        for job in (queued, running, queued, running):
            await lc.cancel(job.job_id)
        assert running.state is queued.state is JobState.cancelled
        with pytest.raises(HJobCancelled):
            await running.wait()
        assert fake.calls.count(("cancel", "s1")) == 1
        assert len(fake.created) == 1  # l'étape annulée en file n'a jamais démarré
        await asyncio.sleep(0.05)
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_step_timeout_cancels_session_and_frees_slot(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        job = lc.submit(StepKind.transport, "Train", timeout_s=0.05)
        with pytest.raises(HJobTimeout):
            await job.wait()
        assert job.state is JobState.timed_out
        assert ("cancel", "s1") in fake.calls
        assert total_active(lc) == 0
        follow = lc.submit(StepKind.transport, "Train bis")
        await until(lambda: follow.state is JobState.running)
        await lc.cancel(follow.job_id)
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_idle_is_not_terminal_and_keeps_slot_until_finish(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        job = lc.submit(StepKind.registration, "Formulaire", idle_timeout_s=60)
        await until(lambda: job.state is JobState.running)
        fake.status["s1"] = "idle"
        assert await job.settled() is JobState.idle
        assert not job.done and total_active(lc) == 1
        await lc.finish(job.job_id)
        assert job.state is JobState.completed
        assert ("cancel", "s1") in fake.calls  # close() libère la session idle côté H
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_cancel_idle_session(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        job = lc.submit(StepKind.registration, "Formulaire", idle_timeout_s=60)
        await until(lambda: job.state is JobState.running)
        fake.status["s1"] = "idle"
        await job.settled()
        await lc.cancel(job.job_id)
        await lc.cancel(job.job_id)
        assert job.state is JobState.cancelled
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_targeted_pause_resume(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        job = lc.submit(StepKind.search, "Recherche")
        await until(lambda: job.state is JobState.running)
        await lc.pause(job.job_id)
        await lc.pause(job.job_id)
        assert job.state is JobState.paused and fake.calls.count(("pause", "s1")) == 1
        await lc.resume(job.job_id)
        await lc.resume(job.job_id)
        assert job.state is JobState.running and fake.calls.count(("resume", "s1")) == 1
        fake.status["s1"] = "completed"
        await job.wait()
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_job_paused_in_queue_does_not_take_a_slot(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        first = lc.submit(StepKind.search, "Recherche")
        second = lc.submit(StepKind.search, "Recherche 2")
        await lc.pause(second.job_id)
        await until(lambda: first.state is JobState.running)
        fake.status["s1"] = "completed"
        await first.wait()
        await asyncio.sleep(0.05)
        assert second.state is JobState.queued and len(fake.created) == 1
        await lc.resume(second.job_id)
        await until(lambda: second.state is JobState.running)
        await lc.cancel(second.job_id)
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_job_paused_while_waiting_for_slot_starts_paused(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        first = lc.submit(StepKind.search, "Recherche")
        await until(lambda: first.state is JobState.running)
        second = lc.submit(StepKind.search, "Recherche 2")
        await asyncio.sleep(0.05)  # second attend un slot dans HRunner.start
        await lc.pause(second.job_id)
        fake.status["s1"] = "completed"
        await first.wait()
        await until(lambda: second.state is JobState.paused)
        assert ("pause", "s2") in fake.calls
        await lc.cancel(second.job_id)
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_global_and_mission_controls(tmp_path):
    async def scenario():
        lc, fakes = make(tmp_path, accounts=2, max_concurrency=2)
        jobs = [lc.submit(StepKind.search, f"t{i}", mission_id=f"m{i % 2}") for i in range(4)]
        await until(lambda: all(j.state is JobState.running for j in jobs))
        assert lc.slots() == {"K0": {"active": 2, "max": 2}, "K1": {"active": 2, "max": 2}}

        await lc.pause_all("m0")
        assert [j.state for j in jobs] == [JobState.paused, JobState.running] * 2
        await lc.resume_all("m0")
        await lc.cancel_all("m1")
        assert [j.state for j in jobs] == [JobState.running, JobState.cancelled] * 2

        await lc.pause_all()
        late = lc.submit(StepKind.search, "tardif", mission_id="m2")
        await asyncio.sleep(0.05)
        assert late.state is JobState.queued and late.run is None
        await lc.resume_all()
        await until(lambda: late.state is JobState.running)
        assert all(j.state is JobState.running for j in jobs if j.mission_id == "m0")

        await lc.cancel_all()
        await lc.cancel_all()
        assert all(j.state is JobState.cancelled for j in lc.jobs.values())
        assert total_active(lc) == 0
        assert sum(len(f.running()) for f in fakes) == 0

    asyncio.run(scenario())


def test_anti_bot_reported_as_typed_error(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        job = lc.submit(StepKind.accommodation, "Hôtel")
        await until(lambda: job.state is JobState.running)
        fake.answers["s1"] = "BLOCAGE CAPTCHA/ANTI-BOT sur la page de réservation"
        fake.status["s1"] = "completed"
        with pytest.raises(HAntiBotBlocked) as excinfo:
            await job.wait()
        assert excinfo.value.code == "h_anti_bot" and excinfo.value.job_id == job.job_id
        assert job.result.status is StepStatus.failed
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_missing_key_from_env(monkeypatch):
    for name in ("HAI_API_KEY", "HAI_API_KEY_2", "HAI_API_KEY_3"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HKeyMissing) as excinfo:
        HLifecycle.from_env()
    assert excinfo.value.code == "h_key_missing"


def test_rejected_key_is_typed_and_frees_slot(tmp_path):
    async def scenario():
        lc, (_fake,) = make(tmp_path, create_error=ForbiddenError(body=None))
        job = lc.submit(StepKind.search, "Recherche")
        with pytest.raises(HKeyMissing):
            await job.wait()
        assert total_active(lc) == 0

    asyncio.run(scenario())


def test_queue_bound_validation(tmp_path):
    with pytest.raises(ValueError):
        HLifecycle(HRunner(SimpleNamespace(sessions=SimulatedSessions()), traces_dir=tmp_path), max_queue=-1)
