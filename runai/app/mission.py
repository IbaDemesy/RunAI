"""Orchestration d'une mission : recherche, trois agents en parallèle, portail avant engagement."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from runai.app.ports import AgentRun, BrowserAgents, RaceSearch, Transcriber
from runai.app.tasks import STEP_LABELS, build_task, human_action
from runai.models import (
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


class Mission(BaseModel):
    id: str
    query: str
    status: MissionStatus = MissionStatus.searching
    created_at: datetime = Field(default_factory=utcnow)
    race: Race | None = None
    steps: dict[StepKind, StepResult]
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
        max_concurrency: int = 3,
        simulated: bool = False,
    ):
        self.search = search
        self.agents = agents
        self.transcriber = transcriber
        self.profile = profile or RunnerProfile()
        self.traces_dir = traces_dir
        self.simulated = simulated
        self.missions: dict[str, Mission] = {}
        self._runs: dict[tuple[str, StepKind], AgentRun] = {}
        self._writers: dict[str, TraceWriter] = {}
        self._subscribers: dict[
            str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]
        ] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def create(self, query: str) -> Mission:
        self._loop = asyncio.get_running_loop()
        mission = Mission(
            id=uuid.uuid4().hex[:12],
            query=query.strip(),
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
            mission.race = await self.search.find_race(mission.query)
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

        async with self._semaphore:
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
                task = build_task(kind, mission.race, self.profile)
                run = await self.agents.start(
                    kind, task, mission.race, self.profile, on_event
                )
                self._runs[(mission.id, kind)] = run
                step.h_session_id = run.session_id
                self._set_live_view(step, run.live_view_url)
                self._publish_state(mission)
                result = await run.wait()
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
