import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Self

from hai_agents import AsyncClient
from hai_agents.errors import TooManyRequestsError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from pydantic import HttpUrl, TypeAdapter, ValidationError

from runai.config import get_settings
from runai.h.events import answer_text, as_dict, to_trace_event
from runai.models import StepKind, StepResult, StepStatus, TraceEvent
from runai.safety import detect_stop_point, guard_task
from runai.tracing import TraceWriter

TERMINAL_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})
SETTLED_STATUSES = TERMINAL_STATUSES | {"idle"}

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

_HTTP_URL = TypeAdapter(HttpUrl)


class HQuotaTimeout(TimeoutError):
    """Aucun slot H libre dans le délai imparti."""


def _http_url(value: Any) -> HttpUrl | None:
    if not value:
        return None
    try:
        return _HTTP_URL.validate_python(value)
    except ValidationError:
        return None


def build_step_result(
    kind: StepKind,
    h_status: str,
    *,
    answer: Any = None,
    outcome: str | None = None,
    error: str | None = None,
    session_id: str | None = None,
    live_view_url: str | None = None,
    last_url: str | None = None,
    data: dict[str, Any] | None = None,
) -> StepResult:
    text = answer_text(answer)
    stop_point = None
    if h_status in ("completed", "idle"):
        stop_point = detect_stop_point(text or "")
        status = StepStatus.stopped_before_commitment if stop_point else StepStatus.completed
    elif h_status in ("failed", "timed_out"):
        status = StepStatus.failed
        error = error or h_status
    elif h_status == "interrupted":
        status = StepStatus.failed
        error = error or "interrupted"
    elif h_status == "paused":
        status = StepStatus.paused
    elif h_status in ("queued", "pending"):
        status = StepStatus.pending
    else:
        status = StepStatus.running
    return StepResult(
        kind=kind,
        status=status,
        summary=text,
        stop_point=stop_point,
        url=_http_url(last_url),
        live_view_url=_http_url(live_view_url),
        h_session_id=session_id,
        data={"h_status": h_status, "answer": answer, "outcome": outcome, **(data or {})},
        error=error,
    )


@dataclass
class HStep:
    kind: StepKind
    task: str
    start_url: str | None = None
    max_steps: int | None = None
    max_time_s: float | None = None
    options: dict[str, Any] = field(default_factory=dict)


