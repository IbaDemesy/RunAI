"""Cycle de vie des sessions H au-dessus de `HRunner` : file bornée, contrôles ciblés/globaux, erreurs typées.

Le module enveloppe `runai.h.runner` sans le modifier. Les slots locaux sont ceux de `HAccount.active` ;
chaque chemin (fin, échec, timeout, annulation en file ou en cours) passe par `HRun.close()` ou par la
libération interne de `HRunner`, si bien qu'aucun slot ne reste orphelin.

`idle` n'est pas un état terminal : une session interactive arrêtée sur `idle` garde son slot jusqu'à
`finish()` ou `cancel()`.
"""

import asyncio
import contextlib
import itertools
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


class HLifecycleError(RuntimeError):
    """Erreur typée du cycle de vie H ; `code` est stable pour l'API et l'UI."""

    code = "h_error"

    def __init__(self, message: str, *, job_id: str | None = None):
        super().__init__(redact_secrets(message))
        self.job_id = job_id


class HKeyMissing(HLifecycleError):
    """Aucune clé H configurée, ou clé refusée par H (401/403)."""

    code = "h_key_missing"


class HQuotaSaturated(HLifecycleError):
    """File locale pleine ou aucun slot H libéré dans le délai."""

    code = "h_quota_saturated"


class HAntiBotBlocked(HLifecycleError):
    """L'agent H a signalé un captcha ou une protection anti-bot : jamais contournée, reprise manuelle."""

    code = "h_anti_bot"


class HJobCancelled(HLifecycleError):
    code = "h_cancelled"


class HJobTimeout(HLifecycleError):
    code = "h_timeout"


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
    """Une étape H suivie par le cycle de vie (en file, en cours, au repos ou finie)."""

    job_id: str
    kind: StepKind
    mission_id: str | None
    state: JobState = JobState.queued
    run: HRun | None = None
    result: StepResult | None = None
    error: HLifecycleError | None = None
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
        """Attend l'état final ; lève l'erreur typée si l'étape n'a pas abouti normalement."""
        await self._done.wait()
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def settled(self) -> JobState:
        """Attend `idle` ou un état final (sans libérer le slot d'une session `idle`)."""
        while self.state not in FINAL_STATES | {JobState.idle}:
            await asyncio.sleep(0.01)
        return self.state


def _is_auth_error(exc: BaseException) -> bool:
    return isinstance(exc, ApiError) and getattr(exc, "status_code", None) in (401, 403)


