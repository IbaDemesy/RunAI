"""Replay : rejoue une trace enregistrée (schéma `replay.v1`), étiquetée `replay`, jamais `live`.

Aucun appel réseau : la recherche, la voix et les agents renvoient ce qui a été enregistré,
avec `StepResult.data["provenance"]["mode"] == "replay"` et sans vue live.
"""

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer

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


class ReplayTrace(BaseModel):
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
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def dump(self, path: Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

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
    return f"Replay of “{trace.label}” (recorded in {trace.recorded_mode.value})"


class ReplayRaceSearch:
    def __init__(self, trace: ReplayTrace):
        self.trace = trace

    async def find_race(self, query: str) -> Race:
        if self.trace.race is None:
            raise ProviderUnavailableError(
                "Replay: no race details in the trace."
            )
        return self.trace.race.model_copy(deep=True)


class ReplayTranscriber:
    def __init__(self, trace: ReplayTrace):
        self.trace = trace

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        if not self.trace.transcript:
            raise ProviderUnavailableError(
                "Replay: no transcript in the trace."
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

    async def _run(self) -> StepResult:
        label = _replay_label(self.trace)
        step = self.trace.steps.get(self.kind)
        if step is None:
            result = StepResult(
                kind=self.kind,
                status=StepStatus.failed,
                error="Step missing from the replayed trace.",
            )
        else:
            for question in step.questions:
                await self._ask_user(question.question, question.options)
            for event in step.events:
                await asyncio.sleep(self._delay)
                await self._resumed.wait()
                self._on_event(
                    event.model_copy(
                        update={"data": {**event.data, "mode": DataMode.replay.value}}
                    )
                )
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
