"""Minimal interfaces for H, voice and search components.

Real implementations in runai/h/, runai/voice/ and runai/search/ implement
these protocols to replace fakes in MissionService.
"""

from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from runai.app.tasks import TripBrief
    from runai.search.logistics_sweep import LogisticsSweep

from pydantic import BaseModel

from runai.models import Race, RunnerProfile, StepKind, StepResult, TraceEvent

EventSink = Callable[[TraceEvent], None]
AskUser = Callable[[str, list[str]], Awaitable[str]]


class LogisticsSweeper(Protocol):
    async def sweep(self, race: Race, brief: "TripBrief", timeout_s: float = 15) -> "LogisticsSweep": ...


class RaceSearch(Protocol):
    """Linkup component: turn free text into a sourced race record."""

    async def find_race(self, query: str) -> Race: ...


class AgentRun(Protocol):
    """A running browser agent (an H session)."""

    session_id: str
    live_view_url: str | None

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...

    async def send_message(self, text: str) -> None: ...

    async def wait(self) -> StepResult:
        """Wait for the agent; the result includes the reached StopPoint."""
        ...


class BrowserAgents(Protocol):
    """H component: launch a step agent with an already guarded task."""

    async def start(
        self,
        kind: StepKind,
        task: str,
        race: Race,
        profile: RunnerProfile,
        on_event: EventSink,
        ask_user: AskUser,
        mission_id: str | None = None,
        query: str = "",
    ) -> AgentRun: ...


class Transcriber(Protocol):
    """Gladia component: transcribe a short browser recording."""

    async def transcribe(self, audio: bytes, content_type: str) -> str: ...

    def stream(self, chunks: AsyncIterable[bytes], sample_rate: int) -> AsyncIterator[BaseModel]: ...
