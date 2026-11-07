"""Orchestration d'une mission : recherche, trois agents en parallèle, portail avant engagement."""

import asyncio
import contextlib
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from runai.app.ports import AgentRun, BrowserAgents, RaceSearch, Transcriber
from runai.app.scoping import ChatMessage, FakeScoper, Scope, Scoper, ScopeTurn
from runai.app.tasks import (
    STEP_LABELS,
    build_task,
    extract_budget_per_night,
    human_action,
)
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
from runai.safety import detect_stop_point, guard_task
from runai.tracing import TraceWriter

logger = logging.getLogger(__name__)

_BUDGET_QUESTION = re.compile(
    r"budget|prix\s+max|maximum|par\s+nuit|per\s+night", re.IGNORECASE
)
AGENT_STEPS = (StepKind.registration, StepKind.accommodation, StepKind.transport)
ACTIVE_STATUSES = {StepStatus.running, StepStatus.paused}


class MissionStatus(str, Enum):
    searching = "searching"
    running = "running"
    awaiting_human = "awaiting_human"
    completed = "completed"
    failed = "failed"


TERMINAL_STATUSES = {
    MissionStatus.awaiting_human,
    MissionStatus.completed,
    MissionStatus.failed,
}
QUESTION_TIMEOUT_ANSWER = "Pas de réponse de l'utilisateur : arrête-toi ici et résume."


class Mission(BaseModel):
    id: str
    query: str
    status: MissionStatus = MissionStatus.searching
    created_at: datetime = Field(default_factory=utcnow)
    scope: Scope | None = None
    race: Race | None = None
    steps: dict[StepKind, StepResult]
    questions: list[AgentQuestion] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None

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
        return data


class MissionError(Exception):
    pass


