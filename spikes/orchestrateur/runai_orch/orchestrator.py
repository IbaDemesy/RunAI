"""Orchestrateur : 3 missions en parallele par voyage, file d'attente des slots H, filtre serveur des reponses."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError

from .adapters.base import AdapterEvent, HAdapter, SessionSpec
from .contracts import (
    ANSWER_MODELS,
    MissionKind,
    MissionOut,
    MissionState,
    TripRequest,
    answer_format,
)
from .scheduler import SlotScheduler, SlotTimeout
from .state import Mission

log = logging.getLogger(__name__)
S = MissionState

RULES = (
    "Hard rules: never pay, never submit the final registration or booking, never create an account. "
    "Use guest mode. Use only this fictitious identity: {first} {last}, {email}, born {birth}. "
    "If an account or a real email is required, call request_human with reason account_required. "
    "Before ticking any health, rules or GDPR checkbox, call request_human with reason consent. "
    "Stop on the page right before payment and answer. Leave unknown fields empty, never invent them. "
    "Think out loud in short sentences: people are watching you live."
)

TASKS = {
    MissionKind.inscription: (
        "Register the runner for the race \"{race}\"{dist} on {date} in {city}. "
        "Start from {start}. Fill the registration form up to the recap page."
    ),
    MissionKind.hotel: (
        "On all.accor.com, find a hotel in {city} near the start of \"{race}\" for the night before {date} "
        "(check-in the day before, check-out on race day), free cancellation if possible{budget}. "
        "Go to the guest details page."
    ),
    MissionKind.transport: (
        "Find a round trip from {origin} to {city} arriving the day before {date} and returning on race day evening"
        "{budget}. Do not use SNCF Connect or OUIGO. Go to the passenger details page."
    ),
}


def build_task(kind: MissionKind, req: TripRequest) -> str:
    r = req.runner
    body = TASKS[kind].format(
        race=req.race_name, date=req.race_date.isoformat(), city=req.city, origin=req.origin_city,
        dist=f" ({req.distance_km:g} km)" if req.distance_km else "",
        start=req.race_url or "the official race website (search it)",
        budget=f", total under {req.max_budget_eur:g} EUR" if req.max_budget_eur else "",
    )
    return body + "\n" + RULES.format(first=r.first_name, last=r.last_name, email=r.email, birth=r.birth_date)


def check_answer(kind: MissionKind, raw: Any, req: TripRequest) -> tuple[MissionState, str | None, dict | None]:
    """Filtre cote serveur (pas seulement dans le prompt) : la reponse doit etre conforme au contrat et a la demande."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return S.failed, "answer_not_json", None
    try:
        a = ANSWER_MODELS[kind].model_validate(raw)
    except ValidationError as e:
        return S.failed, f"answer_invalid: {e.error_count()} erreur(s)", None
    parsed = a.model_dump(mode="json")
    if a.payment_submitted:
        return S.failed, "payment_submitted", parsed
    if a.blocked:
        return S.waiting_human, "blocked", parsed
    if req.max_budget_eur is not None and a.total_price_eur is not None and a.total_price_eur > req.max_budget_eur:
        return S.waiting_human, "over_budget", parsed
    dist = getattr(a, "distance_km", None)
    if kind == MissionKind.inscription and req.distance_km and dist and abs(dist - req.distance_km) > 0.1:
        return S.waiting_human, "wrong_distance", parsed
    if not a.ready_for_payment:
        return S.waiting_human, "incomplete", parsed
    return S.ready_to_pay, None, parsed


class CommandError(Exception):
    pass


