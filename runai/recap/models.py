"""Weekend recap model: one source for HTML, PDF and .ics."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from runai.models import StepKind, StepStatus, StopPoint

TimelineTag = Literal["course", "a_payer", "info", "conseil"]


def http_url_or_none(value: str | None) -> str | None:
    """Reject URL schemes other than http(s) in recap links (e.g. `javascript:`)."""
    if value is not None and not value.lower().startswith(("http://", "https://")):
        raise ValueError(f"URL http(s) attendue : {value[:40]!r}")
    return value


class TimelineItem(BaseModel):
    """Weekend event. `start` must carry the destination's local timezone."""

    start: datetime
    end: datetime | None = None
    title: str
    detail: str | None = None
    location: str | None = None
    tag: TimelineTag = "info"
    time_known: bool = Field(True, description="False: only the date is known (all-day event in the .ics)")
    in_calendar: bool = True
    alarm_minutes: int | None = Field(None, description="Reminder N minutes before (VALARM)")
    calendar_id: str | None = None


class KeyFact(BaseModel):
    label: str
    value: str
    detail: str | None = None
    source: int | None = Field(None, description="Index (1-based) in Recap.sources")


class RecapSource(BaseModel):
    label: str
    url: str | None = None
    found_by: str = "Linkup"
    used_for: str = ""

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        return http_url_or_none(v)


class FieldRow(BaseModel):
    label: str
    value: str


class RecapMission(BaseModel):
    """An H agent mission (registration, accommodation, transport) as shown in the recap."""

    kind: StepKind
    title: str
    status: StepStatus
    stop_point: StopPoint | None = None
    summary: str | None = None
    fields: list[FieldRow] = Field(default_factory=list)
    price_eur: float | None = None
    price_label: str | None = None
    finalize_url: str | None = None
    live_view_url: str | None = None
    h_session_id: str | None = None
    human_action: str
    capture_data_uri: str | None = Field(None, description="PNG capture as a data: URI (last view before stopping)")
    error: str | None = None

    @field_validator("finalize_url", "live_view_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        return http_url_or_none(v)

    @property
    def is_ready(self) -> bool:
        return self.status in (StepStatus.stopped_before_commitment, StepStatus.completed)


class Recap(BaseModel):
    id: str
    calendar_id: str | None = None
    calendar_revision: int = Field(default=0, ge=0)
    generated_at: datetime
    race_name: str
    race_city: str
    race_date: date | None = None
    distance_km: float | None = None
    runner_name: str
    runner_email: str | None = None
    runner_fictive: bool = True
    goal: str | None = None
    voice_request: str | None = None
    notice: str | None = Field(None, description="Top banner (e.g. fictional data)")
    key_facts: list[KeyFact] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    missions: list[RecapMission] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list, description="For you to do in addition to payments")
    sources: list[RecapSource] = Field(default_factory=list)
    calendar_timezone: str = "Europe/Paris"

    @computed_field
    @property
    def paid_by_runai_eur(self) -> float:
        """Always 0: RunAI stops before every payment."""
        return 0.0

    @computed_field
    @property
    def total_eur(self) -> float:
        return round(sum(m.price_eur or 0 for m in self.missions), 2)

    @property
    def ready_count(self) -> int:
        return sum(m.is_ready for m in self.missions)

    @property
    def payments_to_do(self) -> int:
        return sum(m.price_eur is not None for m in self.missions)
