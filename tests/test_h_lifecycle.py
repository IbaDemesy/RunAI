import asyncio
from types import SimpleNamespace

import pytest
from hai_agents.errors import ForbiddenError

from runai.h import HAccount, HRunner
from runai.h.lifecycle import (
    HAntiBotBlocked,
    HCreditsExhausted,
    HJobCancelled,
    HJobTimeout,
    HKeyMissing,
    HLifecycle,
    HQuotaSaturated,
    JobState,
    RetryPolicy,
)
from runai.models import StepKind, StepResult, StepStatus


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


def test_lifecycle_retains_host_boundary_until_result(tmp_path):
    async def scenario():
        lc, (fake,) = make(tmp_path)
        job = lc.submit(StepKind.registration, "Prepare registration", allowed_hosts=("njuko.com",))
        await until(lambda: job.state is JobState.running)
        job.run._absorb({"type": "AgentEvent", "data": {"kind": "observation_event", "metadata": {"url": "https://evil.example/"}}})
        fake.answers["s1"] = "Stopped before payment"
        fake.status["s1"] = "completed"
        result = await job.wait()
        assert result.status is StepStatus.failed
        assert result.data["off_platform_hosts"] == ["evil.example"]
        assert "allowed_hosts" not in fake.created[0]

    asyncio.run(scenario())


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


class RetryRun:
    def __init__(self, account, *, code=None, outcome=None, progress=False, feedback_error=False):
        self.account = account
        self.id = "fake-session"
        self.error_code = code
        self.outcome = outcome
        self.status = "running"
        self.metrics = {"steps": 0}
        self.last_url = "https://example.test/search"
        self.messages = []
        self.forces = 0
        self.logs = []
        self.progress = progress
        self.feedback_error = feedback_error

    async def wait(self, **kwargs):
        if self.progress:
            for step in range(1, 9):
                self.metrics["steps"] = step
                await asyncio.sleep(0.005)
        self.status = "completed"
        return StepResult(kind=StepKind.search, status=StepStatus.failed if self.error_code else StepStatus.completed,
                          error=self.error_code)

    async def close(self):
        pass

    async def send_message(self, message):
        self.messages.append(message)

    async def force_answer(self):
        self.forces += 1

    def _log(self, *args):
        self.logs.append(args)


class RetryRunner:
    def __init__(self, codes, *, accounts=1, outcome=None, progress=False, feedback_error=False):
        self.feedback = []

        async def submit_session_feedback(id, *, success, message):
            self.feedback.append((id, success, message))
            if feedback_error:
                raise RuntimeError("Feedback unavailable")

        self.accounts = [HAccount(f"K{i}", client=SimpleNamespace(sessions=SimpleNamespace(
            submit_session_feedback=submit_session_feedback))) for i in range(accounts)]
        self.codes = iter(codes)
        self.outcome = outcome
        self.progress = progress
        self.calls = []
        self.runs = []

    async def start(self, kind, task, **params):
        account = next(a for a in self.accounts if a.has_local_slot)
        self.calls.append((task, params, account.name))
        run = RetryRun(account, code=next(self.codes), outcome=self.outcome, progress=self.progress)
        self.runs.append(run)
        return run


@pytest.mark.parametrize("code", ["environment_error", "internal", "no_answer", "answer_validation"])
def test_retry_recovery(code):
    async def scenario():
        runner = RetryRunner([code, None])
        job = HLifecycle(runner).submit(StepKind.search, "Find a race", max_steps=60, answer_schema={"type": "object"})
        result = await job.wait()
        assert result.status is StepStatus.completed
        assert job.attempts == result.data["attempts"] == 2
        assert result.data["retry_reasons"] == [code]
        assert len(runner.calls) == 2
        if code == "no_answer":
            assert runner.calls[1][1]["max_steps"] == 90
            assert runner.calls[1][0].endswith("Answer now with what you found so far.")
        elif code == "answer_validation":
            assert "answer_schema" not in runner.calls[1][1]
        else:
            assert runner.calls[0][:2] == runner.calls[1][:2]
    asyncio.run(scenario())


