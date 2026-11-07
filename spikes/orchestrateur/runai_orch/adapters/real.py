"""Implementation reelle sur le SDK hai-agents 1.4.3 (AsyncClient). Non executee dans ce spike."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from hai_agents import AsyncClient
from hai_agents.core.api_error import ApiError
from hai_agents.sessions import SendSessionMessagesRequestBody_UserMessage
from hai_agents.types import ToolRequest, ToolResultEvent

from .base import AdapterEvent, HAdapter, Quota, SessionSpec, StartedSession

log = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "timed_out", "interrupted"}
AGENT_VIEW = "https://platform.eu.hcompany.ai/agent-view/"


def _first_line(s: str | None, n: int = 160) -> str:
    s = (s or "").strip().split("\n")[0].strip()
    return s if len(s) <= n else s[: n - 1] + "…"


class RealHAdapter(HAdapter):
    name = "real"

    def __init__(self, client: AsyncClient | None = None, wait_for_seconds: int = 10):
        self.client = client or AsyncClient()  # lit HAI_API_KEY, region EU par defaut
        self.wait_for_seconds = wait_for_seconds

    async def start(self, spec: SessionSpec) -> StartedSession:
        s = await self.client.sessions.create_session(
            agent=spec.agent,
            messages=spec.task,
            overrides={"agent.answer_format": spec.answer_format, "agent.tools": spec.tools},
            max_time_s=spec.max_time_s,
            idle_timeout_s=spec.idle_timeout_s,
            timezone=spec.timezone,
            queue=True,
        )
        return StartedSession(session_id=s.id, live_view_url=s.agent_view_url or AGENT_VIEW + s.id)

    async def events(self, session_id: str) -> AsyncIterator[AdapterEvent]:
        idx, last_status, answered = 0, None, False
        while True:
            try:
                ch = await self.client.sessions.get_session_changes(
                    session_id, from_index=idx, include_events=True, wait_for_seconds=self.wait_for_seconds)
            except Exception as e:  # noqa: BLE001 - long-poll resilient aux coupures reseau
                log.warning("changes %s: %s", session_id, type(e).__name__)
                await asyncio.sleep(1)
                continue
            if ch is None:  # 204: rien de neuf pendant wait_for_seconds
                continue
            for ev in ch.new_events or []:
                for out in self._map(ev):
                    yield out
            start = idx if ch.first_index is None else ch.first_index
            idx = start + len(ch.new_events or [])
            if ch.metrics and ch.metrics.steps is not None:
                yield AdapterEvent("step", {"steps": ch.metrics.steps, "cost": ch.metrics.total_cost})
            if ch.answer is not None and ch.status in ("idle", "completed") and not answered:
                answered = True
                yield AdapterEvent("answer", {"answer": ch.answer})
            if ch.status != last_status:
                last_status = ch.status
                yield AdapterEvent("status", {"h_status": ch.status, "error": ch.error})
            if ch.status == "running":
                answered = False  # nouvelle reponse possible apres un send_message
            if ch.status in TERMINAL:
                return

    def _map(self, ev: Any) -> list[AdapterEvent]:
        t = getattr(ev, "type", None)
        d = ev.model_dump(mode="json").get("data") or {}
        if t == "LiveViewUrlEvent":
            return [AdapterEvent("live_view", {"url": d.get("live_view_url")})]
        if t == "ActiveStateChangeEvent" and d.get("state") == "awaiting_tool_results":
            calls = [c for c in d.get("pending_tool_calls") or [] if c.get("tool_name") == "request_human"]
            if calls:
                c = calls[0]
                return [AdapterEvent("human_needed", {**(c.get("args") or {}), "tool_call": c})]
        if t == "AgentEvent":
            kind = d.get("kind")
            if kind == "observation_event" and (d.get("image") or {}).get("source"):
                return [AdapterEvent("screenshot", {"url": d["image"]["source"]})]
            if kind == "policy_event":
                reqs = d.get("tool_reqs") or []
                return [AdapterEvent("step", {"thought": _first_line(d.get("reasoning_content")),
                                              "action": reqs[0].get("tool_name") if reqs else None})]
            if kind == "error_event":
                return [AdapterEvent("error", {"message": _first_line(str(d.get("error")))})]
        return []

    async def pause(self, session_id: str) -> None:
        await self.client.sessions.pause_session(session_id)  # 202 asynchrone, 409 si queued/fini

    async def resume(self, session_id: str) -> None:
        await self.client.sessions.resume_session(session_id)

    async def send_message(self, session_id: str, text: str) -> None:
        await self.client.sessions.send_session_messages(
            session_id, request=SendSessionMessagesRequestBody_UserMessage(message=text))

    async def answer_human(self, session_id: str, tool_call: dict[str, Any], result: Any) -> None:
        req = ToolRequest(tool_name=tool_call["tool_name"], args=tool_call.get("args") or {}, id=tool_call.get("id"))
        await self.client.sessions.send_session_tool_results(session_id, request=ToolResultEvent(tool_req=req, result=result))

    async def cancel(self, session_id: str) -> None:
        try:
            await self.client.sessions.cancel_session(session_id)  # DELETE /sessions/{id}
        except ApiError as e:
            if e.status_code not in (404, 409):  # deja terminee ou inconnue
                raise

    async def quota(self) -> Quota | None:
        q = await self.client.sessions.get_session_quota()
        return Quota(limit=q.limit, active=q.active, available=q.available)