class Orchestrator:
    def __init__(self, adapter: HAdapter, limit: int = 3, poll_s: float = 60.0, max_wait_s: float = 600.0,
                 check_quota: bool = True):
        self.adapter = adapter
        self.scheduler = SlotScheduler(limit, adapter.quota if check_quota else None, poll_s, max_wait_s)
        self.missions: dict[str, Mission] = {}
        self.requests: dict[str, TripRequest] = {}
        self.trips: dict[str, list[str]] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    # ----------------------------------------------------------- lifecycle

    async def create_trip(self, req: TripRequest) -> tuple[str, list[Mission]]:
        trip_id = uuid.uuid4().hex[:10]
        missions = []
        for kind in dict.fromkeys(req.kinds):
            m = Mission(id=f"{trip_id}-{kind.value}", trip_id=trip_id, kind=kind, task=build_task(kind, req))
            self.missions[m.id] = m
            self.requests[m.id] = req
            missions.append(m)
            await m.emit("state", {"from": None, "to": S.queued.value})
        self.trips[trip_id] = [m.id for m in missions]
        for m in missions:  # en parallele
            self.tasks[m.id] = asyncio.create_task(self._run(m))
        return trip_id, missions

    async def _run(self, m: Mission) -> None:
        spec = SessionSpec(kind=m.kind.value, task=m.task, answer_format=answer_format(m.kind))
        try:
            await self.scheduler.acquire(m.id)
            started = await self.adapter.start(spec)
            m.session_id, m.live_view_url = started.session_id, started.live_view_url
            await m.emit("live_view", {"url": m.live_view_url, "session_id": m.session_id})
            async for ev in self.adapter.events(m.session_id):
                await self._on_event(m, ev)
            if m.state in (S.queued, S.running):
                await m.transition(S.failed, "session_ended_without_answer")
        except asyncio.CancelledError:
            raise
        except SlotTimeout as e:
            await m.transition(S.failed, f"h_quota_timeout: {e}")
        except Exception as e:  # erreur reseau / SDK : on echoue proprement et on rend le slot
            log.exception("mission %s", m.id)
            if not m.terminal:
                await m.transition(S.failed, f"{type(e).__name__}")
            await self._cancel_session(m)
        finally:
            await self.scheduler.release(m.id)

    async def _cancel_session(self, m: Mission) -> None:
        if m.session_id:
            try:
                await self.adapter.cancel(m.session_id)
            except Exception as e:  # noqa: BLE001 - un cancel rate ne doit pas masquer l erreur
                log.warning("cancel %s: %s", m.session_id, type(e).__name__)

    async def _on_event(self, m: Mission, ev: AdapterEvent) -> None:
        if m.terminal:
            return
        d = ev.data
        if ev.type == "status":
            h = d.get("h_status")
            await m.emit("step", {"h_status": h})
            if h == "running" and m.state in (S.queued, S.waiting_human, S.ready_to_pay) and not m.pending_tool_call:
                await m.transition(S.running)
            elif h == "paused":
                await m.transition(S.waiting_human, "paused_by_user")
            elif h in ("failed", "timed_out"):
                await m.transition(S.failed, f"h_{h}" + (f": {d['error']}" if d.get("error") else ""))
            elif h == "interrupted":
                await m.transition(S.failed, "h_interrupted")
            elif h == "completed" and m.state in (S.queued, S.running):
                await m.transition(S.failed, "completed_without_answer")
        elif ev.type == "step":
            m.steps = d.get("steps") or (m.steps + (1 if d.get("thought") else 0))
            await m.emit("step", {**d, "steps": m.steps})
        elif ev.type == "screenshot":
            await m.emit("screenshot", d)
        elif ev.type == "live_view":
            if d.get("url"):
                m.live_view_url = d["url"]
            await m.emit("live_view", {"url": m.live_view_url, "session_id": m.session_id})
        elif ev.type == "human_needed":
            m.pending_tool_call = d.get("tool_call") or {"tool_name": "request_human", "args": d, "id": None}
            if m.state == S.queued:
                await m.transition(S.running)
            await m.transition(S.waiting_human, d.get("reason") or "agent_question", question=d.get("question"))
        elif ev.type == "answer":
            state, reason, parsed = check_answer(m.kind, d.get("answer"), self.requests[m.id])
            m.answer = parsed
            await m.emit("answer", {"answer": parsed, "verdict": state.value, "reason": reason})
            if m.state == S.queued:
                await m.transition(S.running)
            await m.transition(state, reason)
            if state == S.failed:
                await self._cancel_session(m)
        elif ev.type == "error":
            await m.emit("error", d)

    # ----------------------------------------------------------- commands

    def get(self, mid: str) -> Mission:
        if mid not in self.missions:
            raise KeyError(mid)
        return self.missions[mid]

    async def pause(self, mid: str) -> Mission:
        m = self.get(mid)
        if m.state != S.running or not m.session_id:
            raise CommandError(f"pause impossible en etat {m.state.value}")
        await self.adapter.pause(m.session_id)
        await m.transition(S.waiting_human, "paused_by_user")
        return m

    async def resume(self, mid: str) -> Mission:
        m = self.get(mid)
        if m.state != S.waiting_human or m.waiting_reason != "paused_by_user":
            raise CommandError(f"resume impossible en etat {m.state.value}/{m.waiting_reason}")
        await self.adapter.resume(m.session_id)
        await m.transition(S.running)
        return m

    async def message(self, mid: str, text: str) -> Mission:
        """Correction ou reponse de l'humain. Si l'agent attend request_human, le texte devient le resultat de l'outil."""
        m = self.get(mid)
        if m.terminal or not m.session_id:
            raise CommandError(f"message impossible en etat {m.state.value}")
        await m.emit("message", {"from": "human", "text": text})
        if m.pending_tool_call:
            call, m.pending_tool_call = m.pending_tool_call, None
            await self.adapter.answer_human(m.session_id, call, {"human_reply": text})
        else:
            await self.adapter.send_message(m.session_id, text)
        if m.state != S.running:
            await m.transition(S.running)
        return m

    async def cancel(self, mid: str) -> Mission:
        m = self.get(mid)
        if m.terminal:
            return m
        await m.transition(S.cancelled, "cancelled_by_user")
        await self._cancel_session(m)
        t = self.tasks.get(mid)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        return m

    async def shutdown(self) -> None:
        """Annule toutes les sessions encore vivantes (une session en pause ou idle garde son slot H)."""
        for mid in list(self.missions):
            await self.cancel(mid)
        await self.adapter.aclose()

    def public(self, m: Mission) -> MissionOut:
        return m.public(self.scheduler.position(m.id))
