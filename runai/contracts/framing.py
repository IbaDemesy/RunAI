"""Multi-turn conversational framing required before any mission or H agent.

State machine (`FramingStatus`):

    collecting ⇄ choosing_candidate → ready_to_confirm → confirmed → launched
          ↑______________ correction (revision + 1) ______________|
    any unlaunched state → cancelled

Each reply/correction increments `revision` and invalidates previous summaries.
`assert_launchable` guards launch: no mission without explicit confirmation of the
current revision. Cities are free text; events come from sourced searches (`RaceCandidate`).
"""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, model_serializer

from runai.contracts.common import DataMode, Limitation, Provenance
from runai.models import Race, Source, utcnow
from runai.redaction import redact_secrets

SCHEMA_VERSION = "framing.v1"
USER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
# Client-generated, opaque runner id used to group past requests (no account, no PII).
UserId = Annotated[str, StringConstraints(pattern=USER_ID_PATTERN)]


def format_money(value: float | None) -> str:
    if value is None:
        return "no cap"
    return f"€{value:.0f}" if float(value).is_integer() else f"€{value:.2f}"


def format_distance(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0") + " km"


def format_date(value: date) -> str:
    weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    return f"{weekdays[value.weekday()]} {value.day} {months[value.month - 1]} {value.year}"


class FramingStatus(str, Enum):
    collecting = "collecting"
    choosing_candidate = "choosing_candidate"
    ready_to_confirm = "ready_to_confirm"
    confirmed = "confirmed"
    launched = "launched"
    cancelled = "cancelled"


class SlotName(str, Enum):
    city = "city"
    race = "race"
    edition = "edition"
    race_date = "race_date"
    date_window = "date_window"
    distance_km = "distance_km"
    origin = "origin"
    budget = "budget"
    nights = "nights"
    transport_mode = "transport_mode"
    preferences = "preferences"


class SlotStatus(str, Enum):
    unknown = "unknown"
    asked = "asked"
    answered = "answered"
    sourced = "sourced"
    not_needed = "not_needed"


REQUIRED_SLOTS: tuple[SlotName, ...] = (
    SlotName.race,
    SlotName.race_date,
    SlotName.distance_km,
    SlotName.origin,
    SlotName.budget,
    SlotName.nights,
    SlotName.transport_mode,
)
KNOWN_STATUSES = {SlotStatus.answered, SlotStatus.sourced, SlotStatus.not_needed}


class Slot(BaseModel):
    """`value` stays None until supplied by a human or source; never guessed."""

    name: SlotName
    status: SlotStatus = SlotStatus.unknown
    value: Any = None
    provenance: Provenance | None = None
    revision: int = 0

    @property
    def is_known(self) -> bool:
        return self.status in KNOWN_STATUSES


def matching_distance(distances_km: list[float], km: float) -> float | None:
    """Closest offered distance to `km`, allowing rounding (21.097 ≈ 21.0975)."""
    close = [d for d in distances_km if abs(d - km) <= max(0.5, km * 0.03)]
    return min(close, key=lambda d: abs(d - km)) if close else None


class RaceCandidate(BaseModel):
    """Event found by generic search (B1), offered for human selection."""

    id: str
    name: str
    city: str
    country: str
    race_date: date | None = None
    distances_km: list[float] = Field(default_factory=list)
    official_url: HttpUrl | None = None
    registration_url: HttpUrl | None = None
    sources: list[Source] = Field(default_factory=list)
    provenance: Provenance
    limitations: list[Limitation] = Field(default_factory=list)

    def to_race(self, distance_km: float | None = None) -> Race:
        return Race(
            name=self.name,
            city=self.city,
            country=self.country,
            race_date=self.race_date,
            distance_km=distance_km,
            registration_url=self.registration_url,
            sources=self.sources,
        )


class FramingChoice(BaseModel):
    id: str
    label: str
    value: Any = None
    candidate_id: str | None = None


class FramingQuestion(BaseModel):
    id: str
    slots: list[SlotName]
    text: str
    choices: list[FramingChoice] = Field(default_factory=list)
    allow_free_text: bool = True
    revision: int


class FramingTurn(BaseModel):
    role: Literal["user", "assistant"]
    channel: Literal["text", "voice", "buttons"] = "text"
    text: str
    revision: int
    at: datetime = Field(default_factory=utcnow)


class FramingSummary(BaseModel):
    """Summary shown before confirmation; valid only for `revision`."""

    revision: int
    race: Race
    candidate_id: str | None = None
    origin_public: str
    date_range: tuple[date, date]
    nights: int
    budget_eur: float | None
    transport_mode: str
    lines: list[str]
    limitations: list[Limitation] = Field(default_factory=list)


class FramingSession(BaseModel):
    schema_version: Literal["framing.v1"] = SCHEMA_VERSION
    id: str
    mode: DataMode
    user_id: UserId | None = None
    status: FramingStatus = FramingStatus.collecting
    revision: int = 0
    slots: dict[SlotName, Slot] = Field(
        default_factory=lambda: {name: Slot(name=name) for name in SlotName}
    )
    candidates: list[RaceCandidate] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    open_questions: list[FramingQuestion] = Field(default_factory=list)
    turns: list[FramingTurn] = Field(default_factory=list)
    summary: FramingSummary | None = None
    limitations: list[Limitation] = Field(default_factory=list)
    confirmed_revision: int | None = None
    confirm_key: str | None = None
    mission_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @model_serializer(mode="wrap")
    def serialize_session(self, handler):
        return redact_secrets(handler(self))


class FramingCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    channel: Literal["text", "voice"] = "text"
    user_id: UserId | None = None


class FramingReply(BaseModel):
    """Free-text reply, button choice or slot correction at the UI's `revision`."""

    revision: int
    text: str | None = Field(default=None, max_length=1000)
    channel: Literal["text", "voice", "buttons"] = "text"
    question_id: str | None = None
    choice_id: str | None = None
    corrections: dict[SlotName, Any] = Field(default_factory=dict)


class FramingConfirm(BaseModel):
    revision: int
    idempotency_key: str = Field(min_length=8, max_length=100)


class CandidateSearch(Protocol):
    """Generic sourced search (B1): no city allowlist; [] if nothing is found."""

    async def find_candidates(
        self, slots: dict[SlotName, Slot], request_text: str | None = None
    ) -> list[RaceCandidate]: ...


class FramingError(Exception):
    """Launch or reply refusal; the server translates it to HTTP 409."""


def missing_slots(session: FramingSession) -> list[SlotName]:
    return [name for name in REQUIRED_SLOTS if not session.slots[name].is_known]


def check_reply_revision(session: FramingSession, reply: FramingReply) -> None:
    if session.status in (FramingStatus.cancelled, FramingStatus.launched):
        raise FramingError(f"Framing {session.status.value}: no further replies accepted")
    if reply.revision != session.revision:
        raise FramingError(
            f"Stale revision {reply.revision} (current {session.revision})"
        )


def assert_launchable(session: FramingSession, confirm: FramingConfirm) -> str | None:
    """Return the existing mission ID on replay of the same confirmation, else None.

    Raise FramingError unless confirmation targets the complete current summary.
    """
    if session.mission_id is not None:
        if confirm.idempotency_key == session.confirm_key:
            return session.mission_id
        raise FramingError("Mission already launched for this framing")
    if session.status is not FramingStatus.ready_to_confirm:
        raise FramingError(f"Framing not ready: {session.status.value}")
    if session.summary is None or session.summary.revision != session.revision:
        raise FramingError("Summary missing or stale")
    if confirm.revision != session.revision:
        raise FramingError(
            f"Confirmation for revision {confirm.revision}, current {session.revision}"
        )
    if missing := missing_slots(session):
        raise FramingError("Missing information: " + ", ".join(m.value for m in missing))
    return None
