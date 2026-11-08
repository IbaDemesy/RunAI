"""Replay : rejoue une trace enregistrée (schéma `replay.v1`), étiquetée `replay`, jamais `live`.

Aucun appel réseau : la recherche, la voix et les agents renvoient ce qui a été enregistré,
avec `StepResult.data["provenance"]["mode"] == "replay"` et sans vue live.
"""

import asyncio
import base64
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, model_serializer

from runai.app.capture_store import CaptureStore
from runai.app.ports import AskUser, EventSink
from runai.app.providers import ProviderUnavailableError, provenance_data
from runai.contracts.common import DataMode, ProvenanceKind
from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    TraceEvent,
)
from runai.redaction import redact_secrets


class ReplayQuestion(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)


class ReplayStep(BaseModel):
    result: StepResult
    events: list[TraceEvent] = Field(default_factory=list)
    questions: list[ReplayQuestion] = Field(default_factory=list)
    screenshots: list[dict[str, Any]] = Field(default_factory=list)


class ReplayTrace(BaseModel):
    _base_dir: Path = PrivateAttr(default_factory=Path.cwd)
    schema_version: Literal["replay.v1"] = "replay.v1"
    label: str
    recorded_mode: DataMode = DataMode.live
    race: Race | None = None
    transcript: str | None = None
    steps: dict[StepKind, ReplayStep] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def serialize_trace(self, handler):
        return redact_secrets(handler(self))

    @classmethod
    def load(cls, path: Path) -> "ReplayTrace":
        trace = cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        trace._base_dir = Path(path).resolve().parent
        return trace

    def dump(self, path: Path, *, inline: bool = False) -> None:
        trace = self.model_copy(deep=True)
        for step in trace.steps.values():
            for frame in step.screenshots:
                if not frame["path"].startswith("data:"):
                    source = self._base_dir / frame["path"]
                    if inline:
                        frame["path"] = "data:image/png;base64," + base64.b64encode(source.read_bytes()).decode("ascii")
                    else:
                        frame["path"] = os.path.relpath(source, Path(path).resolve().parent)
        Path(path).write_text(trace.model_dump_json(indent=2), encoding="utf-8")

    def attach_screenshots(self, mission_id: str, traces_dir: Path, *, inline: bool = False) -> None:
        store = CaptureStore(traces_dir)
        self._base_dir = Path(traces_dir).resolve()
        for kind, step in self.steps.items():
            step.screenshots = []
            for entry in store.index(mission_id, kind.value):
                path = store.frame_path(mission_id, kind.value, entry["revision"])
                resource = str(path.relative_to(self._base_dir))
                if inline:
                    resource = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
                step.screenshots.append({**entry, "path": resource})

    @classmethod
    def from_mission_snapshot(
        cls, snapshot: dict[str, Any], label: str | None = None
    ) -> "ReplayTrace":
        """Construit une trace depuis `Mission.snapshot(include_events=True)`."""
        snapshot = redact_secrets(snapshot)
        steps: dict[StepKind, ReplayStep] = {}
        events = [TraceEvent.model_validate(e) for e in snapshot.get("events", [])]
        questions = snapshot.get("questions", [])
        for raw in snapshot.get("steps", []):
            data = {k: v for k, v in raw.items() if k not in ("label", "human_action")}
            result = StepResult.model_validate(data)
            steps[result.kind] = ReplayStep(
                result=result,
                events=[e for e in events if e.data.get("step") == result.kind.value],
                questions=[
                    ReplayQuestion(question=q["question"], options=q.get("options", []))
                    for q in questions
                    if q.get("kind") == result.kind.value
                ],
            )
        provenance = next(
            (
                s.result.data.get("provenance", {}).get("mode")
                for s in steps.values()
                if s.result.data.get("provenance")
            ),
            None,
        )
        race = snapshot.get("race")
        return cls(
            label=label or f"Mission {snapshot.get('id', '?')}",
            recorded_mode=DataMode(provenance) if provenance else DataMode.live,
            race=Race.model_validate(race) if race else None,
            steps=steps,
        )


