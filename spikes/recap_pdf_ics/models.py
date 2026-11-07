"""Modele Pydantic du recap de week-end RunAI (une source unique pour le PDF, le .ics et le mail)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

MissionStatus = Literal["pret_a_payer", "en_cours", "bloque", "non_lance"]
TimelineTag = Literal["a_payer", "info", "conseil", "inscription_prete"]


class Runner(BaseModel):
    full_name: str
    email: str
    birth_date: date
    goal: str | None = None
    fictive: bool = True


class KeyFact(BaseModel):
    label: str
    value: str
    detail: str | None = None
    source: int | None = Field(None, description="numero de la source dans Recap.sources")


class TimelineItem(BaseModel):
    start: datetime
    end: datetime | None = None
    title: str
    detail: str | None = None
    tag: TimelineTag = "info"
    location: str | None = None
    in_calendar: bool = True


class HumanValidation(BaseModel):
    at: datetime
    channel: Literal["voix", "clic"]
    what: str


class FieldRow(BaseModel):
    label: str
    value: str


class HRun(BaseModel):
    session_id: str | None = None
    duration_s: int | None = None
    steps: int | None = None
    agent_view_url: str | None = None
    measured: bool = False


class Capture(BaseModel):
    image_path: str | None = Field(None, description="PNG de la derniere observation H, relatif au dossier du spike")
    page_url: str | None = None
    taken_at: datetime | None = None
    caption: str = "Capture H prise juste avant le paiement"
    stop_button_label: str | None = None
    real: bool = False


class Mission(BaseModel):
    key: Literal["inscription", "hotel", "transport"]
    title: str
    status: MissionStatus = "pret_a_payer"
    fields: list[FieldRow]
    price_eur: float | None = None
    price_label: str | None = None
    finalize_url: str | None = None
    finalize_label: str = "Finaliser et payer"
    run: HRun = HRun()
    capture: Capture = Capture()
    validations: list[HumanValidation] = []
    note: str | None = None


class ElevationPoint(BaseModel):
    km: float
    alt_m: float


class CourseProfile(BaseModel):
    points: list[ElevationPoint]
    aid_stations_km: list[float] = []
    climbs: list[tuple[float, float, str]] = Field(default_factory=list, description="(km debut, km fin, libelle)")
    annotations: list[tuple[float, str]] = []
    note: str | None = None


class PaceRow(BaseModel):
    km: str
    profile: str
    pace: str
    advice: str


class Source(BaseModel):
    label: str
    found_by: str
    used_for: str
    url: str | None = None


class ChecklistItem(BaseModel):
    text: str
    done: bool = False


class Recap(BaseModel):
    id: str
    is_mockup: bool = True
    mockup_notice: str | None = None
    generated_at: datetime
    race_name: str
    race_city: str
    race_date: date
    voice_request: str
    runner: Runner
    key_facts: list[KeyFact]
    timeline: list[TimelineItem]
    missions: list[Mission]
    profile: CourseProfile | None = None
    pace_plan: list[PaceRow] = []
    pace_note: str | None = None
    morning: list[FieldRow] = []
    flyover_url: str | None = None
    checklist: list[ChecklistItem] = []
    sources: list[Source] = []
    timezone: str = "Europe/Paris"

    @property
    def total_eur(self) -> float:
        return round(sum(m.price_eur or 0 for m in self.missions), 2)

    @property
    def ready_count(self) -> int:
        return sum(m.status == "pret_a_payer" for m in self.missions)

    @property
    def payments_to_do(self) -> int:
        return sum(m.status == "pret_a_payer" and m.price_eur is not None for m in self.missions)
