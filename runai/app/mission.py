"""Mission orchestration: search, three parallel agents, and pre-commitment handoff."""

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, HttpUrl

from runai.app.capture_store import CaptureStore
from runai.app.mission_journey import project_journey
from runai.app.ports import (
    AgentRun,
    BrowserAgents,
    LogisticsSweeper,
    RaceSearch,
    Transcriber,
)
from runai.app.providers import UnavailableBrowserAgents
from runai.app.store import MissionStore, StoredMission
from runai.app.tasks import (
    STEP_LABELS,
    human_action,
)
from runai.config import get_settings
from runai.contracts.common import DataMode, Limitation
from runai.contracts.framing import FramingError, FramingSummary, FramingTurn
from runai.contracts.journey import JourneyPlan
from runai.contracts.mission import (
    EventEnvelope,
    HumanAnswer,
    MissionOutcome,
    MissionSnapshot,
    QuestionStatus,
    StepOutcome,
)
from runai.framing.holo import Phraser
from runai.framing.launch import LaunchPlan, plan_launch
from runai.h.human_questions import HumanQuestionRegistry
from runai.h.narrate import friendly_error, headline
from runai.models import (
    AgentQuestion,
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    TraceEvent,
    utcnow,
)
from runai.planning.recap_adapter import recap_from_journey
from runai.redaction import redact_secrets
from runai.safety import detect_stop_point, guard_task, release_attempt
from runai.search.checks import host_of
from runai.search.logistics_sweep import LogisticsSweep
from runai.tracing import TraceWriter

logger = logging.getLogger(__name__)

AGENT_STEPS = (StepKind.registration, StepKind.accommodation, StepKind.transport)
ACTIVE_STATUSES = {StepStatus.running, StepStatus.paused}

class MissionStatus(str, Enum):
    searching = "searching"
    running = "running"
    awaiting_human = "awaiting_human"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES = {
    MissionStatus.awaiting_human,
    MissionStatus.completed,
    MissionStatus.failed,
    MissionStatus.cancelled,
}
QUESTION_TIMEOUT_ANSWER = "No answer from the user: stop here and summarize."


class Mission(BaseModel):
    linkup: LogisticsSweep | None = None
    id: str
    query: str
    user_id: str | None = None
    status: MissionStatus = MissionStatus.searching
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    race: Race | None = None
    steps: dict[StepKind, StepResult]
    questions: list[AgentQuestion] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None
    plan: LaunchPlan | None = Field(default=None, exclude=True)
    envelopes: list[EventEnvelope] = Field(default_factory=list, exclude=True)
    limitations: list[Limitation] = Field(default_factory=list)
    framing_summary: FramingSummary | None = Field(default=None, exclude=True)
    framing_turns: list[FramingTurn] = Field(default_factory=list, exclude=True)
    journey: JourneyPlan | None = Field(default=None, exclude=True)
    read_only: bool = Field(default=False, exclude=True)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def snapshot(self, include_events: bool = False) -> dict[str, Any]:
        data = self.model_dump(
            mode="json", exclude=set() if include_events else {"events"}
        )
        data["steps"] = [
            {
                **step.model_dump(mode="json"),
                "label": STEP_LABELS[kind],
                "human_action": (
                    human_action(step.stop_point)
                    if step.status is StepStatus.stopped_before_commitment
                    else None
                ),
            }
            for kind, step in self.steps.items()
        ]
        return redact_secrets(data)


class MissionError(Exception):
    pass


class MissionNotFound(MissionError):
    pass


