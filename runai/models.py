from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    computed_field,
    field_serializer,
    field_validator,
    model_serializer,
)

from runai.redaction import redact_secrets


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunnerProfile(BaseModel):
    """Runner data sent to H agents in tasks protected by guard_task.

    Defaults are fictional; saving real data requires explicit user confirmation.
    """

    first_name: str = "Camille"
    last_name: str = "Test"
    email: str = "camille.test@example.com"
    birth_date: date = date(1992, 5, 14)
    gender: str = "F"
    nationality: str = "FR"
    city: str = "Paris"
    club: str | None = None
    phone: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    license_number: str | None = None
    pps_number: str | None = None
    tshirt_size: str | None = None
    estimated_finish_time: str | None = None
    fictional: bool = True


class Source(BaseModel):
    url: HttpUrl
    title: str | None = None


class Race(BaseModel):
    name: str
    city: str
    country: str
    race_date: date | None = None
    start_time: str | None = None
    distance_km: float | None = None
    registration_url: HttpUrl | None = None
    bib_pickup: str | None = None
    start_location: str | None = None
    sources: list[Source] = Field(default_factory=list)


class StepKind(str, Enum):
    search = "search"
    registration = "registration"
    accommodation = "accommodation"
    transport = "transport"


class AgentQuestion(BaseModel):
    id: str
    kind: StepKind
    question: str
    display_text: str | None = None
    options: list[str] = Field(default_factory=list)
    answer: str | None = None
    asked_at: datetime = Field(default_factory=utcnow)
    answered_at: datetime | None = None


class StopPoint(str, Enum):
    consent = "consent"
    health_declaration = "health_declaration"
    account_creation = "account_creation"
    submission = "submission"
    payment = "payment"


HUMAN_ACTIONS: dict[StopPoint, str] = {
    StopPoint.payment: "Check the summary and the price, then pay yourself on the official site.",
    StopPoint.account_creation: "Create your account yourself: the agent never enters a password.",
    StopPoint.health_declaration: "Provide the medical certificate or PPS yourself: no health data goes through the agent.",
    StopPoint.consent: "Read and accept the rules, terms or consent yourself.",
    StopPoint.submission: "Review the pre-filled fields and submit the final form yourself.",
}
NO_STOP_POINT_ACTION = "Nothing was committed: take over from the live view if needed."


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    waiting_for_user = "waiting_for_user"
    stopped_before_commitment = "stopped_before_commitment"
    completed = "completed"
    failed = "failed"


class StepResult(BaseModel):
    kind: StepKind
    status: StepStatus = StepStatus.pending
    summary: str | None = None
    stop_point: StopPoint | None = None
    url: HttpUrl | None = None
    price_eur: float | None = None
    live_view_url: HttpUrl | None = None
    agent_view_url: HttpUrl | None = None
    h_session_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @computed_field  # additive: what the human must do at the halt
    @property
    def human_action(self) -> str | None:
        if self.status is not StepStatus.stopped_before_commitment:
            return None
        if self.stop_point is None:
            return NO_STOP_POINT_ACTION
        return HUMAN_ACTIONS[self.stop_point]

    @model_serializer(mode="wrap")
    def serialize_result(self, handler):
        return redact_secrets(handler(self))

    @field_validator("error")
    @classmethod
    def redact_error(cls, value: str | None) -> str | None:
        return redact_secrets(value)

    @field_serializer("error")
    def serialize_error(self, value: str | None) -> str | None:
        return redact_secrets(value)


class TraceEvent(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    source: str
    type: str
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def serialize_event(self, handler):
        return redact_secrets(handler(self))
