import asyncio
import contextlib
import inspect
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from hai_agents import AsyncClient
from hai_agents.errors import TooManyRequestsError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.tools import Tool, ToolInput, as_tools
from pydantic import HttpUrl, TypeAdapter, ValidationError

from runai.app.providers import FORBIDDEN_HOSTS, host_matches
from runai.config import get_settings
from runai.h.events import answer_text, as_dict, safe_text, to_trace_event
from runai.models import StepKind, StepResult, StepStatus, StopPoint, TraceEvent
from runai.safety import detect_stop_point, guard_task
from runai.tracing import TraceWriter

TERMINAL_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})
SETTLED_STATUSES = TERMINAL_STATUSES | {"idle"}

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

_HTTP_URL = TypeAdapter(HttpUrl)
_ANTI_BOT_BLOCK = re.compile(r"\b(?:BLOCAGE CAPTCHA/ANTI-BOT|BLOCKED: CAPTCHA/ANTI-BOT)\b", re.IGNORECASE)
_PAYMENT_PROCESSOR_HOSTS = (
    "stripe.com", "adyen.com", "paypal.com", "checkout.com",
    "ingenico.com", "ingenico.fr", "worldline.com", "worldline-solutions.com",
    "mollie.com",
    "paybox.com", "paybox.fr", "payline.com", "payline.fr",
    "sumup.com", "sumup.me", "klarna.com", "lyra.com", "lyra-network.com",
    "monext.com", "monext.fr",
)

_FORBIDDEN_RUN_HOSTS = (*FORBIDDEN_HOSTS, "tap.pt", "trainline.com", "thetrainline.com")


def _event_page_urls(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"url", "current_url", "final_url"} and isinstance(item, str):
                yield item
            elif key not in {"image", "images"}:
                yield from _event_page_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _event_page_urls(item)


RESERVED_CREATE_PARAMS = frozenset({"agent", "messages", "queue"})

_STOP_SCREENS = {
    "payment": StopPoint.payment,
    "account": StopPoint.account_creation,
    "health": StopPoint.health_declaration,
    "consent": StopPoint.consent,
    "submission": StopPoint.submission,
}


class HQuotaTimeout(TimeoutError):
    """No free H slot before the deadline."""


def api_keys_from_env() -> list[tuple[str, str]]:
    """Available H keys: `HAI_API_KEY`, then `HAI_API_KEY_2`, `HAI_API_KEY_3`… (return names, never log values)."""
    names = ["HAI_API_KEY"]
    index = 2
    while os.getenv(f"HAI_API_KEY_{index}"):
        names.append(f"HAI_API_KEY_{index}")
        index += 1
    return [(name, os.environ[name]) for name in names if os.getenv(name)]


class HAccount:
    """An H key (one H organization): its client, local cap and active sessions."""

    def __init__(
        self,
        name: str,
        *,
        client: Any | None = None,
        api_key: str | None = None,
        max_concurrency: int = 3,
    ):
        self.name = name
        self._client = client
        self._owns_client = client is None
        self._api_key = api_key
        self.max_concurrency = max_concurrency
        self.active = 0

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = AsyncClient(api_key=self._api_key) if self._api_key else AsyncClient()
        return self._client

    @property
    def has_local_slot(self) -> bool:
        return self.active < self.max_concurrency

    async def quota(self) -> Any:
        return await self.client.sessions.get_session_quota()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


def _http_url(value: Any) -> HttpUrl | None:
    if not value:
        return None
    try:
        original = urlsplit(str(value))
        if original.username is not None or original.password is not None:
            return None
        url = _HTTP_URL.validate_python(value)
        if url.username is not None or url.password is not None:
            return None
        return url
    except (ValidationError, ValueError):
        return None


