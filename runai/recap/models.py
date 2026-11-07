"""Modèle du récap de week-end : une seule source pour le HTML, le PDF et le .ics."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from runai.models import StepKind, StepStatus, StopPoint

TimelineTag = Literal["course", "a_payer", "info", "conseil"]


class TimelineItem(BaseModel):
    """Étape du week-end. `start` doit porter un fuseau (heure locale du lieu)."""

    start: datetime
    end: datetime | None = None
    title: str
    detail: str | None = None
    location: str | None = None
    tag: TimelineTag = "info"
    time_known: bool = Field(True, description="False : seule la date est connue (événement « journée » dans le .ics)")
    in_calendar: bool = True
    alarm_minutes: int | None = Field(None, description="Rappel N minutes avant (VALARM)")


class KeyFact(BaseModel):
    label: str
    value: str
    detail: str | None = None
    source: int | None = Field(None, description="Numéro (1-based) dans Recap.sources")


class RecapSource(BaseModel):
    label: str
    url: str | None = None
    found_by: str = "Linkup"
    used_for: str = ""


class FieldRow(BaseModel):
    label: str
    value: str


class RecapMission(BaseModel):
    """Une mission d'agent H (inscription, hébergement, transport) telle qu'elle apparaît dans le récap."""

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
    capture_data_uri: str | None = Field(None, description="Capture PNG en data: URI (dernière vue avant l'arrêt)")
    error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status in (StepStatus.stopped_before_commitment, StepStatus.completed)


class Recap(BaseModel):
    id: str
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
    notice: str | None = Field(None, description="Bandeau en tête (ex. « données fictives »)")
    key_facts: list[KeyFact] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    missions: list[RecapMission] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list, description="À faire par l'humain en plus des paiements")
    sources: list[RecapSource] = Field(default_factory=list)
    calendar_timezone: str = "Europe/Paris"

    @computed_field
    @property
    def paid_by_runai_eur(self) -> float:
        """Toujours 0 : RunAI s'arrête avant chaque paiement."""
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
