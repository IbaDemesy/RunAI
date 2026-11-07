from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunnerProfile(BaseModel):
    """Profil fictif par défaut : aucune donnée réelle ne part dans un navigateur cloud."""

    first_name: str = "Camille"
    last_name: str = "Test"
    email: str = "camille.test@example.com"
    birth_date: date = date(1992, 5, 14)
    gender: str = "F"
    nationality: str = "FR"
    city: str = "Paris"
    club: str | None = None


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


class StopPoint(str, Enum):
    consent = "consent"
    health_declaration = "health_declaration"
    account_creation = "account_creation"
    submission = "submission"
    payment = "payment"


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
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
    h_session_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TraceEvent(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    source: str
    type: str
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