class HLifecycle:
    """Pilote des `HJob` sur un `HRunner` existant.

    `max_queue` borne le nombre d'étapes en attente d'un slot (au-delà : `HQuotaSaturated`).
    `queue_timeout_s` borne l'attente d'un slot ; `timeout_s` (par étape) annule une session trop longue.
    """

    def __init__(self, runner: HRunner, *, max_queue: int = 6, queue_timeout_s: float | None = None):
        if max_queue < 0:
            raise ValueError("max_queue doit être positif")
        self.runner = runner
        self.max_queue = max_queue
        if queue_timeout_s is not None:
            runner.quota_timeout_s = queue_timeout_s
        self.jobs: dict[str, HJob] = {}
        self._ids = itertools.count(1)
        self._paused_all = asyncio.Event()
        self._paused_all.set()  # set = pas de pause globale

    @classmethod
    def from_env(cls, **kwargs: Any) -> "HLifecycle":
        """Construit le runner depuis `HAI_API_KEY[_N]` ; sans clé, `HKeyMissing` plutôt qu'un faux live."""
        keys = api_keys_from_env()
        if not keys:
            raise HKeyMissing("Aucune clé H configurée (HAI_API_KEY) : le mode live H est indisponible.")
        runner_kwargs = {k: kwargs.pop(k) for k in ("agent", "max_concurrency", "traces_dir") if k in kwargs}
        return cls(HRunner(**runner_kwargs), **kwargs)

    # --- état ---------------------------------------------------------------------------------

    def queued(self) -> list[HJob]:
        return [job for job in self.jobs.values() if job.state is JobState.queued]

    def active(self, mission_id: str | None = None) -> list[HJob]:
        return [job for job in self._select(mission_id) if not job.done]

    def slots(self) -> dict[str, dict[str, int]]:
        """Slots locaux occupés par clé H (noms de clés seulement)."""
        return {a.name: {"active": a.active, "max": a.max_concurrency} for a in self.runner.accounts}

    def get(self, job_id: str) -> HJob:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise KeyError(f"Étape H inconnue : {job_id}") from None

    def _select(self, mission_id: str | None) -> list[HJob]:
        return [job for job in self.jobs.values() if mission_id is None or job.mission_id == mission_id]

    # --- lancement ----------------------------------------------------------------------------

    def submit(
        self,
        kind: StepKind,
        task: str,
        *,
        mission_id: str | None = None,
        timeout_s: float | None = None,
        **start_params: Any,
    ) -> HJob:
        """Met l'étape en file et la lance dès qu'un slot H est libre (à appeler dans une boucle asyncio).

        Une étape mise en pause avant d'obtenir un slot n'en consomme pas ; si la pause arrive pendant
        l'attente du slot, la session démarre puis est mise en pause aussitôt.
        """
        if len(self.queued()) >= self.max_queue:
            raise HQuotaSaturated(
                f"File H pleine ({self.max_queue} étapes en attente) : réessayer après libération d'un slot."
            )
        job = HJob(job_id=f"hjob-{next(self._ids)}", kind=kind, mission_id=mission_id)
        job._resume.set()
        self.jobs[job.job_id] = job
        job._task = asyncio.create_task(self._drive(job, task, timeout_s, start_params))
        return job

    async def _drive(self, job: HJob, task: str, timeout_s: float | None, start_params: dict[str, Any]) -> None:
        run: HRun | None = None
        try:
            await self._paused_all.wait()
            await job._resume.wait()
            try:
                run = await self.runner.start(job.kind, task, mission_id=job.mission_id, **start_params)
            except HQuotaTimeout as exc:
                raise HQuotaSaturated(str(exc), job_id=job.job_id) from exc
            job.run = run
            if job._cancel_requested:
                raise asyncio.CancelledError
            job.state = JobState.paused if not job._resume.is_set() else JobState.running
            if job.state is JobState.paused:
                await run.pause()
            result = await run.wait(timeout_s=timeout_s)
            job.result = result
            if run.status == "idle":
                job.state = JobState.idle
                await job._finish.wait()
            self._conclude(job, run, result)
        except asyncio.CancelledError:
            job.state = JobState.cancelled
            job.error = HJobCancelled("Étape H annulée.", job_id=job.job_id)
        except HLifecycleError as exc:
            exc.job_id = exc.job_id or job.job_id
            job.state = JobState.failed
            job.error = exc
        except Exception as exc:  # noqa: BLE001 - toute erreur de lancement devient une erreur typée
            job.state = JobState.failed
            if _is_auth_error(exc):
                job.error = HKeyMissing(f"Clé H refusée ({exc.status_code}).", job_id=job.job_id)
            else:
                job.error = HLifecycleError(f"{type(exc).__name__}: {exc}", job_id=job.job_id)
        finally:
            if run is not None:
                with contextlib.suppress(Exception):
                    await asyncio.shield(run.close())
            job._done.set()

    def _conclude(self, job: HJob, run: HRun, result: StepResult) -> None:
        if run.status == "timed_out" and job.state is not JobState.idle:
            job.state = JobState.timed_out
            job.error = HJobTimeout(result.error or "timeout", job_id=job.job_id)
        elif result.status is StepStatus.failed and _ANTI_BOT_ERROR in (result.error or "").lower():
            job.state = JobState.failed
            job.error = HAntiBotBlocked(
                "Captcha/anti-bot signalé : non contourné, reprise manuelle sur le site officiel.",
                job_id=job.job_id,
            )
        elif result.status is StepStatus.failed:
            job.state = JobState.failed
        else:
            job.state = JobState.completed

    # --- contrôles ciblés ---------------------------------------------------------------------

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
        """Clôt une session `idle` (libère son slot) ; sans effet sur les autres états."""
        job = self.get(job_id)
        job._finish.set()
        if job._task is not None and job.state is JobState.idle:
            await asyncio.shield(job._task)
        return job

    async def cancel(self, job_id: str) -> HJob:
        """Annule l'étape (en file, en cours, en pause ou idle) ; idempotent."""
        job = self.get(job_id)
        if job.done or job._task is None:
            return job
        job._cancel_requested = True
        job._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(job._task)
        if not job.done:  # tâche annulée avant même d'avoir démarré
            job.state = JobState.cancelled
            job.error = HJobCancelled("Étape H annulée.", job_id=job.job_id)
            job._done.set()
        return job

    # --- contrôles globaux (ou par mission) ---------------------------------------------------

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
