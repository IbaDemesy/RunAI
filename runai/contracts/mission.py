"""Questions humaines corrélées, enveloppe SSE v1 et instantané de mission v2.

Compatibles avec `AgentQuestion`/`StepResult` de la V1 : ce sont des vues additives.
"""

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_serializer,
)

from runai.contracts.common import Automation, DataMode, Limitation
from runai.contracts.journey import Budget
from runai.models import (
    AgentQuestion,
    Race,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
    utcnow,
)
from runai.redaction import redact_secrets
from runai.search.logistics_sweep import LogisticsSweep

EVENTS_SCHEMA_VERSION = "events.v1"
MISSION_SCHEMA_VERSION = "mission.v2"


class QuestionStatus(str, Enum):
    open = "open"
    answered = "answered"
    expired = "expired"
    refused = "refused"
    cancelled = "cancelled"


class HumanQuestion(BaseModel):
    question_id: str
    mission_id: str
    step: StepKind
    session_id: str | None = None
    revision: int
    reason: str | None = None
    text: str
    display_text: str | None = None
    choices: list[str] = Field(default_factory=list)
    status: QuestionStatus = QuestionStatus.open
    answer: str | None = None
    asked_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None

    @classmethod
    def from_agent_question(
        cls,
        question: AgentQuestion,
        mission_id: str,
        revision: int,
        session_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> "HumanQuestion":
        return cls(
            question_id=question.id,
            mission_id=mission_id,
            step=question.kind,
            session_id=session_id,
            revision=revision,
            text=question.question,
            display_text=question.display_text,
            choices=question.options,
            status=QuestionStatus.answered if question.answer is not None else QuestionStatus.open,
            answer=question.answer,
            asked_at=question.asked_at,
            expires_at=expires_at,
        )


class HumanAnswer(BaseModel):
    """Un « oui » n'autorise jamais paiement, compte, santé, consentement ou envoi."""

    answer: str = Field(min_length=1, max_length=500)
    revision: int
    idempotency_key: str = Field(min_length=8, max_length=100)


EventType = Literal[
    "snapshot",
    "mission_status",
    "step",
    "question_opened",
    "question_resolved",
    "journey_revised",
    "budget_updated",
    "trace",
    "error",
]


class EventEnvelope(BaseModel):
    """`event_id` = f"{mission_id}:{sequence}" ; sert de `id:` SSE et de Last-Event-ID."""

    schema_version: Literal["events.v1"] = EVENTS_SCHEMA_VERSION
    event_id: str
    sequence: int = Field(ge=0)
    mission_id: str
    emitted_at: datetime = Field(default_factory=utcnow)
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def redact_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return redact_secrets(value)

    @field_serializer("payload")
    def serialize_payload(self, value: dict[str, Any]) -> dict[str, Any]:
        return redact_secrets(value)

    @classmethod
    def build(cls, mission_id: str, sequence: int, type: EventType, payload: dict[str, Any]) -> "EventEnvelope":
        return cls(event_id=f"{mission_id}:{sequence}", sequence=sequence, mission_id=mission_id, type=type, payload=payload)

    def to_sse(self) -> str:
        return f"id: {self.event_id}\nevent: {self.type}\ndata: {self.model_dump_json()}\n\n"


MissionStatusV2 = Literal[
    "searching", "running", "awaiting_human", "completed", "failed", "cancelled"
]


class MissionSnapshot(BaseModel):
    linkup: LogisticsSweep | None = None
    schema_version: Literal["mission.v2"] = MISSION_SCHEMA_VERSION
    mission_id: str
    framing_id: str
    framing_revision: int
    mode: DataMode
    status: MissionStatusV2
    sequence: int = Field(ge=0)
    race: Race | None = None
    steps: list[StepResult]
    questions: list[HumanQuestion] = Field(default_factory=list)
    journey_revision: int | None = None
    budget: Budget | None = None
    limitations: list[Limitation] = Field(default_factory=list)
    error: str | None = None

    @model_serializer(mode="wrap")
    def serialize_snapshot(self, handler):
        return redact_secrets(handler(self))

    @field_validator("error")
    @classmethod
    def redact_error(cls, value: str | None) -> str | None:
        return redact_secrets(value)

    @field_serializer("error")
    def serialize_error(self, value: str | None) -> str | None:
        return redact_secrets(value)


MISSION_SUMMARY_SCHEMA_VERSION = "mission_summary.v1"


class MissionSummaryRace(BaseModel):
    name: str
    city: str
    country: str
    race_date: date | None = None
    distance_km: float | None = None


class MissionSummaryStep(BaseModel):
    kind: StepKind
    status: StepStatus
    automation: Automation | None = None
    stop_point: StopPoint | None = None
    price_eur: float | None = None
    url: str | None = None


class MissionSummary(BaseModel):
    """Compact, redacted view of a past or running mission for the request history."""

    schema_version: Literal["mission_summary.v1"] = MISSION_SUMMARY_SCHEMA_VERSION
    mission_id: str
    framing_id: str | None = None
    user_id: str | None = None
    mode: DataMode | None = None
    status: MissionStatusV2
    created_at: datetime
    finished_at: datetime | None = None
    race: MissionSummaryRace | None = None
    origin: str | None = None
    date_range: tuple[date, date] | None = None
    budget_eur: float | None = None
    total_price_eur: float | None = None
    steps: list[MissionSummaryStep] = Field(default_factory=list)
    headline: str
    replay_available: bool = False

    @model_serializer(mode="wrap")
    def serialize_summary(self, handler):
        return redact_secrets(handler(self))
