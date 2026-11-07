"""Interfaces minimales attendues des briques H, voix et recherche.

Les vraies implémentations (`runai/h/`, `runai/voice/`, `runai/search/`) n'ont qu'à respecter
ces Protocols pour être branchées dans `MissionService` à la place des fakes.
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
    """Brique Linkup : transforme une phrase libre en fiche course sourcée."""

    async def find_race(self, query: str) -> Race: ...


class AgentRun(Protocol):
    """Un agent de navigation en cours (une session H)."""

    session_id: str
    live_view_url: str | None

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...

    async def send_message(self, text: str) -> None: ...

    async def wait(self) -> StepResult:
        """Attend la fin de l'agent ; le résultat porte le `StopPoint` atteint."""
        ...


class BrowserAgents(Protocol):
    """Brique H : lance un agent pour une étape. `task` est déjà passé par `guard_task()`."""

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
    """Brique Gladia : transcrit un enregistrement court envoyé par le navigateur."""

    async def transcribe(self, audio: bytes, content_type: str) -> str: ...

    def stream(self, chunks: AsyncIterable[bytes], sample_rate: int) -> AsyncIterator[BaseModel]: ...