def _replay_label(trace: ReplayTrace) -> str:
    return f"Replay of {trace.label} (recorded in {trace.recorded_mode.value})"


class ReplayRaceSearch:
    def __init__(self, trace: ReplayTrace):
        self.trace = trace

    async def find_race(self, query: str) -> Race:
        if self.trace.race is None:
            raise ProviderUnavailableError(
                "Replay : aucune fiche course dans la trace."
            )
        return self.trace.race.model_copy(deep=True)


class ReplayTranscriber:
    def __init__(self, trace: ReplayTrace):
        self.trace = trace

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        if not self.trace.transcript:
            raise ProviderUnavailableError(
                "Replay : aucune transcription dans la trace."
            )
        return self.trace.transcript


class ReplayRun:
    live_view_url = None

    def __init__(
        self,
        trace: ReplayTrace,
        kind: StepKind,
        on_event: EventSink,
        ask_user: AskUser,
        delay: float,
    ):
        self.trace = trace
        self.kind = kind
        self.session_id = f"replay-{kind.value}"
        self.received: list[str] = []
        self._on_event = on_event
        self._ask_user = ask_user
        self._delay = delay
        self.browser_observation: dict[str, Any] | None = None
        self._frame: dict[str, Any] | None = None
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._task = asyncio.create_task(self._run())

    async def pause(self) -> None:
        self._resumed.clear()

    async def resume(self) -> None:
        self._resumed.set()

    async def send_message(self, text: str) -> None:
        self.received.append(text)

    async def wait(self) -> StepResult:
        return await self._task

    async def get_screenshot(self) -> bytes | None:
        if self._frame is None:
            return None
        path = self._frame["path"]
        if path.startswith("data:image/png;base64,"):
            return base64.b64decode(path.split(",", 1)[1], validate=True)
        return await asyncio.to_thread((self.trace._base_dir / path).read_bytes)

    def _show_frame(self, frame: dict[str, Any]) -> None:
        self._frame = frame
        self.browser_observation = {key: frame.get(key) for key in ("revision", "url", "title", "at")}
        self._on_event(TraceEvent(
            source=f"agent:{self.kind.value}", type="browser_observation",
            data={"step": self.kind.value, "mode": DataMode.replay.value},
        ))

    async def _run(self) -> StepResult:
        label = _replay_label(self.trace)
        step = self.trace.steps.get(self.kind)
        if step is None:
            result = StepResult(
                kind=self.kind,
                status=StepStatus.failed,
                error="Étape absente de la trace rejouée.",
            )
        else:
            for question in step.questions:
                await self._ask_user(question.question, question.options)
            frames = iter(step.screenshots)
            observation_types = {"browser_observation", "AgentEvent.observation_event"}
            has_observations = any(event.type in observation_types for event in step.events)
            for event in step.events:
                await asyncio.sleep(self._delay)
                await self._resumed.wait()
                if (not has_observations or event.type in observation_types) and (frame := next(frames, None)) is not None:
                    self._show_frame(frame)
                self._on_event(
                    event.model_copy(
                        update={"data": {**event.data, "mode": DataMode.replay.value}}
                    )
                )
            for frame in frames:
                await asyncio.sleep(self._delay)
                await self._resumed.wait()
                self._show_frame(frame)
            result = step.result.model_copy(deep=True)
            result.data = {**result.data, "replay_of": result.h_session_id}
            result.h_session_id = self.session_id
            result.live_view_url = None
        result.data["provenance"] = provenance_data(
            DataMode.replay, ProvenanceKind.replay, label
        )
        return result


class ReplayBrowserAgents:
    def __init__(self, trace: ReplayTrace, delay: float = 0.0):
        self.trace = trace
        self.delay = delay
        self.runs: list[ReplayRun] = []

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
        **kwargs: Any,
    ) -> ReplayRun:
        run = ReplayRun(self.trace, kind, on_event, ask_user, self.delay)
        self.runs.append(run)
        return run