class HRun:
    """Session H en cours : suivi des événements, contrôles et résultat final."""

    def __init__(
        self, runner: "HRunner", session: Any, kind: StepKind, trace: TraceWriter, interactive: bool = False
    ):
        self._runner = runner
        # Une session one-shot passe brièvement par `idle` avant `completed` : on attend l'état terminal.
        self._settled = SETTLED_STATUSES if interactive else TERMINAL_STATUSES
        self._sessions = runner.client.sessions
        self.id: str = session.id
        self.kind = kind
        self.trace = trace
        self.agent_view_url: str | None = getattr(session, "agent_view_url", None)
        self.live_view_url: str | None = None
        self.status: str = getattr(getattr(session, "status", None), "status", None) or "pending"
        self.answer: Any = None
        self.outcome: str | None = None
        self.error: str | None = None
        self.last_url: str | None = None
        self.last_title: str | None = None
        self.metrics: dict[str, Any] = {}
        self.event_count = 0
        self.result: StepResult | None = None
        self._cursor = 0
        self._released = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _log(self, type_: str, message: str | None = None, **data: Any) -> None:
        self.trace.write(
            TraceEvent(
                source="h",
                type=type_,
                message=message,
                data={"h_session_id": self.id, "step": self.kind.value, **data},
            )
        )

    def _absorb(self, event: dict[str, Any]) -> None:
        self.event_count += 1
        event_type = event.get("type")
        data = event.get("data") or {}
        if not isinstance(data, dict):
            return
        if event_type == "LiveViewUrlEvent" and data.get("live_view_url"):
            self.live_view_url = data["live_view_url"]
        elif event_type == "MetricsUpdateEvent" and isinstance(data.get("metrics"), dict):
            self.metrics = data["metrics"]
        elif event_type == "AgentRunStatusChangeEvent" and data.get("status"):
            self.status = data["status"]
        elif event_type == "AgentErrorEvent":
            self.error = data.get("error") or self.error
        elif event_type == "AgentEvent":
            kind = data.get("kind")
            if kind == "observation_event":
                metadata = data.get("metadata") or {}
                self.last_url = metadata.get("url") or self.last_url
                self.last_title = metadata.get("title") or self.last_title
            elif kind == "answer_event":
                self.answer = data.get("answer")
                self.outcome = data.get("outcome") or self.outcome

    async def refresh_status(self) -> str:
        status = await self._sessions.get_session_status(self.id)
        self.status = status.status
        self.outcome = getattr(status, "outcome", None) or self.outcome
        self.error = getattr(status, "error", None) or self.error
        if getattr(status, "steps", None) is not None:
            self.metrics.setdefault("steps", status.steps)
        return self.status

    async def wait_for_status(self, statuses: Iterable[str], timeout_s: float = 60.0, poll_s: float = 1.0) -> float:
        """Attend l'un des statuts et renvoie le délai observé en secondes."""
        wanted = set(statuses)
        started = time.monotonic()
        while await self.refresh_status() not in wanted:
            if time.monotonic() - started > timeout_s:
                raise TimeoutError(f"Session {self.id} n'a pas atteint {sorted(wanted)} en {timeout_s}s")
            await asyncio.sleep(poll_s)
        return time.monotonic() - started

    async def pause(self) -> None:
        await self._sessions.pause_session(self.id)
        self._log("control", "pause")

    async def resume(self) -> None:
        await self._sessions.resume_session(self.id)
        self._log("control", "resume")

    async def send_message(self, message: str) -> None:
        await self._sessions.send_session_messages(
            self.id, request=SendSessionMessagesRequestBody_UserMessage(message=message)
        )
        self._log("control", "message", text=message)

    async def force_answer(self) -> None:
        await self._sessions.force_session_answer(self.id)
        self._log("control", "force_answer")

    async def cancel(self) -> None:
        await self._sessions.cancel_session(self.id)
        self._log("control", "cancel")

    async def _follow(self, on_event: EventCallback | None, wait_for_seconds: int) -> None:
        caught_up = True
        while True:
            changes = await self._sessions.get_session_changes(
                self.id,
                from_index=self._cursor,
                include_events=True,
                wait_for_seconds=wait_for_seconds if caught_up else 0,
            )
            batch = list(getattr(changes, "new_events", None) or []) if changes is not None else []
            for raw in batch:
                event = as_dict(raw)
                self._absorb(event)
                self.trace.write(to_trace_event(event, self.id, self.kind.value))
                if on_event is not None:
                    outcome = on_event(event)
                    if inspect.isawaitable(outcome):
                        await outcome
            if changes is not None:
                first_index = getattr(changes, "first_index", None)
                self._cursor = (self._cursor if first_index is None else first_index) + len(batch)
                if getattr(changes, "answer", None) is not None:
                    self.answer = changes.answer
            caught_up = not batch
            if await self.refresh_status() in self._settled and not batch:
                return

    async def _finalize(self) -> StepResult:
        try:
            session = await self._sessions.get_session(self.id)
            if self.answer is None:
                self.answer = getattr(session, "latest_answer", None)
            self.agent_view_url = getattr(session, "agent_view_url", None) or self.agent_view_url
        except Exception as exc:  # noqa: BLE001 - le résultat reste exploitable sans ces champs
            self._log("warning", f"get_session a échoué : {exc}")
        return self._result()

    def _result(self, error: str | None = None) -> StepResult:
        return build_step_result(
            self.kind,
            self.status,
            answer=self.answer,
            outcome=self.outcome,
            error=error or self.error,
            session_id=self.id,
            live_view_url=self.live_view_url or self.agent_view_url,
            last_url=self.last_url,
            data={
                "agent_view_url": self.agent_view_url,
                "title": self.last_title,
                "steps": self.metrics.get("steps"),
                "total_cost": self.metrics.get("total_cost"),
                "events": self.event_count,
            },
        )

    async def wait(
        self,
        on_event: EventCallback | None = None,
        timeout_s: float | None = None,
        wait_for_seconds: int = 20,
    ) -> StepResult:
        """Suit la session jusqu'à son terme ; au-delà de `timeout_s`, l'annule pour libérer le slot."""
        try:
            await asyncio.wait_for(self._follow(on_event, wait_for_seconds), timeout_s)
            result = await self._finalize()
        except TimeoutError:
            await self._safe_cancel()
            self.status = "timed_out"
            result = self._result(error=f"timeout RunAI après {timeout_s}s")
        except Exception as exc:  # noqa: BLE001 - toute erreur de suivi devient un échec tracé
            await self._safe_cancel()
            result = self._result(error=f"{type(exc).__name__}: {exc}")
            result.status = StepStatus.failed
        finally:
            self._release()
        self.result = result
        self._log("result", result.status.value, result=result.model_dump(mode="json"))
        return result

    async def _safe_cancel(self) -> None:
        if self.status in TERMINAL_STATUSES:
            return
        try:
            await self.cancel()
        except Exception as exc:  # noqa: BLE001
            self._log("warning", f"annulation impossible : {exc}")

    async def close(self) -> None:
        """Annule la session si elle tourne encore et libère le slot local."""
        if self.result is None:
            await self._safe_cancel()
        self._release()

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self._runner._semaphore.release()


