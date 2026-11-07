import asyncio
import contextlib
import inspect
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Self
from urllib.parse import unquote, urlsplit

from hai_agents import AsyncClient
from hai_agents.errors import TooManyRequestsError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.tools import Tool, ToolInput, as_tools
from pydantic import HttpUrl, TypeAdapter, ValidationError

from runai.app.providers import FORBIDDEN_HOSTS, host_matches
from runai.config import get_settings
from runai.h.events import answer_text, as_dict, safe_text, to_trace_event
from runai.models import StepKind, StepResult, StepStatus, TraceEvent
from runai.safety import detect_stop_point, guard_task
from runai.tracing import TraceWriter

TERMINAL_STATUSES = frozenset({"completed", "failed", "timed_out", "interrupted"})
SETTLED_STATUSES = TERMINAL_STATUSES | {"idle"}

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

_HTTP_URL = TypeAdapter(HttpUrl)
_ANTI_BOT_BLOCK = re.compile(r"\bBLOCAGE CAPTCHA/ANTI-BOT\b", re.IGNORECASE)
_PAYMENT_PROCESSOR_HOSTS = (
    "stripe.com", "adyen.com", "paypal.com", "checkout.com",
    "ingenico.com", "ingenico.fr", "worldline.com", "worldline-solutions.com",
    "mollie.com",
)


RESERVED_CREATE_PARAMS = frozenset({"agent", "messages", "queue"})


class HQuotaTimeout(TimeoutError):
    """Aucun slot H libre dans le délai imparti."""


def api_keys_from_env() -> list[tuple[str, str]]:
    """Clés H disponibles : `HAI_API_KEY` puis `HAI_API_KEY_2`, `HAI_API_KEY_3`… (noms renvoyés, jamais les valeurs loguées)."""
    names = ["HAI_API_KEY"]
    index = 2
    while os.getenv(f"HAI_API_KEY_{index}"):
        names.append(f"HAI_API_KEY_{index}")
        index += 1
    return [(name, os.environ[name]) for name in names if os.getenv(name)]


class HAccount:
    """Une clé H (une organisation H) : son client, son plafond local et ses sessions en cours."""

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
    if h_status in ("completed", "idle"):
        if _ANTI_BOT_BLOCK.search(text or ""):
            status = StepStatus.failed
            error = error or "Blocage captcha/anti-bot signalé par l'agent."
        else:
            stop_point = detect_stop_point(text or "", ignore_negated=True)
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
    untrusted_hosts = list(off_platform_hosts)
    if off_platform or payment_processor:
        status = StepStatus.failed
        stop_point = None
        host = ", ".join(untrusted_hosts) or "unknown host"
        error = (
            "Payment provider page reached — automation stopped" if payment_processor
            else f"The agent left the official site ({host}); result not trusted"
        )
    result_data = {"h_status": h_status, "answer": answer, "outcome": outcome, **(data or {})}
    if off_platform or payment_processor:
        result_data.update(off_platform_hosts=untrusted_hosts, off_platform=off_platform, payment_processor=payment_processor)
    return StepResult(
        kind=kind,
        status=status,
        summary=text,
        stop_point=stop_point,
        url=_http_url(last_url),
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
    """Session H en cours : suivi des événements, contrôles et résultat final."""

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
    ):
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
        self._screenshot_ref: tuple[str, str] | None = None
        self.browser_observation: dict[str, Any] | None = None
        self.status: str = getattr(getattr(session, "status", None), "status", None) or "pending"
        self.answer: Any = None
        self.outcome: str | None = None
        self.error: str | None = None
        self.last_url: str | None = None
        self.last_title: str | None = None
        self.allowed_hosts = allowed_hosts
        self.off_platform = False
        self.payment_processor = False
        self.off_platform_hosts: list[str] = []
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
                self.last_title = safe_text(metadata.get("title")) or self.last_title
                if url := metadata.get("url"):
                    self._check_host(url)
                image = data.get("image")
                if isinstance(image, dict) and image.get("type") == "url" and image.get("media_type") == "image/png":
                    self._capture_reference(image.get("source"), metadata)
            elif kind == "answer_event":
                self.answer = data.get("answer")
                self.outcome = data.get("outcome") or self.outcome

    def _check_host(self, url: str) -> None:
        parsed = _http_url(url)
        host = parsed.host if parsed is not None else "invalid URL"
        forbidden = parsed is not None and host_matches(str(parsed), tuple(FORBIDDEN_HOSTS))
        payment = parsed is not None and host_matches(str(parsed), _PAYMENT_PROCESSOR_HOSTS)
        allowed = self.allowed_hosts is None or (parsed is not None and host_matches(str(parsed), self.allowed_hosts))
        if forbidden or payment or not allowed:
            self.off_platform = True
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
        if getattr(status, "steps", None) is not None:
            self.metrics["steps"] = status.steps
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
        """Message de pilotage, toujours accompagné des règles d'arrêt (`guard_task`)."""
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
                self.trace.write(to_trace_event(event, self.id, self.kind.value))
                if on_event is not None:
                    outcome = on_event(event)
                    if inspect.isawaitable(outcome):
                        await outcome
                self._cursor += 1
            await self.refresh_status()
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
            live_view_url=self.live_view_url,
            agent_view_url=self.agent_view_url,
            last_url=self.last_url,
            off_platform=self.off_platform,
            payment_processor=self.payment_processor,
            off_platform_hosts=self.off_platform_hosts,
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
        """Suit la session jusqu'à son terme ; au-delà de `timeout_s`, l'annule pour libérer le slot.

        Une session interactive arrêtée sur `idle` garde son slot : `close()` (ou `async with run:`) l'annule.
        """
        try:
            await asyncio.wait_for(self._follow(on_event, wait_for_seconds), timeout_s)
            result = await self._finalize()
        except TimeoutError:
            await self._abandon()
            self.status = "timed_out"
            result = self._result(error=f"timeout RunAI après {timeout_s}s")
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
            self._log("warning", f"annulation impossible : {exc}")

    async def close(self) -> None:
        """Annule la session si elle tourne encore (y compris `idle`) et libère le slot local."""
        if not self._released and self.status not in TERMINAL_STATUSES:
            await self._safe_cancel()
        self._release()

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self._runner._release(self.account)


