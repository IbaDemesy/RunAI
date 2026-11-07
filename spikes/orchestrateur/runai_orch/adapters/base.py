"""Adaptateur H abstrait : l'orchestrateur ne voit que des evenements normalises."""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal["status", "step", "screenshot", "live_view", "human_needed", "answer", "error"]

HUMAN_TOOL = {
    "name": "request_human",
    "description": (
        "Call this BEFORE ticking any health, rules, GDPR or consent checkbox, when an account or a real email "
        "is required, and when you reach the page right before payment. Explain what you need. Wait for the reply."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "enum": ["consent", "missing_info", "account_required", "before_payment"]},
            "question": {"type": "string"},
        },
        "required": ["reason", "question"],
    },
}


@dataclass
class SessionSpec:
    kind: str
    task: str
    answer_format: dict[str, Any]
    agent: str = "h/web-surfer-pro"
    tools: list[dict[str, Any]] = field(default_factory=lambda: [HUMAN_TOOL])
    max_time_s: float | None = 900
    idle_timeout_s: int | None = 1800
    timezone: str = "Europe/Paris"


@dataclass
class StartedSession:
    session_id: str
    live_view_url: str | None = None


@dataclass
class AdapterEvent:
    """status: data.h_status (statuts H). step: thought/action/steps. screenshot: url.
    live_view: url. human_needed: reason/question/tool_call. answer: answer (dict brut). error: message."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Quota:
    limit: int
    active: int
    available: int


class HAdapter(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    async def start(self, spec: SessionSpec) -> StartedSession: ...

    @abc.abstractmethod
    def events(self, session_id: str) -> AsyncIterator[AdapterEvent]:
        """Flux d'evenements jusqu'a un statut H terminal (completed, failed, timed_out, interrupted)."""

    @abc.abstractmethod
    async def pause(self, session_id: str) -> None: ...

    @abc.abstractmethod
    async def resume(self, session_id: str) -> None: ...

    @abc.abstractmethod
    async def send_message(self, session_id: str, text: str) -> None: ...

    @abc.abstractmethod
    async def answer_human(self, session_id: str, tool_call: dict[str, Any], result: Any) -> None:
        """Repond a un appel request_human en attente (la session est en awaiting_tool_results)."""

    @abc.abstractmethod
    async def cancel(self, session_id: str) -> None: ...

    @abc.abstractmethod
    async def quota(self) -> Quota | None: ...

    async def aclose(self) -> None:
        return None