class MissionService:
    def __init__(
        self,
        search: RaceSearch,
        agents: BrowserAgents,
        transcriber: Transcriber,
        *,
        profile: RunnerProfile | None = None,
        phraser: Phraser | None = None,
        traces_dir: Path | None = None,
        max_concurrency: int | None = 3,
        simulated: bool = False,
        question_timeout_s: float | None = None,
        sweeper: LogisticsSweeper | None = None,
    ):
        self.search = search
        self.sweeper = sweeper
        self.agents = agents
        self.transcriber = transcriber
        self.profile = profile or RunnerProfile()
        self.phraser = phraser
        self.traces_dir = traces_dir
        self.capture_store = CaptureStore(traces_dir)
        self.simulated = simulated
        self.question_timeout_s = (
            float(os.getenv("RUNAI_QUESTION_TIMEOUT_S", "600"))
            if question_timeout_s is None
            else question_timeout_s
        )
        self.missions: dict[str, Mission] = {}
        self._store: MissionStore | None = None
        self._runs: dict[tuple[str, StepKind], AgentRun] = {}
        self._capture_runs: dict[tuple[str, StepKind], AgentRun] = {}
        self._writers: dict[str, TraceWriter] = {}
        self._subscribers: dict[
            str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]
        ] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self.questions = HumanQuestionRegistry()
        self._answer_lock = Lock()
        self._event_subscribers: dict[str, set[asyncio.Queue]] = {}
        self.providers = None
        self._mission_tasks: dict[str, asyncio.Task] = {}
        self._recaps = {}
        self._slots: contextlib.AbstractAsyncContextManager[Any] = (
            asyncio.Semaphore(max_concurrency) if max_concurrency is not None else contextlib.nullcontext()
        )
        self._loop: asyncio.AbstractEventLoop | None = None

    async def confirm(self, session) -> MissionSnapshot:
        plan = plan_launch(session, self.profile)
        if plan.mode is not DataMode.live and not session.selected_candidate_id:
            raise FramingError(
                f"No {plan.mode.value} fixture for this event; manual preparation only, no agent launched."
            )
        mission = await self.create(
            plan, summary=session.summary, turns=session.turns,
            user_id=getattr(session, "user_id", None),
        )
        return self.snapshot(mission.id)

    async def create(
        self,
        plan: LaunchPlan,
        *,
        summary: FramingSummary | None = None,
        turns: list[FramingTurn] | None = None,
        user_id: str | None = None,
    ) -> Mission:
        if not isinstance(plan, LaunchPlan):
            raise MissionError("Confirmed framing is required: /api/framings")
        self._loop = asyncio.get_running_loop()
        mission = Mission(
            id=uuid.uuid4().hex[:12], query=plan.brief.race_label, user_id=user_id,
            race=plan.race, plan=plan, limitations=list(plan.limitations),
            framing_summary=summary.model_copy(deep=True) if summary else None,
            framing_turns=list(turns or []),
            steps={kind: StepResult(
                kind=kind,
                status=StepStatus.pending if kind in plan.automated_steps() else StepStatus.completed,
                url=next((l.manual_url for l in step.limitations if l.manual_url), None),
                summary=None if kind in plan.automated_steps() else "Not automated: prepare manually.",
                data={"automation": step.automation.value},
            ) for kind, step in plan.steps.items()},
        )
        self.missions[mission.id] = mission
        self._writers[mission.id] = TraceWriter(mission.id, traces_dir=self.traces_dir)
        self._refresh_journey(mission)
        self._record(mission, TraceEvent(source="app", type="mission_created",
                                        message=f"Mission created: {mission.query}"))
        self._emit(mission, "snapshot", self.snapshot(mission.id).model_dump(mode="json"))
        self._save_mission(mission)
        task = asyncio.create_task(self._run_mission(mission))
        self._tasks.add(task)
        self._mission_tasks[mission.id] = task
        task.add_done_callback(self._tasks.discard)
        return mission

    @property
    def store(self) -> MissionStore:
        if self._store is None:
            self._store = MissionStore(self.traces_dir)
        return self._store

    def _save_mission(self, mission: Mission) -> None:
        if mission.plan is None:
            return
        self.store.save(mission.id, lambda: StoredMission(
            snapshot=self.snapshot(mission.id), envelopes=mission.envelopes,
            framing_summary=mission.framing_summary, framing_turns=mission.framing_turns,
            plan=mission.plan, created_at=mission.created_at, finished_at=mission.finished_at,
            journey=mission.journey,
        ), terminal=mission.is_terminal)

    async def rehydrate(self) -> None:
        for document in self.store.load():
            snapshot = document.snapshot
            if snapshot.mission_id in self.missions:
                continue
            mission = Mission(
                id=snapshot.mission_id, query=document.plan.brief.race_label,
                status=snapshot.status, created_at=document.created_at, finished_at=document.finished_at,
                race=snapshot.race,
                steps={step.kind: step for step in snapshot.steps}, plan=document.plan,
                events=[TraceEvent.model_validate(event.payload) for event in document.envelopes if event.type == "trace"],
                envelopes=document.envelopes, limitations=snapshot.limitations, error=snapshot.error,
                framing_summary=document.framing_summary, framing_turns=document.framing_turns,
                journey=document.journey, read_only=True,
            )
            self.missions[mission.id] = mission
            self.questions.questions.update({question.question_id: question for question in snapshot.questions})
            if mission.journey:
                self._recaps[(mission.id, mission.journey.revision)] = recap_from_journey(mission.journey)
            if not mission.is_terminal:
                message = "The server restarted while agents were running; relaunch the request."
                mission.status = MissionStatus.failed
                mission.finished_at = utcnow()
                mission.error = message
                mission.limitations.append(Limitation(code="server_restarted", message=message))
                for question in snapshot.questions:
                    if question.status is QuestionStatus.open:
                        question.status = QuestionStatus.cancelled
                        self._emit(mission, "question_resolved", question.model_dump(mode="json"))
                for step in mission.steps.values():
                    if step.h_session_id and step.status in {
                        StepStatus.running, StepStatus.paused, StepStatus.waiting_for_user,
                    }:
                        await self._cancel_restored_session(step)
                    if step.status in {StepStatus.pending, StepStatus.running, StepStatus.paused, StepStatus.waiting_for_user}:
                        step.status = StepStatus.failed
                        step.error = message
                self._emit(mission, "error", {"code": "server_restarted", "message": message})
                self._emit(mission, "mission_status", self.snapshot(mission.id).model_dump(mode="json"))
                self._publish_state(mission)

    async def _cancel_restored_session(self, step: StepResult) -> None:
        lifecycle = getattr(self.agents, "lifecycle", None)
        runner = getattr(lifecycle, "runner", None)
        key = step.data.get("h_key_name") or step.data.get("h_key") or step.data.get("agent_step", {}).get("h_key_name")
        for account in getattr(runner, "accounts", ()):
            if key and account.name != key:
                continue
            try:
                await account.client.sessions.cancel_session(step.h_session_id)
                return
            except Exception:  # noqa: BLE001 - recovery must continue after cancellation errors
                logger.warning("Could not cancel restored H session %s", step.h_session_id)

    def _writable(self, mission_id: str) -> Mission:
        mission = self.get(mission_id)
        if mission.read_only:
            raise MissionError("Restored missions are read-only; relaunch the request.")
        return mission

    def snapshot(self, mission_id: str) -> MissionSnapshot:
        mission = self.get(mission_id)
        plan = mission.plan
        labels = {
            "payment": "Stopped at the payment page",
            "consent": "Stopped before accepting the rules and medical certificate",
            "health_declaration": "Stopped before accepting the rules and medical certificate",
            "account_creation": "Stopped before creating an account",
            "submission": "Stopped before submitting the form",
        }
        steps = []
        automated = plan.automated_steps()
        for step in mission.steps.values():
            provenance = step.data.get("provenance", {})
            mode = provenance.get("mode", plan.mode.value) if isinstance(provenance, dict) else plan.mode.value
            steps.append(StepOutcome(
                kind=step.kind, status=step.status,
                headline=(step.data.get("headline") or step.summary or step.status.value.replace("_", " ").capitalize())
                if step.kind in automated else "Not automated — plan this step yourself",
                stop_point=step.stop_point,
                stop_point_label=labels.get(step.stop_point) if step.kind in automated else "Not automated — plan this step yourself",
                handoff_url=str(step.url) if step.url else (
                    str(mission.race.registration_url)
                    if step.kind is StepKind.registration and mission.race and mission.race.registration_url else None
                ),
                price=f"€{step.price_eur:g}" if step.price_eur is not None else None,
                price_eur=step.price_eur,
                provider="h" if plan.mode is DataMode.live else mode,
            ))
        automated_outcomes = [step for step in steps if step.kind in automated]
        ready = sum(step.status in {StepStatus.stopped_before_commitment, StepStatus.completed} for step in automated_outcomes)
        if mission.status is MissionStatus.cancelled:
            state = "cancelled"
        elif not mission.is_terminal:
            state = "in_progress"
        elif automated_outcomes and ready == len(automated_outcomes):
            state = "prepared"
        elif ready:
            state = "partial"
        else:
            state = "failed"
        titles = {
            "in_progress": "Your trip is being prepared",
            "prepared": "Your trip is prepared — nothing has been paid",
            "partial": "Your trip is partially prepared — nothing has been paid",
            "failed": "Your trip could not be prepared — nothing has been paid",
            "cancelled": "Your trip preparation was cancelled — nothing has been paid",
        }
        prices = [step.price_eur for step in steps if step.price_eur is not None]
        budget = mission.journey.budget if mission.journey else None
        total = budget.known_total if budget else sum(prices) if prices else None
        costs_complete = budget.complete if budget else bool(prices) and len(prices) == len(steps)
        cap = plan.brief.budget_total_eur
        budget_status = "no_cap" if cap is None else (
            "over_cap" if total is not None and total > cap else
            "within_cap" if costs_complete else "unknown"
        )
        outcome = MissionOutcome(
            state=state, title=titles[state], steps=steps,
            total=f"€{total:g}" if total is not None else None, total_eur=total,
            budget_cap_eur=cap, budget_status=budget_status,
            recap_urls={fmt: f"/api/missions/{mission.id}/recap.{fmt}?revision={mission.journey.revision}"
                        for fmt in ("html", "pdf", "ics")} if mission.journey else {},
            elapsed_s=max(0, ((mission.finished_at or utcnow()) - mission.created_at).total_seconds()),
        )
        lifecycle = getattr(self.agents, "lifecycle", None)
        slots = lifecycle.slots() if lifecycle is not None else {}
        snapshot = MissionSnapshot(
            mission_id=mission.id, framing_id=plan.framing_id,
            framing_revision=plan.revision, mode=plan.mode,
            status=mission.status.value, sequence=len(mission.envelopes),
            race=mission.race, steps=self._snapshot_steps(mission),
            linkup=mission.linkup,
            questions=[q for q in self.questions.questions.values() if q.mission_id == mission.id],
            limitations=mission.limitations, error=mission.error,
            journey_revision=mission.journey.revision if mission.journey else None,
            budget=mission.journey.budget if mission.journey else None,
            outcome=outcome,
            h_slots=slots,
            agents_busy=sum(slot["active"] for slot in slots.values()),
            agents_total=sum(slot["max"] for slot in slots.values()),
            partners={
                "h": getattr(self.agents, "agent", None) or get_settings().h_agent,
                "linkup": not self.simulated and type(self.search).__name__ == "RealRaceSearch",
                "gladia": not self.simulated and type(self.transcriber).__name__ == "RealTranscriber",
                "holo": type(self.phraser).__name__,
            },
        )
        return MissionSnapshot.model_validate(redact_secrets(snapshot.model_dump(mode="json")))

    @staticmethod
    def _snapshot_steps(mission: Mission) -> list[StepResult]:
        if mission.read_only:
            return list(mission.steps.values())
        return [step.model_copy(update={"live_view_url": step.live_view_url or step.data.get("share_url"), "data": {**step.data, "history": [
            {"at": event.at.isoformat(), "message": event.message, "type": event.type}
            for event in mission.events
            if event.data.get("step") == step.kind.value
            and (event.source == "h" or event.source.startswith("agent"))
        ]}}) for step in mission.steps.values()]

    def _refresh_journey(self, mission: Mission) -> None:
        if mission.framing_summary is None:
            return
        try:
            plan, questions = project_journey(mission)
        except (ValueError, TypeError, KeyError) as error:
            limitation = Limitation(code="journey_data_invalid", message=redact_secrets(str(error)))
            if limitation not in mission.limitations:
                mission.limitations.append(limitation)
                self._emit(mission, "error", limitation.model_dump(mode="json"))
            return
        plan = JourneyPlan.model_validate(redact_secrets(plan.model_dump(mode="json")))
        if mission.journey is None or plan.revision != mission.journey.revision:
            mission.journey = plan
            self._recaps[(mission.id, plan.revision)] = recap_from_journey(plan)
            self._emit(mission, "journey_revised", {"revision": plan.revision})
            self._emit(mission, "budget_updated", plan.budget.model_dump(mode="json"))
        for question in questions:
            qid = f"eligibility-{mission.id}-{question.id}"
            if qid in self.questions.questions:
                continue
            manual = AgentQuestion(id=qid, kind=StepKind.registration, question=question.text,
                                   options=["I will check on the official site"])
            wrapped = self.questions.open(manual, mission.id, mission.plan.revision,
                                          ttl=self.question_timeout_s)
            self.questions.questions[qid].reason = f"eligibility: Manual action only. {question.detail or ''} {question.source_url or ''} {question.deadline or ''}"
            wrapped = self.questions.get(qid)
            self._emit(mission, "question_opened", wrapped.model_dump(mode="json"))

    def get_journey(self, mission_id: str) -> JourneyPlan:
        mission = self.get(mission_id)
        if mission.journey is None:
            raise MissionError("Trip unavailable: not enough confirmed data yet")
        return mission.journey.model_copy(deep=True)

    def get_recap(self, mission_id: str, revision: int | None = None):
        plan = self.get_journey(mission_id)
        try:
            return self._recaps[(mission_id, plan.revision if revision is None else revision)]
        except KeyError:
            raise MissionError("Recap revision unavailable") from None

    def _emit(self, mission: Mission, type_: str, payload: dict) -> None:
        envelope = EventEnvelope.build(mission.id, len(mission.envelopes) + 1, type_, payload)
        source = str(payload.get("source", "")) if type_ == "trace" else type_
        if source == "h" or source.startswith("agent:") or type_ in {"agent_step", "question_opened"}:
            envelope.provider = "h"
        elif source == "human" or type_ == "question_resolved":
            envelope.provider = "human"
        elif source in {"framing", "holo"}:
            envelope.provider = "holo"
        elif source in {"search", "linkup", "linkup_call"}:
            envelope.provider = "linkup"
        elif source in {"transcribe", "gladia", "voice"}:
            envelope.provider = "gladia"
        else:
            envelope.provider = "app"
        mission.envelopes.append(envelope)
        for queue in self._event_subscribers.get(mission.id, ()):
            queue.put_nowait(envelope)

    async def subscribe_events(self, mission_id: str, last_event_id: str | None = None):
        mission = self.get(mission_id)
        sequence = 0
        if last_event_id:
            prefix, _, raw = last_event_id.rpartition(":")
            try:
                sequence = int(raw)
            except ValueError:
                raise MissionError("Invalid Last-Event-ID") from None
            if prefix != mission_id or not 0 <= sequence <= len(mission.envelopes):
                raise MissionError("Invalid Last-Event-ID")
        queue = asyncio.Queue()
        self._event_subscribers.setdefault(mission_id, set()).add(queue)
        try:
            for event in tuple(mission.envelopes[sequence:]):
                yield event
            if mission.is_terminal:
                while not queue.empty():
                    yield queue.get_nowait()
                return
            while True:
                event = await queue.get()
                yield event
                if event.type == "mission_status" and event.payload["status"] in {s.value for s in TERMINAL_STATUSES}:
                    return
        finally:
            self._event_subscribers[mission_id].discard(queue)

    async def cancel(self, mission_id: str) -> None:
        mission = self._writable(mission_id)
        if mission.status is MissionStatus.cancelled:
            return
        mission.status = MissionStatus.cancelled
        mission.finished_at = utcnow()
        self.questions.cancel_mission(mission_id)
        lifecycle = getattr(self.agents, "lifecycle", None)
        if lifecycle:
            await lifecycle.cancel_all(mission_id)
        for (mid, _), run in list(self._runs.items()):
            if mid == mission_id and hasattr(run, "cancel"):
                await run.cancel()
        task = self._mission_tasks.get(mission_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        mission.limitations.append(Limitation(code="h_cancelled", message="Mission cancelled; no new launches."))
        mission.finished_at = utcnow()
        self._emit(mission, "mission_outcome", self.snapshot(mission.id).outcome.model_dump(mode="json"))
        self._emit(mission, "mission_status", self.snapshot(mission.id).model_dump(mode="json"))
        self._publish_state(mission)

    def get(self, mission_id: str) -> Mission:
        try:
            return self.missions[mission_id]
        except KeyError:
            raise MissionNotFound(f"Unknown mission: {mission_id}") from None

    async def wait(self, mission_id: str) -> Mission:
        while not self.get(mission_id).is_terminal:
            await asyncio.sleep(0.01)
        return self.get(mission_id)

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        return await self.transcriber.transcribe(audio, content_type)

    @staticmethod
    def _question_context(mission: Mission) -> dict[str, str]:
        if mission.plan is None:
            return {}
        brief = mission.plan.brief
        known = {"course": brief.race_label}
        dates = []
        if brief.race_date:
            dates.append(brief.race_date.isoformat())
        if brief.arrival and brief.departure:
            dates.append(f"{brief.arrival.isoformat()} → {brief.departure.isoformat()}")
        if dates:
            known["dates"] = " ; ".join(dates)
        if brief.origin:
            known["origin"] = brief.origin
        if brief.budget_open:
            known["budget"] = "no limit"
        else:
            budget = []
            if brief.budget_total_eur is not None:
                budget.append(f"{brief.budget_total_eur:g} € total")
            if brief.budget_per_night_eur is not None:
                budget.append(f"{brief.budget_per_night_eur:g} € per night")
            if budget:
                known["budget"] = ", ".join(budget)
        if brief.transport_mode:
            known["transport"] = brief.transport_mode
        return known

    async def ask(self, mission_id: str, kind: StepKind, question: str, options: list[str]) -> str:
        mission = self._writable(mission_id)
        if mission.status is MissionStatus.cancelled:
            raise MissionError("Mission cancelled")
        display_text = question
        if self.phraser:
            try:
                phrased = await self.phraser.phrase(
                    mission.framing_turns, question, self._question_context(mission)
                )
                if isinstance(phrased, str) and phrased.strip():
                    display_text = phrased
            except Exception:  # noqa: BLE001
                display_text = question
        question_model = AgentQuestion(
            id=uuid.uuid4().hex,
            kind=kind,
            question=question,
            display_text=display_text,
            options=options,
        )
        mission.questions.append(question_model)
        step = mission.steps[kind]
        run = self._runs.get((mission_id, kind))
        if run:
            step.h_session_id = run.session_id
            self._set_agent_views(step, run)
        wrapped = self.questions.open(question_model, mission_id, mission.plan.revision,
                                      step.h_session_id, ttl=self.question_timeout_s)
        step.status = StepStatus.waiting_for_user
        self._record(mission, TraceEvent(source=f"agent:{kind.value}", type="question", message=question,
                                       data={"step": kind.value, "question_id": question_model.id, "options": options}))
        self._publish(mission, ("question", question_model.model_dump(mode="json")))
        self._emit(mission, "question_opened", wrapped.model_dump(mode="json"))
        try:
            answer = await self.questions.wait_answer(question_model.id)
            return answer
        finally:
            resolved = self.questions.get(question_model.id)
            question_model.answer = resolved.answer
            question_model.answered_at = utcnow()
            if mission.status is not MissionStatus.cancelled:
                step.status = StepStatus.running
            self._emit(mission, "question_resolved", resolved.model_dump(mode="json"))
            self._record(mission, TraceEvent(source="human", type="answer",
                                           message=resolved.answer or resolved.status.value,
                                           data={"step": kind.value, "question_id": question_model.id}))
            self._publish(mission, ("answer", question_model.model_dump(mode="json")))

    def answer_question(self, mission_id: str, question_id: str, answer: HumanAnswer):
        mission = self._writable(mission_id)
        with self._answer_lock:
            self._ensure_not_cancelled(mission)
            question = self.questions.get(question_id)
            if question.choices and answer.answer not in question.choices:
                raise MissionError("Answer must be one of the available options")
            result = self.questions.answer(question_id, mission_id, answer)
        if question.status is QuestionStatus.open and (
            (result.reason or "").startswith("eligibility:") or question_id.startswith("eligibility-")
        ):
            self._emit(mission, "question_resolved", result.model_dump(mode="json"))
        self._save_mission(mission)
        return result

    async def pause(self, mission_id: str, kind: StepKind) -> None:
        mission, step, run = self._active(mission_id, kind)
        if step.status is not StepStatus.running:
            return
        await run.pause()
        step.status = StepStatus.paused
        self._record(
            mission,
            TraceEvent(
                source="human",
                type="pause",
                message=f"{STEP_LABELS[kind]}: pause requested",
                data={"step": kind.value},
            ),
        )

    async def resume(self, mission_id: str, kind: StepKind) -> None:
        mission, step, run = self._active(mission_id, kind)
        if step.status is not StepStatus.paused:
            return
        await run.resume()
        step.status = StepStatus.running
        self._record(
            mission,
            TraceEvent(
                source="human",
                type="resume",
                message=f"{STEP_LABELS[kind]}: resumed",
                data={"step": kind.value},
            ),
        )

    async def send_message(self, mission_id: str, kind: StepKind, text: str) -> None:
        mission, step, run = self._active(mission_id, kind)
        if reason := release_attempt(text):
            self._record(
                mission,
                TraceEvent(
                    source="human",
                    type="message_refused",
                    message=reason,
                    data={"step": kind.value},
                ),
            )
            raise MissionError(reason)
        if run.session_id is None:
            raise MissionError("H session is still queued; try again after it starts.")
        await run.send_message(guard_task(text))
        step.data.setdefault("messages", []).append(text)
        self._record(
            mission,
            TraceEvent(
                source="human",
                type="message",
                message=f"{STEP_LABELS[kind]}: {text}",
                data={"step": kind.value},
            ),
        )

    async def pause_all(self, mission_id: str) -> None:
        self._writable(mission_id)
        self._ensure_not_cancelled(self.get(mission_id))
        for kind in AGENT_STEPS:
            if self.get(mission_id).steps[kind].status is StepStatus.running:
                await self.pause(mission_id, kind)

    async def resume_all(self, mission_id: str) -> None:
        self._writable(mission_id)
        self._ensure_not_cancelled(self.get(mission_id))
        for kind in AGENT_STEPS:
            if self.get(mission_id).steps[kind].status is StepStatus.paused:
                await self.resume(mission_id, kind)

    @staticmethod
    def _ensure_not_cancelled(mission: Mission) -> None:
        if mission.status is MissionStatus.cancelled:
            raise MissionError("Mission is cancelled")

    def find_session(self, session_id: str) -> tuple[Mission, StepResult] | None:
        for mission in self.missions.values():
            for step in mission.steps.values():
                if step.h_session_id == session_id:
                    return mission, step
        return None

    async def subscribe(
        self, mission_id: str
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        mission = self.get(mission_id)
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._subscribers.setdefault(mission_id, set()).add(queue)
        try:
            yield "snapshot", mission.snapshot(include_events=True)
            if mission.is_terminal:
                return
            while True:
                name, data = await queue.get()
                yield name, data
                if (
                    name == "mission"
                    and MissionStatus(data["status"]) in TERMINAL_STATUSES
                ):
                    return
        finally:
            self._subscribers[mission_id].discard(queue)

    def _active(
        self, mission_id: str, kind: StepKind
    ) -> tuple[Mission, StepResult, AgentRun]:
        mission = self._writable(mission_id)
        step = mission.steps.get(kind)
        run = self._runs.get((mission_id, kind))
        self._ensure_not_cancelled(mission)
        if step is None or run is None or step.status not in ACTIVE_STATUSES | {StepStatus.waiting_for_user}:
            raise MissionError(f"No active agent for step {kind.value}")
        return mission, step, run

    def _record(self, mission: Mission, event: TraceEvent) -> None:
        """May be called from another thread by a synchronous SDK callback."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            self._loop.call_soon_threadsafe(self._record, mission, event)
            return
        event = TraceEvent.model_validate(redact_secrets(event.model_dump(mode="json")))
        mission.events.append(event)
        self._emit(mission, "trace", event.model_dump(mode="json"))
        try:
            self._writers[mission.id].write(event)
        except OSError:
            logger.exception("Trace not written for mission %s", mission.id)
        step_name = event.data.get("step")
        if step_name in StepKind._value2member_map_:
            step = mission.steps.get(StepKind(step_name))
            if step is not None:
                if text := headline(event):
                    step.data["headline"] = text
                if event.source == "h" or event.source.startswith("agent"):
                    if session_id := event.data.get("h_session_id"):
                        step.h_session_id = session_id
                    if event.message and event.type != "AgentRunStatusChangeEvent":
                        step.data["last_action"] = "Live view available" if event.type == "LiveViewUrlEvent" else event.message
                    if run := self._runs.get((mission.id, StepKind(step_name))):
                        self._set_agent_views(step, run)
                        if observation := getattr(run, "browser_observation", None):
                            step.data["browser_observation"] = observation
                            if event.data.get("mode") != "replay":
                                self.capture_store.schedule(mission.id, step.kind, observation, run)
                            self._capture_runs[(mission.id, StepKind(step_name))] = run
                    if event.data.get("url"):
                        step.data["current_url"] = event.data["url"]
                    if event.type == "AgentEvent.policy_event":
                        payload = event.data.get("event", {}).get("data", {})
                        thought = payload.get("content") or payload.get("reasoning_content") or event.message
                        step.data["agent_thought"] = redact_secrets(str(thought or ""))[:160]
                    if event.type == "AgentEvent.observation_event":
                        self._agent_step(mission, step, event)
        self._publish(mission, ("trace", event.model_dump(mode="json")))

    def _agent_step(self, mission: Mission, step: StepResult, event: TraceEvent) -> None:
        run = self._runs.get((mission.id, step.kind))
        raw = getattr(getattr(run, "job", None), "run", None) or getattr(run, "run", run)
        metadata = event.data.get("event", {}).get("data", {}).get("metadata") or {}
        url = metadata.get("url") or event.data.get("url")
        try:
            parsed = urlsplit(url or "")
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            host = parsed.hostname
        except ValueError:
            url, host = None, None
        observation = getattr(run, "browser_observation", None) or getattr(raw, "browser_observation", None) or {}
        metrics = getattr(raw, "metrics", {}) or {}
        revision = observation.get("revision")
        payload = redact_secrets({
            "step": step.kind.value,
            "n": step.data.get("agent_step", {}).get("n", 0) + 1,
            "url": url or None, "host": host,
            "title": str(metadata.get("title") or "")[:80],
            "thought": step.data.get("agent_thought", ""),
            "screenshot_revision": revision,
            "screenshot_url": f"/api/missions/{mission.id}/steps/{step.kind.value}/screenshot" if revision else None,
            "steps": metrics.get("steps"), "total_cost": metrics.get("total_cost"),
            "elapsed_s": max(0, (event.at - mission.created_at).total_seconds()),
            "agent": getattr(self.agents, "agent", None) or get_settings().h_agent,
            "h_key_name": getattr(getattr(raw, "account", None), "name", None),
            "provider": "h", "at": event.at.isoformat(),
        })
        step.data["agent_step"] = payload
        self._emit(mission, "agent_step", payload)

    def _publish_state(self, mission: Mission) -> None:
        self._publish(mission, ("mission", mission.snapshot()))
        self._emit(mission, "step", {"steps": [step.model_dump(mode="json") for step in self._snapshot_steps(mission)]})
        self._save_mission(mission)

    def _publish(self, mission: Mission, message: tuple[str, dict[str, Any]]) -> None:
        for queue in self._subscribers.get(mission.id, ()):
            queue.put_nowait(message)
        if message[0] == "trace":
            self._publish_state(mission)

    async def _run_mission(self, mission: Mission) -> None:
        mission.status = MissionStatus.running
        if self.sweeper is not None and mission.plan.mode is DataMode.live:
            try:
                sweep = await asyncio.wait_for(
                    self.sweeper.sweep(mission.race, mission.plan.brief, timeout_s=15), 15.1
                )
                mission.linkup = sweep
                self._record(mission, TraceEvent(
                    source="linkup", type="linkup_sweep",
                    message=f"Linkup: {len(sweep.hotels)} hotels, {len(sweep.transport_operators)} operators in {sweep.latency_s:.1f} s",
                    data=sweep.model_dump(mode="json"),
                ))
                registration = mission.plan.steps.get(StepKind.registration)
                if registration and sweep.race_form_url and host_of(sweep.race_form_url) == host_of(registration.start_url):
                    registration.start_url = str(sweep.race_form_url)
                if not sweep.calls:
                    mission.limitations.append(Limitation(
                        code="linkup_sweep_unavailable", message="Linkup logistics sweep timed out."
                    ))
            except Exception:  # noqa: BLE001 - optional discovery must never block agents
                mission.limitations.append(Limitation(
                    code="linkup_sweep_unavailable", message="Linkup logistics sweep unavailable."
                ))
        await asyncio.gather(*(self._run_step(mission, kind) for kind in mission.plan.automated_steps()))
        if mission.status is MissionStatus.cancelled:
            return
        statuses = {step.status for step in mission.steps.values()}
        if StepStatus.stopped_before_commitment in statuses:
            mission.status = MissionStatus.awaiting_human
        elif StepStatus.failed in statuses:
            mission.status = MissionStatus.failed
        else:
            mission.status = MissionStatus.completed
        mission.finished_at = utcnow()
        self._emit(mission, "mission_outcome", self.snapshot(mission.id).outcome.model_dump(mode="json"))
        self._emit(mission, "mission_status", self.snapshot(mission.id).model_dump(mode="json"))
        self._record(
            mission,
            TraceEvent(
                source="app",
                type="mission_done",
                message="Agents stopped: over to you at the handoff",
            ),
        )

    async def _run_step(self, mission: Mission, kind: StepKind) -> None:
        step = mission.steps[kind]
        assert mission.race is not None

        def on_event(event: TraceEvent) -> None:
            event.data.setdefault("step", kind.value)
            self._record(mission, event)

        async with self._slots:
            step.status = StepStatus.running
            self._record(
                mission,
                TraceEvent(
                    source="app",
                    type="step_started",
                    message=f"{STEP_LABELS[kind]}: agent launched",
                    data={"step": kind.value},
                ),
            )
            try:
                step_plan = mission.plan.steps[kind]
                task = step_plan.task

                async def ask_user(question: str, options: list[str]) -> str:
                    return await self.ask(mission.id, kind, question, options)

                run = await self.agents.start(
                    kind,
                    task,
                    mission.race,
                    self.profile,
                    on_event,
                    ask_user=ask_user,
                    mission_id=mission.id,
                    query=mission.query,
                    start_url=step_plan.start_url,
                    brief=mission.plan.brief,
                )
                self._runs[(mission.id, kind)] = run
                step.h_session_id = run.session_id
                self._set_agent_views(step, run)
                self._publish_state(mission)
                result = await run.wait()
                step.h_session_id = run.session_id
                self._set_agent_views(step, run)
                result = self._validate_hotel_budget(mission, result)
            except Exception as error:  # noqa: BLE001
                step.status = StepStatus.failed
                step.error = redact_secrets(str(error))
                user_error = friendly_error(step.error)
                step.data["error_user"] = user_error
                step.data["headline"] = user_error
                code = "h_key_missing" if isinstance(self.agents, UnavailableBrowserAgents) else getattr(error, "code", "agent_error")
                limitation = Limitation(code=code, message=user_error, step=kind.value)
                mission.limitations.append(limitation)
                self._emit(mission, "error", limitation.model_dump(mode="json"))
                self._record(
                    mission,
                    TraceEvent(
                        source="app",
                        type="step_failed",
                        message=f"{STEP_LABELS[kind]}: {user_error}",
                        data={"step": kind.value},
                    ),
                )
                self._refresh_journey(mission)
                return
            finally:
                self._runs.pop((mission.id, kind), None)
        step = mission.steps[kind] = self._merge_result(step, result)
        if step.status is StepStatus.stopped_before_commitment:
            step.data["headline"] = "Prepared — finish it yourself on the official site"
        elif step.status is StepStatus.completed:
            step.data["headline"] = "Done"
        elif step.status is StepStatus.failed and step.error:
            step.data.setdefault("error_user", friendly_error(step.error))
        self._refresh_journey(mission)
        self._record(
            mission,
            TraceEvent(
                source="app",
                type="step_done",
                message=f"{STEP_LABELS[kind]}: {step.summary or step.status.value}",
                data={"step": kind.value, "status": step.status.value},
            ),
        )

    @staticmethod
    def _validate_hotel_budget(mission: Mission, result: StepResult) -> StepResult:
        if result.kind is not StepKind.accommodation or result.status is StepStatus.failed:
            return result

        brief = mission.plan.brief if mission.plan else None
        if brief is None or brief.nights is None:
            return result
        budget = brief.budget_per_night_eur
        total_limit = brief.budget_total_eur
        if budget is not None:
            per_night_limit = budget * brief.nights
            total_limit = min(total_limit, per_night_limit) if total_limit is not None else per_night_limit
        if total_limit is None:
            return result
        if result.price_eur is None:
            result.status = StepStatus.failed
            result.error = "The total hotel price could not be verified."
            return result
        result.data.update(
            {
                "budget_max_per_night_eur": budget,
                "budget_max_total_eur": total_limit,
                "over_budget": result.price_eur > total_limit,
            }
        )
        if result.price_eur > total_limit:
            result.status = StepStatus.failed
            result.error = (
                f"OVER BUDGET: {result.price_eur:.2f} € exceeds "
                f"{total_limit:.2f} € for {brief.nights} nights."
            )
            result.summary = f"{result.error} {result.summary or ''}".strip()
        return result

    @staticmethod
    def _set_agent_views(step: StepResult, run: AgentRun) -> None:
        share_url = getattr(run, "share_url", None)
        if share_url:
            step.data["share_url"] = share_url
        MissionService._set_live_view(step, getattr(run, "live_view_url", None) or (share_url if step.live_view_url is None else None))
        url = getattr(run, "agent_view_url", None)
        if url and url.startswith(("http://", "https://")):
            step.agent_view_url = HttpUrl(url)

    @staticmethod
    def _set_live_view(step: StepResult, url: str | None) -> None:
        if not url:
            return
        if url.startswith(("http://", "https://")):
            step.live_view_url = HttpUrl(url)
        else:
            step.data["live_view_path"] = url

    @staticmethod
    def _merge_result(step: StepResult, result: StepResult) -> StepResult:
        merged = result.model_copy(
            update={
                "kind": step.kind,
                "data": {**step.data, **result.data},
                "live_view_url": result.live_view_url or step.live_view_url,
                "agent_view_url": result.agent_view_url or step.agent_view_url,
                "h_session_id": result.h_session_id or step.h_session_id,
            }
        )
        if merged.stop_point is None and merged.summary:
            merged.stop_point = detect_stop_point(merged.summary, ignore_negated=True)
        if merged.stop_point is not None and merged.status in {
            StepStatus.completed,
            StepStatus.running,
        }:
            merged.status = StepStatus.stopped_before_commitment
        return merged