class HRunner:
    """Lance des étapes H gardées sur une ou plusieurs clés H, selon le quota réel de chacune et un plafond par clé.

    Sans `client` ni `accounts`, les clés viennent de l'environnement (`HAI_API_KEY`, `HAI_API_KEY_2`…).
    `max_concurrency` (défaut `RUNAI_H_MAX_CONCURRENCY`) est le plafond local **par clé**.
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
        if accounts is not None:
            self.accounts = list(accounts)
        elif client is not None:
            self.accounts = [HAccount("default", client=client, max_concurrency=self.max_concurrency)]
        else:
            keys = api_keys_from_env() or [("HAI_API_KEY", None)]
            self.accounts = [HAccount(name, api_key=key, max_concurrency=self.max_concurrency) for name, key in keys]
        if not self.accounts:
            raise ValueError("Au moins une clé H est nécessaire")
        self._slot_freed = asyncio.Event()
        self._releases = 0

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
        """Quota réel de chaque clé, par nom de clé."""
        values = await asyncio.gather(*(account.quota() for account in self.accounts))
        return {account.name: quota for account, quota in zip(self.accounts, values, strict=True)}

    async def _pick(self, accounts: list[HAccount]) -> tuple[HAccount | None, dict[str, Any]]:
        """Choisit la clé qui a le plus de slots libres (quota réel borné par le plafond local)."""
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
        """Attend une libération de slot ; ne dort pas si un slot a été libéré depuis `seen_releases`."""
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
        """Réserve un slot local sur la clé la plus libre puis crée la session ; réessaie après un `429`."""
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
                raise HQuotaTimeout(f"Aucun slot H libre après {self.quota_timeout_s}s ({detail})")
            await self._wait_freed(self.quota_poll_s, releases)

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
        """Crée la session sans file d'attente H (`queue=False`) : un slot local et un slot réel sont garantis."""
        reserved = RESERVED_CREATE_PARAMS & create_params.keys()
        if reserved:
            raise ValueError(f"Paramètres gérés par HRunner, non surchargeables : {sorted(reserved)}")
        params: dict[str, Any] = {**create_params, "agent": self.agent, "messages": guard_task(task), "queue": False}
        if max_steps is not None:
            params["max_steps"] = max_steps
        if max_time_s is not None:
            params["max_time_s"] = max_time_s
        if start_url:
            params["overrides"] = {**params.get("overrides", {}), "agent.environments[kind=web].start_url": start_url}

        normalized_tools = as_tools(list(tools)) if tools else None
        account, session = await self._create(params, normalized_tools)
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
            )
            run._log(
                "session_created",
                kind.value,
                agent=self.agent,
                h_key=account.name,
                task=task,
                agent_view_url=run.agent_view_url,
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
        """Lance plusieurs étapes en parallèle ; une erreur de lancement devient un `StepResult` en échec.

        `run_params` s'applique à toutes les étapes ; les champs d'une `HStep` (et ses `options`) priment.
        """
        steps = list(steps)
        trace = TraceWriter(mission_id, traces_dir=self.traces_dir) if mission_id else None

        async def one(step: HStep) -> StepResult:
            own = {"start_url": step.start_url, "max_steps": step.max_steps, "max_time_s": step.max_time_s, "allowed_hosts": step.allowed_hosts}
            params = {**run_params, **step.options, **{k: v for k, v in own.items() if v is not None}}
            params.setdefault("trace", trace)
            try:
                return await self.run(step.kind, step.task, **params)
            except Exception as exc:  # noqa: BLE001 - une étape en échec ne bloque pas les autres
                return StepResult(kind=step.kind, status=StepStatus.failed, error=f"{type(exc).__name__}: {exc}")

        return list(await asyncio.gather(*(one(step) for step in steps)))