@pytest.mark.parametrize("accounts", [1, 2])
def test_credit_exhaustion(accounts):
    async def scenario():
        runner = RetryRunner(["insufficient_credit", None], accounts=accounts)
        job = HLifecycle(runner).submit(StepKind.search, "Find a race")
        if accounts == 1:
            with pytest.raises(HCreditsExhausted, match="No H account") as exc:
                await job.wait()
            assert exc.value.code == "h_insufficient_credit"
        else:
            assert (await job.wait()).status is StepStatus.completed
            assert [call[2] for call in runner.calls] == ["K0", "K1"]
        assert runner.accounts[0].max_concurrency == 0
    asyncio.run(scenario())


def test_credit_retry_waits_for_busy_healthy_account():
    async def scenario():
        runner = RetryRunner(["insufficient_credit", None], accounts=2)
        healthy = runner.accounts[1]
        healthy.active = healthy.max_concurrency
        original_start = runner.start
        waiting = asyncio.Event()

        async def start(*args, **kwargs):
            if runner.calls:
                waiting.set()
                while not healthy.has_local_slot:
                    await asyncio.sleep(0.001)
            return await original_start(*args, **kwargs)

        runner.start = start
        job = HLifecycle(runner).submit(StepKind.search, "Find a race")
        await asyncio.wait_for(waiting.wait(), 1)
        assert not job.done
        healthy.active = 0
        assert (await asyncio.wait_for(job.wait(), 1)).status is StepStatus.completed
        assert [call[2] for call in runner.calls] == ["K0", "K1"]
    asyncio.run(scenario())


def test_new_job_fails_fast_after_all_accounts_exhausted():
    async def scenario():
        runner = RetryRunner(["insufficient_credit"])
        lifecycle = HLifecycle(runner)
        first = lifecycle.submit(StepKind.search, "Find a race")
        with pytest.raises(HCreditsExhausted):
            await asyncio.wait_for(first.wait(), 1)

        async def start(*args, **kwargs):
            pytest.fail("Exhausted accounts must not reach runner.start")

        runner.start = start
        follow = lifecycle.submit(StepKind.search, "Find another race")
        with pytest.raises(HCreditsExhausted, match="All H accounts"):
            await asyncio.wait_for(follow.wait(), 1)
        assert follow.attempts == 0
        assert follow.state is JobState.failed
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["infeasible", "blocked"])
def test_non_retryable_outcomes(outcome):
    async def scenario():
        runner = RetryRunner(["environment_error"], outcome=outcome)
        job = HLifecycle(runner).submit(StepKind.search, "Find a race")
        if outcome == "blocked":
            with pytest.raises(HAntiBotBlocked):
                await job.wait()
        else:
            await job.wait()
        assert job.attempts == 1
    asyncio.run(scenario())


def test_watchdog_nudges_and_forces_once():
    async def scenario():
        runner = RetryRunner([None], progress=True)
        job = HLifecycle(runner, watchdog_interval_s=0.001).submit(StepKind.search, "Find a race", max_steps=10)
        result = await job.wait()
        run = runner.runs[0]
        assert len(run.messages) == run.forces == 1
        assert result.data["watchdog"] == ["stall_nudge", "force_answer_near_budget"]
        assert run.logs == [("control", name) for name in result.data["watchdog"]]
    asyncio.run(scenario())


@pytest.mark.parametrize("feedback_error", [False, True])
def test_feedback_once_and_best_effort(feedback_error):
    async def scenario():
        runner = RetryRunner([None], feedback_error=feedback_error)
        job = HLifecycle(runner).submit(StepKind.search, "Find a race")
        result = await job.wait()
        await asyncio.sleep(0)
        assert len(runner.feedback) == 1
        assert runner.feedback[0][1] is True
        assert result.data["watchdog"] == []
        assert result.data["retry_reasons"] == []
    asyncio.run(scenario())


def test_retry_policy_environment_and_limit(monkeypatch):
    monkeypatch.setenv("RUNAI_H_MAX_ATTEMPTS", "1")
    assert RetryPolicy().max_attempts == 1
    with pytest.raises(ValueError):
        RetryPolicy(0)

    async def scenario():
        runner = RetryRunner(["environment_error"])
        job = HLifecycle(runner).submit(StepKind.search, "Find a race")
        assert (await job.wait()).status is StepStatus.failed
        assert job.attempts == 1
    asyncio.run(scenario())