class HRunner:
    """Lance des étapes H gardées, sous une limite de sessions simultanées alignée sur le quota réel."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        agent: str | None = None,
        max_concurrency: int | None = None,
        quota_poll_s: float = 5.0,
        quota_timeout_s: float = 300.0,
        traces_dir=None,
    ):
        settings = get_settings()
        self._client = client
        self._owns_client = client is None
        self._api_key = settings.hai_api_key
        self.agent = agent or settings.h_agent
        self.max_concurrency = max_concurrency or settings.h_max_concurrency
        self.quota_poll_s = quota_poll_s
        self.quota_timeout_s = quota_timeout_s
        self.traces_dir = traces_dir
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = AsyncClient(api_key=self._api_key) if self._api_key else AsyncClient()
        return self._client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def quota(self) -> Any:
        return await self.client.sessions.get_session_quota()

    async def wait_for_slot(self, timeout_s: float | None = None) -> Any:
        """Attend qu'un slot H soit libre pour toute l'organisation (`available > 0`)."""
        timeout_s = self.quota_timeout_s if timeout_s is None else timeout_s
        deadline = time.monotonic() + timeout_s
        while True:
            quota = await self.quota()
            if quota.available > 0:
                return quota
            if time.monotonic() >= deadline:
                raise HQuotaTimeout(f"Aucun slot H libre ({quota.active}/{quota.limit}) après {timeout_s}s")
            await asyncio.sleep(self.quota_poll_s)

    async def start(
        self,
        kind: StepKind,
        task: str,
        *,
        trace: TraceWriter | None = None,
        mission_id: str | None = None,
        start_url: str | None = None,
        max_steps: int | None = None,
        max_time_s: float | None = None,
        **create_params: Any,
    ) -> HRun:
        """Crée la session sans file d'attente H (`queue=False`) : un slot local et un slot réel sont garantis."""
        params: dict[str, Any] = {"agent": self.agent, "messages": guard_task(task), "queue": False, **create_params}
        if max_steps is not None:
            params["max_steps"] = max_steps
        if max_time_s is not None:
            params["max_time_s"] = max_time_s
        if start_url:
            params.setdefault("overrides", {})["agent.environments[kind=web].start_url"] = start_url

        await self._semaphore.acquire()
        try:
            session = await self._create(params)
        except BaseException:
            self._semaphore.release()
            raise
        writer = trace or TraceWriter(mission_id or f"h-{session.id}", traces_dir=self.traces_dir)
        run = HRun(self, session, kind, writer, interactive=bool(params.get("idle_timeout_s")))
        run._log(
            "session_created",
            kind.value,
            agent=self.agent,
            task=task,
            agent_view_url=run.agent_view_url,
            max_steps=max_steps,
            max_time_s=max_time_s,
            start_url=start_url,
        )
        return run

    async def _create(self, params: dict[str, Any]) -> Any:
        deadline = time.monotonic() + self.quota_timeout_s
        while True:
            await self.wait_for_slot(max(0.0, deadline - time.monotonic()))
            try:
                return await self.client.sessions.create_session(**params)
            except TooManyRequestsError:
                if time.monotonic() >= deadline:
                    raise HQuotaTimeout(f"Quota H toujours plein après {self.quota_timeout_s}s") from None
                await asyncio.sleep(self.quota_poll_s)

    async def run(
        self,
        kind: StepKind,
        task: str,
        *,
        on_event: EventCallback | None = None,
        timeout_s: float | None = None,
        **start_params: Any,
    ) -> StepResult:
        run = await self.start(kind, task, **start_params)
        return await run.wait(on_event=on_event, timeout_s=timeout_s)

    async def run_many(self, steps: Iterable[HStep], *, mission_id: str | None = None, **run_params: Any) -> list[StepResult]:
        """Lance plusieurs étapes en parallèle ; une erreur de lancement devient un `StepResult` en échec."""
        steps = list(steps)
        trace = TraceWriter(mission_id, traces_dir=self.traces_dir) if mission_id else None

        async def one(step: HStep) -> StepResult:
            try:
                return await self.run(
                    step.kind,
                    step.task,
                    trace=trace,
                    start_url=step.start_url,
                    max_steps=step.max_steps,
                    max_time_s=step.max_time_s,
                    **step.options,
                    **run_params,
                )
            except Exception as exc:  # noqa: BLE001 - une étape en échec ne bloque pas les autres
                return StepResult(kind=step.kind, status=StepStatus.failed, error=f"{type(exc).__name__}: {exc}")

        return list(await asyncio.gather(*(one(step) for step in steps)))