class MissionService:
    def __init__(
        self,
        search: RaceSearch,
        agents: BrowserAgents,
        transcriber: Transcriber,
        *,
        profile: RunnerProfile | None = None,
        traces_dir: Path | None = None,
        max_concurrency: int | None = 3,
        simulated: bool = False,
        question_timeout_s: float | None = None,
        scoper: Scoper | None = None,
    ):
        self.search = search
        self.agents = agents
        self.transcriber = transcriber
        self.scoper = scoper or FakeScoper(delay=0)
        self.profile = profile or RunnerProfile()
        self.traces_dir = traces_dir
        self.simulated = simulated
        self.question_timeout_s = (
            float(os.getenv("RUNAI_QUESTION_TIMEOUT_S", "600"))
            if question_timeout_s is None
            else question_timeout_s
        )
        self.missions: dict[str, Mission] = {}
        self._runs: dict[tuple[str, StepKind], AgentRun] = {}
        self._writers: dict[str, TraceWriter] = {}
        self._subscribers: dict[
            str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]
        ] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._pending_questions: dict[str, asyncio.Future[str]] = {}
        self._slots: contextlib.AbstractAsyncContextManager[Any] = (
            asyncio.Semaphore(max_concurrency)
            if max_concurrency is not None
            else contextlib.nullcontext()
        )
        self._loop: asyncio.AbstractEventLoop | None = None

    async def scope(self, messages: list[ChatMessage]) -> ScopeTurn:
        return await self.scoper.next_turn(messages)

    async def create(self, query: str, scope: Scope | None = None) -> Mission:
        self._loop = asyncio.get_running_loop()
        mission = Mission(
            id=uuid.uuid4().hex[:12],
            query=scope.query() if scope else query.strip(),
            scope=scope,
            steps={kind: StepResult(kind=kind) for kind in AGENT_STEPS},
        )
        self.missions[mission.id] = mission
        self._writers[mission.id] = TraceWriter(mission.id, traces_dir=self.traces_dir)
        self._record(
            mission,
            TraceEvent(
                source="app",
                type="mission_created",
                message=f"Mission créée : « {mission.query} »",
            ),
        )
        task = asyncio.create_task(self._run_mission(mission))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return mission

    def get(self, mission_id: str) -> Mission:
        try:
            return self.missions[mission_id]
        except KeyError:
            raise MissionError(f"Mission inconnue : {mission_id}") from None

    async def wait(self, mission_id: str) -> Mission:
        while not self.get(mission_id).is_terminal:
            await asyncio.sleep(0.01)
        return self.get(mission_id)

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        return await self.transcriber.transcribe(audio, content_type)

    async def ask(
        self, mission_id: str, kind: StepKind, question: str, options: list[str]
    ) -> str:
        mission = self.get(mission_id)
        duplicate = next(
            (
                item
                for item in reversed(mission.questions)
                if item.kind is kind
                and item.question == question
                and item.options == options
            ),
            None,
        )
        if duplicate is not None:
            if duplicate.answer is not None:
                return duplicate.answer
            future = self._pending_questions.get(duplicate.id)
            if future is not None:
                return await future
        if sum(item.kind is kind for item in mission.questions) >= 2:
            return "Tu as déjà posé deux questions. Utilise les informations disponibles et arrête-toi avant tout engagement."
        step = mission.steps[kind]
        question_model = AgentQuestion(
            id=uuid.uuid4().hex,
            kind=kind,
            question=question,
            options=options,
        )
        future = asyncio.get_running_loop().create_future()
        self._pending_questions[question_model.id] = future
        mission.questions.append(question_model)
        step.status = StepStatus.waiting_for_user
        self._record(
            mission,
            TraceEvent(
                source=f"agent:{kind.value}",
                type="question",
                message=question,
                data={
                    "step": kind.value,
                    "question_id": question_model.id,
                    "options": options,
                },
            ),
        )
        self._publish(mission, ("question", question_model.model_dump(mode="json")))
        timed_out = False
        try:
            try:
                answer = await asyncio.wait_for(
                    future, timeout=self.question_timeout_s
                )
            except TimeoutError:
                timed_out = True
                answer = QUESTION_TIMEOUT_ANSWER
            question_model.answer = answer
            question_model.answered_at = question_model.answered_at or utcnow()
            step.status = StepStatus.running
            self._record(
                mission,
                TraceEvent(
                    source="system" if timed_out else "human",
                    type="answer",
                    message=f"{STEP_LABELS[kind]} : « {answer} »",
                    data={
                        "step": kind.value,
                        "question_id": question_model.id,
                        "answer": answer,
                    },
                ),
            )
            self._publish(
                mission, ("answer", question_model.model_dump(mode="json"))
            )
            return answer
        finally:
            self._pending_questions.pop(question_model.id, None)

    def answer_question(
        self, mission_id: str, question_id: str, answer: str
    ) -> AgentQuestion:
        mission = self.get(mission_id)
        question = next(
            (item for item in mission.questions if item.id == question_id), None
        )
        if question is None:
            raise MissionError(f"Question inconnue : {question_id}")
        future = self._pending_questions.get(question_id)
        if question.answer is not None or future is None or future.done():
            raise MissionError(f"Question déjà répondue : {question_id}")
        question.answer = answer.strip()
        question.answered_at = utcnow()
        future.set_result(question.answer)
        return question

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
                message=f"{STEP_LABELS[kind]} : pause demandée",
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
                message=f"{STEP_LABELS[kind]} : reprise",
                data={"step": kind.value},
            ),
        )

    async def send_message(self, mission_id: str, kind: StepKind, text: str) -> None:
        mission, step, run = self._active(mission_id, kind)
        await run.send_message(guard_task(text))
        step.data.setdefault("messages", []).append(text)
        self._record(
            mission,
            TraceEvent(
                source="human",
                type="message",
                message=f"{STEP_LABELS[kind]} : « {text} »",
                data={"step": kind.value},
            ),
        )

    async def pause_all(self, mission_id: str) -> None:
        for kind in AGENT_STEPS:
            if self.get(mission_id).steps[kind].status is StepStatus.running:
                await self.pause(mission_id, kind)

    async def resume_all(self, mission_id: str) -> None:
        for kind in AGENT_STEPS:
            if self.get(mission_id).steps[kind].status is StepStatus.paused:
                await self.resume(mission_id, kind)

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
        mission = self.get(mission_id)
        step = mission.steps.get(kind)
        run = self._runs.get((mission_id, kind))
        if step is None or run is None or step.status not in ACTIVE_STATUSES:
            raise MissionError(f"Aucun agent actif pour l'étape {kind.value}")
        return mission, step, run

    def _record(self, mission: Mission, event: TraceEvent) -> None:
        """Peut être appelé depuis un autre thread (callback d'un SDK synchrone)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            self._loop.call_soon_threadsafe(self._record, mission, event)
            return
        mission.events.append(event)
        try:
            self._writers[mission.id].write(event)
        except OSError:
            logger.exception("Trace non écrite pour la mission %s", mission.id)
        step_name = event.data.get("step")
        if step_name in StepKind._value2member_map_ and event.source.startswith(
            "agent"
        ):
            step = mission.steps.get(StepKind(step_name))
            if step is not None:
                step.data["last_action"] = event.message
                if event.data.get("url"):
                    step.data["current_url"] = event.data["url"]
        self._publish(mission, ("trace", event.model_dump(mode="json")))

    def _publish_state(self, mission: Mission) -> None:
        self._publish(mission, ("mission", mission.snapshot()))

    def _publish(self, mission: Mission, message: tuple[str, dict[str, Any]]) -> None:
        for queue in self._subscribers.get(mission.id, ()):
            queue.put_nowait(message)
        if message[0] == "trace":
            self._publish_state(mission)

    async def _run_mission(self, mission: Mission) -> None:
        try:
            mission.race = await self.search.find_race(
                mission.scope.search_query() if mission.scope else mission.query
            )
        except Exception as error:  # noqa: BLE001 - toute erreur de brique doit remonter au portail
            mission.status = MissionStatus.failed
            mission.error = f"Recherche impossible : {error}"
            self._record(
                mission,
                TraceEvent(source="search", type="error", message=mission.error),
            )
            return
        self._record(
            mission,
            TraceEvent(
                source="search",
                type="race_found",
                message=f"Course trouvée : {mission.race.name} ({mission.race.city})",
                data={"sources": [str(source.url) for source in mission.race.sources]},
            ),
        )
        mission.status = MissionStatus.running
        await asyncio.gather(*(self._run_step(mission, kind) for kind in AGENT_STEPS))
        statuses = {step.status for step in mission.steps.values()}
        if StepStatus.stopped_before_commitment in statuses:
            mission.status = MissionStatus.awaiting_human
        elif StepStatus.failed in statuses:
            mission.status = MissionStatus.failed
        else:
            mission.status = MissionStatus.completed
        self._record(
            mission,
            TraceEvent(
                source="app",
                type="mission_done",
                message="Agents arrêtés : à vous de jouer au portail",
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
                    message=f"{STEP_LABELS[kind]} : agent lancé",
                    data={"step": kind.value},
                ),
            )
            try:
                task = build_task(
                    kind,
                    mission.race,
                    self.profile,
                    query=mission.query,
                    scope=mission.scope,
                )

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
                )
                self._runs[(mission.id, kind)] = run
                step.h_session_id = run.session_id
                self._set_live_view(step, run.live_view_url)
                self._publish_state(mission)
                result = await run.wait()
                result = self._validate_hotel_budget(mission, result)
            except Exception as error:  # noqa: BLE001
                step.status = StepStatus.failed
                step.error = str(error)
                self._record(
                    mission,
                    TraceEvent(
                        source="app",
                        type="step_failed",
                        message=f"{STEP_LABELS[kind]} : échec ({error})",
                        data={"step": kind.value},
                    ),
                )
                return
            finally:
                self._runs.pop((mission.id, kind), None)
        step = mission.steps[kind] = self._merge_result(step, result)
        self._record(
            mission,
            TraceEvent(
                source="app",
                type="step_done",
                message=f"{STEP_LABELS[kind]} : {step.summary or step.status.value}",
                data={"step": kind.value, "status": step.status.value},
            ),
        )

    @staticmethod
    def _validate_hotel_budget(mission: Mission, result: StepResult) -> StepResult:
        if result.kind is not StepKind.accommodation or result.status is StepStatus.failed:
            return result

        budgets = [
            parsed
            for question in mission.questions
            if question.kind is StepKind.accommodation
            and _BUDGET_QUESTION.search(question.question)
            and question.answer
            and (parsed := extract_budget_per_night(question.answer)) is not None
        ]
        query_budget = extract_budget_per_night(mission.query, require_context=True)
        if query_budget is not None:
            budgets.append(query_budget)
        budget = min(budgets) if budgets else None
        if result.price_eur is None and budget is None:
            return result
        if budget is None:
            result.status = StepStatus.failed
            result.error = "Le budget hôtel maximal par nuit n'a pas été fourni."
            result.summary = f"BUDGET MANQUANT — {result.summary or ''}".strip()
            return result
        if result.price_eur is None:
            result.status = StepStatus.failed
            result.error = "Le prix total de l'hôtel n'a pas pu être vérifié."
            result.summary = f"PRIX INCONNU — {result.summary or ''}".strip()
            return result

        total_limit = budget * 2
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
                f"HORS BUDGET : {result.price_eur:.2f} € dépasse "
                f"{total_limit:.2f} € ({budget:g} €/nuit × 2 nuits)."
            )
            result.summary = f"{result.error} {result.summary or ''}".strip()
        return result

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
                "h_session_id": result.h_session_id or step.h_session_id,
            }
        )
        if merged.stop_point is None and merged.summary:
            merged.stop_point = detect_stop_point(merged.summary)
        if merged.stop_point is not None and merged.status in {
            StepStatus.completed,
            StepStatus.running,
        }:
            merged.status = StepStatus.stopped_before_commitment
        return merged
