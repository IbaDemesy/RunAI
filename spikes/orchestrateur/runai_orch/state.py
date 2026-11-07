"""Machine a etats des missions et bus d'evenements (historique + abonnes SSE)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .contracts import MissionEvent, MissionKind, MissionOut, MissionState

S = MissionState

TRANSITIONS: dict[MissionState, set[MissionState]] = {
    S.queued: {S.running, S.failed, S.cancelled},
    S.running: {S.waiting_human, S.ready_to_pay, S.failed, S.cancelled},
    S.waiting_human: {S.running, S.ready_to_pay, S.failed, S.cancelled},
    S.ready_to_pay: {S.running, S.cancelled, S.failed},
    S.failed: set(),
    S.cancelled: set(),
}
TERMINAL = {S.failed, S.cancelled}


class InvalidTransition(Exception):
    pass


def can_transition(src: MissionState, dst: MissionState) -> bool:
    return src == dst or dst in TRANSITIONS[src]


@dataclass
class Mission:
    id: str
    trip_id: str
    kind: MissionKind
    task: str
    state: MissionState = S.queued
    waiting_reason: str | None = None
    session_id: str | None = None
    live_view_url: str | None = None
    steps: int = 0
    answer: dict[str, Any] | None = None
    error: str | None = None
    pending_tool_call: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[MissionEvent] = field(default_factory=list)
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    async def emit(self, type_: str, data: dict[str, Any] | None = None) -> MissionEvent:
        ev = MissionEvent(seq=len(self.events), mission_id=self.id, ts=time.time(), type=type_,
                          state=self.state, data=data or {})
        async with self._cond:
            self.events.append(ev)
            self.updated_at = ev.ts
            self._cond.notify_all()
        return ev

    async def transition(self, dst: MissionState, reason: str | None = None, **data: Any) -> bool:
        """Change d'etat et publie un evenement 'state'. Renvoie False si rien n'a change."""
        if not can_transition(self.state, dst):
            raise InvalidTransition(f"{self.state.value} -> {dst.value}")
        new_reason = reason if dst == S.waiting_human else None
        if dst == self.state and new_reason == self.waiting_reason:
            return False
        prev = self.state
        self.state, self.waiting_reason = dst, new_reason
        if dst == S.failed and reason:
            self.error = reason
        await self.emit("state", {"from": prev.value, "to": dst.value, "reason": reason, **data})
        return True

    async def stream(self, from_seq: int = 0, keepalive_s: float = 15.0):
        """Rejoue l'historique depuis from_seq puis suit le direct. None = keep-alive. S'arrete en etat terminal."""
        i = from_seq
        while True:
            async with self._cond:
                if i >= len(self.events) and not self.terminal:
                    try:
                        await asyncio.wait_for(self._cond.wait_for(lambda i=i: i < len(self.events) or self.terminal),
                                               keepalive_s)
                    except TimeoutError:
                        pass
                batch = self.events[i:]
                done = self.terminal
            if not batch and not done:
                yield None
            for ev in batch:
                yield ev
            i += len(batch)
            if done and i >= len(self.events):
                return

    def public(self, queue_position: int | None = None) -> MissionOut:
        return MissionOut(id=self.id, trip_id=self.trip_id, kind=self.kind, state=self.state,
                          waiting_reason=self.waiting_reason, session_id=self.session_id,
                          live_view_url=self.live_view_url, queue_position=queue_position, steps=self.steps,
                          answer=self.answer, error=self.error, created_at=self.created_at,
                          updated_at=self.updated_at)
