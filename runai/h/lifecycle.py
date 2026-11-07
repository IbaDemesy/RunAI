"""Bounded H session lifecycle with targeted/global controls and typed errors.

Every exit closes the run or relies on the runner's internal slot release.
Idle sessions retain their slot until finish() or cancel().
"""

import asyncio
import contextlib
import inspect
import itertools
import logging
import math
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Self

from hai_agents.core.api_error import ApiError

from runai.h.runner import (
    TERMINAL_STATUSES,
    HQuotaTimeout,
    HRun,
    HRunner,
    api_keys_from_env,
)
from runai.models import StepKind, StepResult, StepStatus
from runai.redaction import redact_secrets

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = field(default_factory=lambda: int(os.getenv("RUNAI_H_MAX_ATTEMPTS", "2")))

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


class HLifecycleError(RuntimeError):
    """Typed lifecycle error with a stable API/UI code."""

    code = "h_error"

    def __init__(self, message: str, *, job_id: str | None = None):
        super().__init__(redact_secrets(message))
        self.job_id = job_id


class HKeyMissing(HLifecycleError):
    """No H key configured, or H rejected the key (401/403)."""

    code = "h_key_missing"


class HQuotaSaturated(HLifecycleError):
    """The local queue is full or no H slot became available in time."""

    code = "h_quota_saturated"


class HAntiBotBlocked(HLifecycleError):
    """H reported an anti-bot challenge requiring manual intervention."""

    code = "h_anti_bot"


class HJobCancelled(HLifecycleError):
    code = "h_cancelled"


class HJobTimeout(HLifecycleError):
    code = "h_timeout"


class HCreditsExhausted(HLifecycleError):
    code = "h_insufficient_credit"


class JobState(str, Enum):
    queued = "queued"
    running = "running"
    paused = "paused"
    idle = "idle"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"


FINAL_STATES = frozenset({JobState.completed, JobState.failed, JobState.cancelled, JobState.timed_out})
_ANTI_BOT_ERROR = "captcha/anti-bot"


@dataclass
class HJob:
    """An H step tracked through queued, running, idle, and final states."""

    job_id: str
    kind: StepKind
    mission_id: str | None
    state: JobState = JobState.queued
    run: HRun | None = None
    result: StepResult | None = None
    error: HLifecycleError | None = None
    attempts: int = 0
    retry_reasons: list[str] = field(default_factory=list)
    watchdog: list[str] = field(default_factory=list)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _resume: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _finish: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _cancel_requested: bool = field(default=False, repr=False)
    _timeout_hit: bool = field(default=False, repr=False)

    @property
    def done(self) -> bool:
        return self.state in FINAL_STATES

    @property
    def h_session_id(self) -> str | None:
        return self.run.id if self.run is not None else None

    async def wait(self) -> StepResult:
        """Wait for completion, raising a typed error for abnormal termination."""
        await self._done.wait()
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def settled(self) -> JobState:
        """Wait for idle or a final state without releasing an idle session's slot."""
        while self.state not in FINAL_STATES | {JobState.idle}:
            await asyncio.sleep(0.01)
        return self.state


def _is_auth_error(exc: BaseException) -> bool:
    return isinstance(exc, ApiError) and getattr(exc, "status_code", None) in (401, 403)