def build_step_result(
    kind: StepKind,
    h_status: str,
    *,
    answer: Any = None,
    outcome: str | None = None,
    error: str | None = None,
    error_code: str | None = None,
    session_id: str | None = None,
    live_view_url: str | None = None,
    agent_view_url: str | None = None,
    last_url: str | None = None,
    off_platform: bool = False,
    payment_processor: bool = False,
    off_platform_hosts: Iterable[str] = (),
    data: dict[str, Any] | None = None,
) -> StepResult:
    text = answer_text(answer)
    stop_point = None
    result_data = {"h_status": h_status, "answer": answer, **(data or {}), "outcome": outcome, "error_code": error_code}
    typed_answer = answer if isinstance(answer, dict) else {}
    screen = typed_answer.get("stop_screen")
    price = typed_answer.get("total_price")
    if not isinstance(price, int | float) or isinstance(price, bool):
        price = None
    if price is not None:
        result_data["price_eur"] = price
    if outcome == "partial":
        result_data["partial"] = True
    if outcome == "blocked":
        status = StepStatus.failed
        error = "Blocked by the site (captcha/anti-bot or login wall)"
    elif outcome == "infeasible":
        status = StepStatus.failed
        error = f"The agent judged the task infeasible: {(text or '')[:200]}"
        result_data["retryable"] = False
    elif h_status in ("completed", "idle"):
        if _ANTI_BOT_BLOCK.search(text or ""):
            status = StepStatus.failed
            error = error or "Captcha/anti-bot block reported by the agent."
        else:
            if screen in _STOP_SCREENS or screen == "none":
                stop_point = _STOP_SCREENS.get(screen)
            else:
                stop_point = detect_stop_point(text or "", ignore_negated=True)
            status = StepStatus.stopped_before_commitment if stop_point else StepStatus.completed
    elif h_status in ("failed", "timed_out"):
        status = StepStatus.failed
        error = error or error_code or h_status
    elif h_status == "interrupted":
        status = StepStatus.failed
        error = error or "interrupted"
    elif h_status == "paused":
        status = StepStatus.paused
    elif h_status in ("queued", "pending"):
        status = StepStatus.pending
    else:
        status = StepStatus.running
    untrusted_hosts = list(off_platform_hosts)
    if off_platform or payment_processor:
        status = StepStatus.failed
        stop_point = None
        host = ", ".join(untrusted_hosts) or "unknown host"
        error = error or (
            f"Payment processor reached ({host}); cancellation not confirmed" if payment_processor
            else f"The agent left the official site ({host}); result not trusted"
        )
    if off_platform or payment_processor:
        result_data.update(off_platform_hosts=untrusted_hosts, off_platform=off_platform, payment_processor=payment_processor)
    if result_data.get("host_drift_cancelled"):
        status = StepStatus.stopped_before_commitment
        stop_point = StopPoint.payment if payment_processor else None
        error = f"H session cancelled: {result_data['host_drift_reason']}"
    return StepResult(
        kind=kind,
        status=status,
        summary=text,
        stop_point=stop_point,
        url=_http_url(typed_answer.get("final_url") or last_url),
        price_eur=price,
        live_view_url=_http_url(live_view_url),
        agent_view_url=_http_url(agent_view_url),
        h_session_id=session_id,
        data=result_data,
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
    allowed_hosts: tuple[str, ...] | None = None


class HRun:
    """Active H session: event tracking, controls and final result."""

    def __init__(
        self,
        runner: "HRunner",
        account: HAccount,
        session: Any,
        kind: StepKind,
        trace: TraceWriter,
        interactive: bool = False,
        session_handle: Any | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        max_steps: int | None = None,
        start_url: str | None = None,
    ):
        self.started_at = datetime.now(UTC).isoformat()
        self.max_steps = max_steps
        self.start_url = start_url
        self._pending_metrics: list[dict[str, Any]] = []
        self._runner = runner
        self.account = account
        # Une session one-shot passe brièvement par `idle` avant `completed` : on attend l'état terminal.
        self._settled = SETTLED_STATUSES if interactive else TERMINAL_STATUSES
        self._interactive = interactive
        self._session_handle = session_handle
        self._sessions = account.client.sessions
        self.id: str = session.id
        self.kind = kind
        self.trace = trace
        self.agent_view_url: str | None = getattr(session, "agent_view_url", None)
        self.live_view_url: str | None = None
        self.share_url: str | None = None
        self._screenshot_ref: tuple[str, str] | None = None
        self.browser_observation: dict[str, Any] | None = None
        self.status: str = getattr(getattr(session, "status", None), "status", None) or "pending"
        self.answer: Any = None
        self.outcome: str | None = None
        self.error: str | None = None
        self.error_code: str | None = None
        self.last_url: str | None = None
        self.last_title: str | None = None
        self.allowed_hosts = allowed_hosts
        self.off_platform = False
        self.payment_processor = False
        self.off_platform_hosts: list[str] = []
        self._host_drift_reason: str | None = None
        self._host_drift_cancelled = False
        self._created_at = time.monotonic()
        self.metrics: dict[str, Any] = {"elapsed_s": 0.0}
        self.event_count = 0
        self.result: StepResult | None = None
        self._cursor = 0
        self._released = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _log(self, type_: str, message: str | None = None, **data: Any) -> None:
        event = TraceEvent(
            source="h",
            type=type_,
            message=message,
            data={"h_session_id": self.id, "step": self.kind.value, **data},
        )
        self.trace.write(event)
        if type_ == "metrics":
            self._pending_metrics.append(event.model_dump(mode="json"))

    def _update_metrics(self, metrics: dict[str, Any]) -> None:
        previous = (self.metrics.get("steps"), self.metrics.get("total_cost"))
        self.metrics.update({key: value for key, value in metrics.items() if value is not None})
        if previous != (self.metrics.get("steps"), self.metrics.get("total_cost")):
            steps = self.metrics.get("steps")
            cost = self.metrics.get("total_cost")
            self._log(
                "metrics", f"step {steps}/{self.max_steps} · ${cost or 0:.3f}",
                steps=steps, total_cost=cost,
                elapsed_s=round(time.monotonic() - self._created_at, 1),
            )

    async def _notify_metrics(self, on_event: EventCallback | None) -> None:
        pending, self._pending_metrics = self._pending_metrics, []
        if on_event is None:
            return
        for event in pending:
            outcome = on_event(event)
            if inspect.isawaitable(outcome):
                await outcome

    def _absorb(self, event: dict[str, Any]) -> None:
        self.event_count += 1
        event_type = event.get("type")
        data = event.get("data") or {}
        if not isinstance(data, dict):
            return
        if event_type != "LiveViewUrlEvent":
            for url in _event_page_urls(data):
                self.last_url = url
                self._check_host(url)
                if self.off_platform:
                    break
        if event_type == "LiveViewUrlEvent" and data.get("live_view_url"):
            self.live_view_url = data["live_view_url"]
        elif event_type == "MetricsUpdateEvent" and isinstance(data.get("metrics"), dict):
            self._update_metrics(data["metrics"])
        elif event_type == "AgentRunStatusChangeEvent" and data.get("status"):
            self.status = data["status"]
            self.error_code = data.get("error_code") or self.error_code
        elif event_type == "AgentErrorEvent":
            self.error = data.get("error") or self.error
            info = data.get("info") if isinstance(data.get("info"), dict) else {}
            self.error_code = data.get("error_code") or info.get("error_code") or self.error_code
        elif event_type == "AgentEvent":
            kind = data.get("kind")
            if kind == "observation_event":
                metadata = data.get("metadata") or {}
                self.last_url = metadata.get("url") or self.last_url
                self.last_title = safe_text(metadata.get("title")) or self.last_title
                image = data.get("image")
                if isinstance(image, dict) and image.get("type") == "url" and image.get("media_type") == "image/png":
                    self._capture_reference(image.get("source"), metadata)
            elif kind == "answer_event":
                self.answer = data.get("answer")
                self.outcome = data.get("outcome") or self.outcome

    def _check_host(self, url: str) -> None:
        if self.off_platform:
            return
        parsed = _http_url(url)
        host = parsed.host if parsed is not None else "invalid URL"
        forbidden = parsed is not None and host_matches(str(parsed), _FORBIDDEN_RUN_HOSTS)
        payment = parsed is not None and host_matches(str(parsed), _PAYMENT_PROCESSOR_HOSTS)
        allowed = self.allowed_hosts is None or (parsed is not None and host_matches(str(parsed), self.allowed_hosts))
        if forbidden or payment or not allowed:
            self.off_platform = True
            reason = "forbidden host" if forbidden else "payment processor" if payment else "outside allowed_hosts"
            self._host_drift_reason = f"{host} ({reason})"
            self.payment_processor = self.payment_processor or payment
            if host not in self.off_platform_hosts:
                self.off_platform_hosts.append(host)
            allowed_label = ", ".join(self.allowed_hosts or ()) or "the official site"
            self._log("host_drift", f"Agent left {allowed_label} for {host}", url=url, allowed=list(self.allowed_hosts or ()), payment_processor=payment)

    def _capture_reference(self, source: str | None, metadata: dict[str, Any]) -> None:
        if not isinstance(source, str):
            return
        try:
            url = urlsplit(source)
            prefix = f"/api/v1/trajectories/{self.id}/resources/"
            if url.scheme != "https" or not url.path.startswith(prefix):
                return
            parts = unquote(url.path[len(prefix):]).split("/")
            if len(parts) < 3 or parts[1] != self.id or any(part in (".", "..") or not re.fullmatch(r"[\w.-]+", part) for part in parts):
                return
        except ValueError:
            return
        reference = (parts[0], "/".join(parts[1:]))
        if reference != self._screenshot_ref:
            revision = (self.browser_observation or {}).get("revision", 0) + 1
            self._screenshot_ref = reference
            self.browser_observation = {"revision": revision, "url": metadata.get("url"), "title": metadata.get("title")}

    async def get_screenshot(self) -> bytes | None:
        if self._screenshot_ref is None:
            return None
        bucket, key = self._screenshot_ref
        content = bytearray()
        async for chunk in self._sessions.get_session_resource(self.id, bucket, key):
            if len(content) + len(chunk) > 8 * 1024 * 1024:
                raise RuntimeError("Capture H trop volumineuse.")
            content.extend(chunk)
        return bytes(content)

    async def refresh_status(self) -> str:
        status = await self._sessions.get_session_status(self.id)
        self.status = status.status
        self.outcome = getattr(status, "outcome", None) or self.outcome
        self.error = getattr(status, "error", None) or self.error
        self.error_code = getattr(status, "error_code", None) or self.error_code
        self.metrics["elapsed_s"] = time.monotonic() - self._created_at
        if getattr(status, "steps", None) is not None:
            self._update_metrics({"steps": status.steps})
        return self.status

    async def wait_for_status(self, statuses: Iterable[str], timeout_s: float = 60.0, poll_s: float = 1.0) -> float:
        """Wait for one of the statuses and return elapsed seconds."""
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
        """Control message, always accompanied by stop rules (`guard_task`)."""
        await self._sessions.send_session_messages(
            self.id, request=SendSessionMessagesRequestBody_UserMessage(message=guard_task(message))
        )
        self._log("control", "message", text=message)

    async def force_answer(self) -> None:
        await self._sessions.force_session_answer(self.id)
        self._log("control", "force_answer")

    async def cancel(self) -> None:
        await self._sessions.cancel_session(self.id)
        self._log("control", "cancel")

    async def _follow(self, on_event: EventCallback | None, wait_for_seconds: int) -> None:
        if self._session_handle is not None:
            async for raw in self._session_handle.stream(
                from_index=self._cursor,
                wait_for_seconds=wait_for_seconds,
                until="settled" if self._interactive else "terminal",
            ):
                event = as_dict(raw)
                self._absorb(event)
                if self.off_platform:
                    await self._stop_host_drift(event)
                    return
                await self._notify_metrics(on_event)
                self.trace.write(to_trace_event(event, self.id, self.kind.value))
                if on_event is not None:
                    outcome = on_event(event)
                    if inspect.isawaitable(outcome):
                        await outcome
                self._cursor += 1
            await self.refresh_status()
            await self._notify_metrics(on_event)
            return

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
                if self.off_platform:
                    await self._stop_host_drift(event)
                    return
                await self._notify_metrics(on_event)
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
            await self.refresh_status()
            await self._notify_metrics(on_event)
            if self.status in self._settled and not batch:
                return

    async def _stop_host_drift(self, event: dict[str, Any]) -> None:
        try:
            await self.cancel()
            self._host_drift_cancelled = True
            self.status = "interrupted"
        finally:
            self._release()
            self.trace.write(to_trace_event(event, self.id, self.kind.value))

    async def _finalize(self) -> StepResult:
        try:
            session = await self._sessions.get_session(self.id)
            if self.answer is None:
                self.answer = getattr(session, "latest_answer", None)
            self.agent_view_url = getattr(session, "agent_view_url", None) or self.agent_view_url
        except Exception as exc:  # noqa: BLE001 - le résultat reste exploitable sans ces champs
            self._log("warning", f"get_session failed: {exc}")
        return self._result()

    def _result(self, error: str | None = None) -> StepResult:
        self.metrics["elapsed_s"] = time.monotonic() - self._created_at
        return build_step_result(
            self.kind,
            self.status,
            answer=self.answer,
            outcome=self.outcome,
            error=error or self.error,
            error_code=self.error_code,
            session_id=self.id,
            live_view_url=self.live_view_url,
            agent_view_url=self.agent_view_url,
            last_url=self.last_url,
            off_platform=self.off_platform,
            payment_processor=self.payment_processor,
            off_platform_hosts=self.off_platform_hosts,
            data={
                "agent_view_url": self.agent_view_url,
                "host_drift_cancelled": self._host_drift_cancelled,
                "host_drift_reason": self._host_drift_reason,
                "share_url": self.share_url,
                "h_key": self.account.name,
                "title": self.last_title,
                "steps": self.metrics.get("steps"),
                "total_cost": self.metrics.get("total_cost"),
                "elapsed_s": self.metrics["elapsed_s"],
                "started_at": self.started_at,
                "ended_at": datetime.now(UTC).isoformat(),
                "duration_s": round(self.metrics["elapsed_s"], 1),
                "max_steps": self.max_steps,
                "start_url": self.start_url,
                "agent": self._runner.agent,
                "events": self.event_count,
            },
        )

    async def wait(
        self,
        on_event: EventCallback | None = None,
        timeout_s: float | None = None,
        wait_for_seconds: int = 20,
    ) -> StepResult:
        """Track the session to completion; after `timeout_s`, cancel it to release the slot.

        An interactive session stopped at `idle` keeps its slot: `close()` (or `async with run:`) cancels it.
        """
        try:
            await asyncio.wait_for(self._follow(on_event, wait_for_seconds), timeout_s)
            result = await self._finalize()
        except TimeoutError:
            await self._abandon()
            self.status = "timed_out"
            result = self._result(error=f"RunAI timeout after {timeout_s}s")
        except asyncio.CancelledError:
            await asyncio.shield(self._abandon())
            raise
        except Exception as exc:  # noqa: BLE001 - toute erreur de suivi devient un échec tracé
            await self._abandon()
            result = self._result(error=f"{type(exc).__name__}: {exc}")
            result.status = StepStatus.failed
        if self.status in TERMINAL_STATUSES:
            self._release()
        self.result = result
        self._log("result", result.status.value, result=result.model_dump(mode="json"))
        return result

    async def _abandon(self) -> None:
        try:
            await self._safe_cancel()
        except Exception:  # noqa: BLE001, S110 - trace illisible : le slot doit quand même être libéré
            pass
        finally:
            self._release()

    async def _safe_cancel(self) -> None:
        if self.status in TERMINAL_STATUSES:
            return
        try:
            await self.cancel()
        except Exception as exc:  # noqa: BLE001
            self._log("warning", f"cancellation failed: {exc}")

    async def close(self) -> None:
        """Cancel the session if still active (including `idle`) and release the local slot."""
        if not self._released and self.status not in TERMINAL_STATUSES:
            await self._safe_cancel()
        self._release()

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self._runner._release(self.account)


class HRunner:
    """Run guarded H steps on one or more H keys, using each key's actual quota and local cap.

    Without `client` or `accounts`, keys come from the environment (`HAI_API_KEY`, `HAI_API_KEY_2`…).
    `max_concurrency` (default `RUNAI_H_MAX_CONCURRENCY`) is the local cap **per key**.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        accounts: Iterable[HAccount] | None = None,
        agent: str | None = None,
        max_concurrency: int | None = None,
        quota_poll_s: float = 5.0,
        quota_timeout_s: float = 300.0,
        traces_dir=None,
    ):
        settings = get_settings()
        self.agent = agent or settings.h_agent
        self.max_concurrency = max_concurrency or settings.h_max_concurrency
        self.quota_poll_s = quota_poll_s
        self.quota_timeout_s = quota_timeout_s
        self.traces_dir = traces_dir
        try:
            self.overrides = json.loads(os.environ.get("RUNAI_H_OVERRIDES", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("RUNAI_H_OVERRIDES must be a valid JSON object") from exc
        if not isinstance(self.overrides, dict):
            raise ValueError("RUNAI_H_OVERRIDES must be a JSON object")  # noqa: TRY004
        if accounts is not None:
            self.accounts = list(accounts)
        elif client is not None:
            self.accounts = [HAccount("default", client=client, max_concurrency=self.max_concurrency)]
        else:
            keys = api_keys_from_env() or [("HAI_API_KEY", None)]
            self.accounts = [HAccount(name, api_key=key, max_concurrency=self.max_concurrency) for name, key in keys]
        if not self.accounts:
            raise ValueError("At least one H key is required")
        self._slot_freed = asyncio.Event()
        self._releases = 0
        self._attempts: dict[tuple[str, StepKind], int] = {}
        self._failed_attempts: dict[tuple[str, StepKind], list[int]] = {}

    @property
    def client(self) -> Any:
        return self.accounts[0].client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for account in self.accounts:
            await account.aclose()

    async def quotas(self) -> dict[str, Any]:
        """Actual quota for each key, by key name."""
        values = await asyncio.gather(*(account.quota() for account in self.accounts))
        return {account.name: quota for account, quota in zip(self.accounts, values, strict=True)}

    async def _pick(self, accounts: list[HAccount]) -> tuple[HAccount | None, dict[str, Any]]:
        """Choose the key with the most free slots (actual quota bounded by the local cap)."""
        values = await asyncio.gather(*(account.quota() for account in accounts), return_exceptions=True)
        errors = [value for value in values if isinstance(value, BaseException)]
        if len(errors) == len(values):
            raise errors[0]
        best, best_score, seen = None, (0, 0), {}
        for account, quota in zip(accounts, values, strict=True):
            if isinstance(quota, BaseException):
                seen[account.name] = f"erreur {type(quota).__name__}"
                continue
            seen[account.name] = f"{quota.active}/{quota.limit}"
            # À égalité de slots utilisables, on préfère l'organisation la moins chargée.
            score = (min(quota.available, account.max_concurrency - account.active), quota.available)
            if score[0] > 0 and score > best_score:
                best, best_score = account, score
        return best, seen

    async def _wait_freed(self, timeout_s: float | None, seen_releases: int) -> None:
        """Wait for a slot release; do not sleep if a slot was released since `seen_releases`."""
        if self._releases != seen_releases:
            return
        self._slot_freed.clear()
        try:
            await asyncio.wait_for(self._slot_freed.wait(), timeout_s)
        except TimeoutError:
            pass

    def _release(self, account: HAccount) -> None:
        account.active -= 1
        self._releases += 1
        self._slot_freed.set()

    async def _create(
        self, params: dict[str, Any], tools: list[Tool] | None = None
    ) -> tuple[HAccount, Any]:
        """Reserve a local slot on the freest key, then create the session; retry after a `429`."""
        deadline = None
        while True:
            releases = self._releases
            local = [account for account in self.accounts if account.has_local_slot]
            if not local:
                await self._wait_freed(None, releases)
                continue
            if deadline is None:
                deadline = time.monotonic() + self.quota_timeout_s
            account, seen = await self._pick(local)
            if account is not None and not account.has_local_slot:
                continue  # pris par un lancement concurrent pendant la lecture du quota : on relit
            if account is not None:
                account.active += 1
                try:
                    if tools:
                        session_handle = await account.client.start_session(
                            tools=tools, **params
                        )
                        return account, session_handle
                    return account, await account.client.sessions.create_session(
                        **params
                    )
                except TooManyRequestsError:
                    self._release(account)
                    releases = self._releases  # notre propre libération ne doit pas sauter l'attente
                    seen[account.name] = "429"
                except BaseException:
                    self._release(account)
                    raise
            if time.monotonic() >= deadline:
                detail = ", ".join(f"{name} {state}" for name, state in seen.items())
                raise HQuotaTimeout(f"No free H slot after {self.quota_timeout_s}s ({detail})")
            await self._wait_freed(self.quota_poll_s, releases)

    def _next_attempt(self, key: tuple[str, StepKind]) -> int:
        """Reuse the oldest attempt whose create failed, otherwise allocate a new one."""
        failed = self._failed_attempts.get(key)
        if failed:
            return failed.pop(0)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        return self._attempts[key]

    async def start(
        self,
        kind: StepKind,
        task: str,
        *,
        trace: TraceWriter | None = None,
        mission_id: str | None = None,
        start_url: str | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        max_steps: int | None = None,
        max_time_s: float | None = None,
        tools: Iterable[ToolInput] | None = None,
        **create_params: Any,
    ) -> HRun:
        """Create the session without H queuing (`queue=False`): local and actual slots are guaranteed."""
        reserved = RESERVED_CREATE_PARAMS & create_params.keys()
        if reserved:
            raise ValueError(f"Parameters managed by HRunner cannot be overridden: {sorted(reserved)}")
        params: dict[str, Any] = {**create_params, "agent": self.agent, "messages": guard_task(task), "queue": False}
        attempt_key = attempt = None
        if not params.get("idempotency_key"):
            attempt_key = (mission_id if mission_id is not None else str(uuid4()), kind)
            attempt = self._next_attempt(attempt_key) if mission_id is not None else 1
            params["idempotency_key"] = f"{attempt_key[0]}:{kind.value}:{attempt}"
        if self.overrides:
            params["overrides"] = {**self.overrides, **params.get("overrides", {})}
        if max_steps is not None:
            params["max_steps"] = max_steps
        if max_time_s is not None:
            params["max_time_s"] = max_time_s
        if start_url:
            params["overrides"] = {**params.get("overrides", {}), "agent.environments[kind=web].start_url": start_url}

        normalized_tools = as_tools(list(tools)) if tools else None
        try:
            account, session = await self._create(params, normalized_tools)
        except BaseException:
            if mission_id is not None and attempt_key is not None:
                # The session may exist server-side: the caller's retry must reuse this key.
                self._failed_attempts.setdefault(attempt_key, []).append(attempt)
            raise
        session_handle = session if normalized_tools else None
        try:
            if session_handle is not None:
                session = await account.client.sessions.get_session(session.id)
            writer = trace or TraceWriter(mission_id or f"h-{session.id}", traces_dir=self.traces_dir)
            run = HRun(
                self,
                account,
                session,
                kind,
                writer,
                interactive=bool(params.get("idle_timeout_s")),
                session_handle=session_handle,
                allowed_hosts=allowed_hosts,
                max_steps=max_steps,
                start_url=start_url,
            )
            try:
                share = await account.client.sessions.share_session(session.id)
                if share.share_url:
                    wrapper = getattr(account.client, "_client_wrapper", None)
                    base = wrapper.get_base_url() if callable(getattr(wrapper, "get_base_url", None)) else None
                    origin = urlsplit(base or "")
                    share_origin = (
                        f"{origin.scheme}://{origin.netloc}"
                        if origin.scheme and origin.netloc else "https://agp.eu.hcompany.ai"
                    )
                    run.share_url = (
                        share.share_url if urlsplit(share.share_url).scheme
                        else f"{share_origin}/{share.share_url.lstrip('/')}"
                    )
                    run.live_view_url = run.share_url
            except Exception as exc:  # noqa: BLE001
                run._log("warning", f"Could not share H session: {exc}")
            run._log(
                "session_created",
                kind.value,
                agent=self.agent,
                h_key=account.name,
                task=task,
                agent_view_url=run.agent_view_url,
                share_url=run.share_url,
                max_steps=max_steps,
                max_time_s=max_time_s,
                start_url=start_url,
            )
        except BaseException:
            with contextlib.suppress(Exception):
                await account.client.sessions.cancel_session(session.id)
            self._release(account)
            raise
        return run

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
        async with run:
            return await run.wait(on_event=on_event, timeout_s=timeout_s)

    async def run_many(self, steps: Iterable[HStep], *, mission_id: str | None = None, **run_params: Any) -> list[StepResult]:
        """Run steps in parallel; a launch error becomes a failed `StepResult`.

        `run_params` applies to all steps; `HStep` fields (and its `options`) take precedence.
        """
        steps = list(steps)
        trace = TraceWriter(mission_id, traces_dir=self.traces_dir) if mission_id else None

        async def one(step: HStep) -> StepResult:
            own = {"start_url": step.start_url, "max_steps": step.max_steps, "max_time_s": step.max_time_s, "allowed_hosts": step.allowed_hosts}
            params = {**run_params, **step.options, **{k: v for k, v in own.items() if v is not None}}
            params.setdefault("trace", trace)
            params.setdefault("mission_id", mission_id)
            try:
                return await self.run(step.kind, step.task, **params)
            except Exception as exc:  # noqa: BLE001 - une étape en échec ne bloque pas les autres
                return StepResult(kind=step.kind, status=StepStatus.failed, error=f"{type(exc).__name__}: {exc}")

        return list(await asyncio.gather(*(one(step) for step in steps)))
