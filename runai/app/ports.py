"""Interfaces minimales attendues des briques H, voix et recherche.

Les vraies implémentations (`runai/h/`, `runai/voice/`, `runai/search/`) n'ont qu'à respecter
ces Protocols pour être branchées dans `MissionService` à la place des fakes.
"""

from collections.abc import Callable
from typing import Protocol

from runai.models import Race, RunnerProfile, StepKind, StepResult, TraceEvent

EventSink = Callable[[TraceEvent], None]


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
    ) -> AgentRun: ...


class Transcriber(Protocol):
    """Brique Gladia : transcrit un enregistrement court envoyé par le navigateur."""

    async def transcribe(self, audio: bytes, content_type: str) -> str: ...
