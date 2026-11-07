"""Implementation mock : rejoue des scenarios d'evenements, avec pause / message / cancel et quota simule."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .base import AdapterEvent, HAdapter, Quota, SessionSpec, StartedSession

# (delai en secondes avant l'evenement, evenement). Les delais sont divises par `speed`.
Step = tuple[float, AdapterEvent]


def _steps(kind: str, url: str) -> list[Step]:
    E = AdapterEvent
    return [
        (0.2, E("status", {"h_status": "running"})),
        (0.1, E("live_view", {"url": None})),  # rempli au start
        (0.5, E("step", {"thought": f"Opening {url}", "action": "navigate"})),
        (0.3, E("screenshot", {"url": f"mock://{kind}/1.png"})),
        (0.5, E("step", {"thought": "Dismissing the cookie banner", "action": "click"})),
        (0.5, E("step", {"thought": "Filling the guest form with Camille Martin", "action": "type"})),
        (0.3, E("screenshot", {"url": f"mock://{kind}/2.png"})),
    ]


ANSWERS: dict[str, dict[str, Any]] = {
    "inscription": {"ready_for_payment": True, "payment_submitted": False, "blocked": False,
                    "current_url": "https://in.njuko.com/mock/checkout", "total_price_eur": 8.0,
                    "platform": "Njuko", "race_name": "10 km du Maine Libre", "distance_km": 10,
                    "race_date": "2027-03-07", "filled_fields": ["first_name", "last_name", "email", "birth_date"],
                    "human_checkboxes": ["reglement", "rgpd"], "missing_fields": ["pps"],
                    "note": "Recap page shown, stopped before payment."},
    "hotel": {"ready_for_payment": True, "payment_submitted": False, "blocked": False,
              "current_url": "https://all.accor.com/mock/guest-details", "total_price_eur": 185.41,
              "hotel_name": "ibis Mock Centre", "check_in": "2027-03-06", "check_out": "2027-03-07",
              "free_cancellation": True, "distance_to_start_km": 1.2, "note": "Guest details page, not paid."},
    "transport": {"ready_for_payment": True, "payment_submitted": False, "blocked": False,
                  "current_url": "https://booking.flytap.com/mock/passengers", "total_price_eur": 103.47,
                  "mode": "plane", "carrier": "TAP", "outbound_departure": "2027-03-06T08:10:00",
                  "return_departure": "2027-03-07T19:40:00", "passengers": 1, "note": "Passengers page, not paid."},
}


def default_script(kind: str) -> list[Step]:
    E = AdapterEvent
    url = {"inscription": "https://in.njuko.com", "hotel": "https://all.accor.com",
           "transport": "https://www.flytap.com"}.get(kind, "https://example.com")
    script = _steps(kind, url)
    if kind == "inscription":
        script.append((0.4, E("human_needed", {"reason": "consent", "question": "Tick the rules and GDPR boxes?"})))
        script.append((0.4, E("step", {"thought": "Human validated the boxes, opening the recap", "action": "click"})))
    script += [(0.5, E("screenshot", {"url": f"mock://{kind}/recap.png"})),
               (0.3, E("answer", {"answer": ANSWERS.get(kind, {})})),
               (0.0, E("status", {"h_status": "idle"}))]
    return script


@dataclass
class _MockSession:
    id: str
    spec: SessionSpec
    script: list[Step]
    out: asyncio.Queue = field(default_factory=asyncio.Queue)
    running: asyncio.Event = field(default_factory=asyncio.Event)
    human: asyncio.Event = field(default_factory=asyncio.Event)
    human_reply: Any = None
    messages: list[str] = field(default_factory=list)
    task: asyncio.Task | None = None
    holds_slot: bool = True


class MockHAdapter(HAdapter):
    """speed divise tous les delais. external_active simule les sessions des autres equipes sur les 3 slots."""

    name = "mock"

    def __init__(self, speed: float = 1.0, limit: int = 3, external_active: int = 0,
                 scripts: dict[str, list[Step]] | None = None):
        self.speed = speed
        self.limit = limit
        self.external_active = external_active
        self.scripts = scripts or {}
        self.sessions: dict[str, _MockSession] = {}
        self.calls: list[tuple[str, str]] = []
        self._ids = itertools.count(1)

    def _sleep(self, s: float):
        return asyncio.sleep(s / self.speed if self.speed else 0)

    async def start(self, spec: SessionSpec) -> StartedSession:
        sid = f"mock-{spec.kind}-{next(self._ids)}"
        script = list(self.scripts.get(spec.kind) or default_script(spec.kind))
        s = _MockSession(id=sid, spec=spec, script=script)
        s.running.set()
        self.sessions[sid] = s
        self.calls.append(("start", sid))
        s.out.put_nowait(AdapterEvent("status", {"h_status": "pending"}))
        s.task = asyncio.create_task(self._play(s))
        return StartedSession(session_id=sid, live_view_url=f"https://platform.eu.hcompany.ai/agent-view/{sid}")

    async def _play(self, s: _MockSession) -> None:
        try:
            for delay, ev in s.script:
                await self._sleep(delay)
                await s.running.wait()  # pause: on bloque ici
                if ev.type == "live_view":
                    ev = AdapterEvent("live_view", {"url": f"https://platform.eu.hcompany.ai/agent-view/{s.id}"})
                await s.out.put(ev)
                if ev.type == "status" and ev.data.get("h_status") in ("completed", "failed", "timed_out"):
                    s.holds_slot = False
                    return
                if ev.type == "human_needed":
                    await s.out.put(AdapterEvent("status", {"h_status": "awaiting_tool_results"}))
                    s.human.clear()
                    await s.human.wait()
                    await s.out.put(AdapterEvent("status", {"h_status": "running"}))
        except asyncio.CancelledError:
            s.holds_slot = False
            await s.out.put(AdapterEvent("status", {"h_status": "interrupted"}))
            raise

    async def events(self, session_id: str) -> AsyncIterator[AdapterEvent]:
        s = self.sessions[session_id]
        while True:
            ev = await s.out.get()
            yield ev
            if ev.type == "status" and ev.data.get("h_status") in ("completed", "failed", "timed_out", "interrupted"):
                return

    async def pause(self, session_id: str) -> None:
        self.calls.append(("pause", session_id))
        s = self.sessions[session_id]
        s.running.clear()
        await s.out.put(AdapterEvent("status", {"h_status": "paused"}))

    async def resume(self, session_id: str) -> None:
        self.calls.append(("resume", session_id))
        s = self.sessions[session_id]
        if not s.running.is_set():
            s.running.set()
            await s.out.put(AdapterEvent("status", {"h_status": "running"}))

    async def send_message(self, session_id: str, text: str) -> None:
        self.calls.append(("message", session_id))
        s = self.sessions[session_id]
        s.messages.append(text)
        await s.out.put(AdapterEvent("step", {"thought": f"User says: {text[:80]}", "action": "read_message"}))
        await self.resume(session_id)  # comme H : un message reprend une session en pause
        if s.task and s.task.done():  # session idle : H relance l'agent avec le message
            s.script = [(0.2, AdapterEvent("status", {"h_status": "running"})),
                        (0.3, AdapterEvent("answer", {"answer": ANSWERS.get(s.spec.kind, {})})),
                        (0.0, AdapterEvent("status", {"h_status": "idle"}))]
            s.task = asyncio.create_task(self._play(s))

    async def answer_human(self, session_id: str, tool_call: dict[str, Any], result: Any) -> None:
        self.calls.append(("tool_result", session_id))
        s = self.sessions[session_id]
        s.human_reply = result
        s.human.set()

    async def cancel(self, session_id: str) -> None:
        self.calls.append(("cancel", session_id))
        s = self.sessions.get(session_id)
        if s is None:
            return
        s.running.set()
        s.holds_slot = False  # comme H apres DELETE : le slot est rendu
        if s.task and not s.task.done():
            s.task.cancel()
        else:
            s.holds_slot = False
            await s.out.put(AdapterEvent("status", {"h_status": "interrupted"}))

    async def quota(self) -> Quota:
        active = self.external_active + sum(1 for s in self.sessions.values() if s.holds_slot)
        return Quota(limit=self.limit, active=active, available=max(0, self.limit - active))