class HLifecycle:
    """Drive H jobs with bounded queue length, slot waits, and session duration."""

    def __init__(self, runner: HRunner, *, max_queue: int = 6, queue_timeout_s: float | None = None,
                 retry_policy: RetryPolicy | None = None, watchdog_interval_s: float = 15):
        if max_queue < 0:
            raise ValueError("max_queue must be nonnegative")
        self.runner = runner
        self.retry_policy = retry_policy or RetryPolicy()
        if watchdog_interval_s <= 0:
            raise ValueError("watchdog_interval_s must be positive")
        self.watchdog_interval_s = watchdog_interval_s
        self._feedback_tasks: set[asyncio.Task] = set()
        self.max_queue = max_queue
        if queue_timeout_s is not None:
            runner.quota_timeout_s = queue_timeout_s
        self.jobs: dict[str, HJob] = {}
        self._ids = itertools.count(1)
        self._paused_all = asyncio.Event()
        self._paused_all.set()  # Set means globally resumed.

    @classmethod
    def from_env(cls, **kwargs: Any) -> "HLifecycle":
        """Build from HAI_API_KEY[_N], raising HKeyMissing rather than pretending to be live."""
        keys = api_keys_from_env()
        if not keys:
            raise HKeyMissing("No H key configured (HAI_API_KEY): live H mode is unavailable.")
        runner_kwargs = {k: kwargs.pop(k) for k in ("agent", "max_concurrency", "traces_dir") if k in kwargs}
        return cls(HRunner(**runner_kwargs), **kwargs)

    # --- state --------------------------------------------------------------------------------

    def queued(self) -> list[HJob]:
        return [job for job in self.jobs.values() if job.state is JobState.queued]

    def active(self, mission_id: str | None = None) -> list[HJob]:
        return [job for job in self._select(mission_id) if not job.done]

    def slots(self) -> dict[str, dict[str, int]]:
        """Local slots per H key (key names only)."""
        return {a.name: {"active": a.active, "max": a.max_concurrency} for a in self.runner.accounts}

    def get(self, job_id: str) -> HJob:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise KeyError(f"Unknown H step: {job_id}") from None

    def _select(self, mission_id: str | None) -> list[HJob]:
        return [job for job in self.jobs.values() if mission_id is None or job.mission_id == mission_id]

    # --- submission ---------------------------------------------------------------------------

    def submit(
        self,
        kind: StepKind,
        task: str,
        *,
        mission_id: str | None = None,
        timeout_s: float | None = None,
        **start_params: Any,
    ) -> HJob:
        """Queue a step inside an asyncio loop and start when an H slot becomes available.

        Paused queued jobs take no slot; jobs paused during slot acquisition pause immediately on start.
        """
        if len(self.queued()) >= self.max_queue:
            raise HQuotaSaturated(
                f"H queue full ({self.max_queue} steps waiting): retry when a slot becomes available."
            )
        job = HJob(job_id=f"hjob-{next(self._ids)}", kind=kind, mission_id=mission_id)
        job._resume.set()
        self.jobs[job.job_id] = job
        job._task = asyncio.create_task(self._drive(job, task, timeout_s, start_params))
        return job

    async def _drive(self, job: HJob, task: str, timeout_s: float | None, start_params: dict[str, Any]) -> None:
        run: HRun | None = None
        result_wrapper = start_params.pop("result_wrapper", None)
        try:
            for attempt in range(self.retry_policy.max_attempts):
                await self._paused_all.wait()
                await job._resume.wait()
                accounts = getattr(self.runner, "accounts", [])
                if accounts and all(a.max_concurrency == 0 for a in accounts):
                    raise HCreditsExhausted("All H accounts have exhausted their credits.")
                try:
                    run = await self.runner.start(job.kind, task, mission_id=job.mission_id, **start_params)
                except HQuotaTimeout as exc:
                    raise HQuotaSaturated(str(exc), job_id=job.job_id) from exc
                job.attempts += 1
                job.run = run
                if job._cancel_requested:
                    raise asyncio.CancelledError
                job.state = JobState.paused if not job._resume.is_set() else JobState.running
                if job.state is JobState.paused:
                    await run.pause()
                monitor = asyncio.create_task(self._watchdog(job, run, start_params, timeout_s))
                try:
                    result = await result_wrapper(run).wait() if result_wrapper else await run.wait(timeout_s=timeout_s)
                finally:
                    monitor.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await monitor
                job.result = result
                outcome = getattr(run, "outcome", None)
                if outcome == "blocked":
                    raise HAntiBotBlocked("The agent is blocked; manual intervention is required.")
                code = getattr(run, "error_code", None)
                if not code:
                    code = next((name for name in ("environment_error", "no_answer", "answer_validation",
                                                  "timeout", "insufficient_credit", "internal")
                                 if name in (result.error or "").lower()), None)
                if code == "insufficient_credit":
                    account = getattr(run, "account", None)
                    if account is not None:
                        account.max_concurrency = 0
                        logger.warning("H credits exhausted for account %s", account.name)
                    if outcome != "infeasible" and not any(a.max_concurrency > 0 for a in self.runner.accounts):
                        raise HCreditsExhausted("No H account with credits has an available slot.")
                if (outcome == "infeasible" or attempt + 1 >= self.retry_policy.max_attempts
                        or code not in {"environment_error", "internal", "no_answer", "answer_validation",
                                        "insufficient_credit"}):
                    break
                job.retry_reasons.append(code)
                await run.close()
                run = None
                if code == "no_answer":
                    start_params["max_steps"] = min(90, math.ceil((start_params.get("max_steps") or 60) * 1.5))
                    task += "\nAnswer now with what you found so far."
                elif code == "answer_validation":
                    start_params.pop("answer_schema", None)
            if run.status == "idle" and result_wrapper is None:
                job.state = JobState.idle
                await job._finish.wait()
            self._conclude(job, run, result)
        except asyncio.CancelledError:
            job.state = JobState.cancelled
            job.error = HJobCancelled("H step cancelled.", job_id=job.job_id)
        except HLifecycleError as exc:
            exc.job_id = exc.job_id or job.job_id
            job.state = JobState.failed
            job.error = exc
        except Exception as exc:  # noqa: BLE001 - Normalize all startup errors.
            job.state = JobState.failed
            if _is_auth_error(exc):
                job.error = HKeyMissing(f"H key rejected ({exc.status_code}).", job_id=job.job_id)
            else:
                job.error = HLifecycleError(f"{type(exc).__name__}: {exc}", job_id=job.job_id)
        finally:
            if run is not None:
                with contextlib.suppress(Exception):
                    await asyncio.shield(run.close())
            if job.result is not None:
                job.result.data.update(attempts=job.attempts, retry_reasons=job.retry_reasons, watchdog=job.watchdog)
            if run is not None and job.state is not JobState.cancelled:
                feedback = asyncio.create_task(self._feedback(job, run))
                self._feedback_tasks.add(feedback)
                feedback.add_done_callback(self._feedback_tasks.discard)
            job._done.set()

    async def _feedback(self, job: HJob, run: HRun) -> None:
        try:
            sessions = run.account.client.sessions
            submit = getattr(sessions, "submit_session_feedback", None)
            if submit is None:
                return
            success = bool(job.result and job.result.status in {
                StepStatus.stopped_before_commitment, StepStatus.completed,
            })
            params = {"success": success, "message": f"RunAI job {job.state.value}."}
            inspect.signature(submit).bind(run.id, **params)
            await submit(run.id, **params)
        except Exception:  # noqa: BLE001 - Feedback must never affect a job's result.
            logger.debug("H session feedback was unavailable")

    async def _watchdog(self, job: HJob, run: HRun, params: dict[str, Any], timeout_s: float | None) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_url = getattr(run, "last_url", None)
        same_since = (getattr(run, "metrics", None) or {}).get("steps") or getattr(run, "event_count", 0)
        while True:
            await asyncio.sleep(self.watchdog_interval_s)
            if getattr(run, "status", "running") not in {"running", "pending"}:
                continue
            steps = (getattr(run, "metrics", None) or {}).get("steps")
            observed = steps if steps is not None else getattr(run, "event_count", 0)
            url = getattr(run, "last_url", None)
            if url != last_url or observed < same_since:
                last_url, same_since = url, observed
            action = None
            if ("force_answer_near_budget" not in job.watchdog
                    and ((steps is not None and params.get("max_steps")
                          and steps >= 0.8 * params["max_steps"])
                         or (timeout_s is not None and loop.time() - started >= 0.85 * timeout_s))
                    and callable(getattr(run, "force_answer", None))):
                action = "force_answer_near_budget"
                method = run.force_answer
            elif ("stall_nudge" not in job.watchdog and observed - same_since >= 6
                  and callable(getattr(run, "send_message", None))):
                action = "stall_nudge"
                async def method():
                    await run.send_message("You seem stuck on the same page: close any modal or cookie banner, "
                                           "then go back to the search form and continue.")
            if action:
                job.watchdog.append(action)
                log = getattr(run, "_log", None)
                if callable(log):
                    log("control", action)
                with contextlib.suppress(Exception):
                    await method()

    def _conclude(self, job: HJob, run: HRun, result: StepResult) -> None:
        if run.status == "timed_out" and job.state is not JobState.idle:
            job.state = JobState.timed_out
            job.error = HJobTimeout(result.error or "timeout", job_id=job.job_id)
        elif result.status is StepStatus.failed and _ANTI_BOT_ERROR in (result.error or "").lower():
            job.state = JobState.failed
            job.error = HAntiBotBlocked(
                "Captcha/anti-bot reported: not bypassed; resume manually on the official site.",
                job_id=job.job_id,
            )
        elif result.status is StepStatus.failed:
            job.state = JobState.failed
        else:
            job.state = JobState.completed

    # --- targeted controls --------------------------------------------------------------------

    async def pause(self, job_id: str) -> HJob:
        job = self.get(job_id)
        if job.done or job.state in (JobState.paused, JobState.idle):
            return job
        job._resume.clear()
        if job.run is not None and job.run.status not in TERMINAL_STATUSES:
            await job.run.pause()
            job.state = JobState.paused
        return job

    async def resume(self, job_id: str) -> HJob:
        job = self.get(job_id)
        if job.done or job._resume.is_set():
            return job
        job._resume.set()
        if job.run is not None and job.state is JobState.paused:
            await job.run.resume()
            job.state = JobState.running
        return job

    async def finish(self, job_id: str) -> HJob:
        """Close an idle session and release its slot; other states are unchanged."""
        job = self.get(job_id)
        job._finish.set()
        if job._task is not None and job.state is JobState.idle:
            await asyncio.shield(job._task)
        return job

    async def cancel(self, job_id: str) -> HJob:
        """Cancel a queued, running, paused, or idle step idempotently."""
        job = self.get(job_id)
        if job.done or job._task is None:
            return job
        job._cancel_requested = True
        job._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(job._task)
        if not job.done:  # Task cancelled before it started.
            job.state = JobState.cancelled
            job.error = HJobCancelled("H step cancelled.", job_id=job.job_id)
            job._done.set()
        return job

    # --- global or mission controls -----------------------------------------------------------

    async def pause_all(self, mission_id: str | None = None) -> list[HJob]:
        if mission_id is None:
            self._paused_all.clear()
        return list(await asyncio.gather(*(self.pause(j.job_id) for j in self.active(mission_id))))

    async def resume_all(self, mission_id: str | None = None) -> list[HJob]:
        if mission_id is None:
            self._paused_all.set()
        return list(await asyncio.gather(*(self.resume(j.job_id) for j in self.active(mission_id))))

    async def cancel_all(self, mission_id: str | None = None) -> list[HJob]:
        return list(await asyncio.gather(*(self.cancel(j.job_id) for j in self.active(mission_id))))

    async def aclose(self) -> None:
        await self.cancel_all()
        await self.runner.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
