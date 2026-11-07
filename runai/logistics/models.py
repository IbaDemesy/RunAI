"""Modèles du règlement d'une course, du feu vert et de la timeline du week-end."""

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, HttpUrl, field_validator


class FieldSource(BaseModel):
    """D'où vient une valeur : URL lue, page du document et extrait (langue d'origine)."""

    url: HttpUrl
    page: int | None = None
    excerpt: str | None = None


class PickupWindow(BaseModel):
    """Créneau de retrait des dossards, heure locale de la course."""

    day: date
    opens: time
    closes: time


class TimeGate(BaseModel):
    """Barrière horaire intermédiaire : temps de course maximal au km `km`."""

    km: float
    max_elapsed: timedelta
    clock_time: time | None = Field(None, description="Heure locale publiée par l'organisateur, si elle l'est")


class RequirementKind(str, Enum):
    license = "license"
    runcard = "runcard"
    medical_certificate = "medical_certificate"
    waiver = "waiver"
    insurance_fee = "insurance_fee"
    identity_document = "identity_document"
    other = "other"


class Requirement(BaseModel):
    """Pièce ou démarche exigée par le règlement. C'est toujours l'humain qui la fournit."""

    kind: RequirementKind
    label: str
    detail: str | None = None
    cost_eur: float | None = None
    deadline: str | None = None
    source: FieldSource | None = None


class LicenseKind(str, Enum):
    none = "none"
    host_federation = "host_federation"
    foreign_federation = "foreign_federation"


class EntryPath(BaseModel):
    """Une voie d'inscription du règlement (ex. Runcard + certificat pour un étranger résidant à l'étranger).

    `None` sur un critère = indifférent ; `licenses` = types de licence acceptés sur cette voie ;
    `to_confirm` = voie déduite mais non confirmée par le règlement (jamais verte).
    """

    id: str
    label: str
    competitive: bool = True
    host_citizen: bool | None = None
    resident_in_host_country: bool | None = None
    licenses: list[LicenseKind] | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    to_confirm: str | None = None
    source: FieldSource | None = None


class RaceRules(BaseModel):
    """Règlement utile d'une course. Chaque champ renseigné a sa source dans `field_sources` (même nom de clé).

    Les champs introuvables restent vides et sont listés dans `missing_fields` : jamais de valeur devinée.
    Les heures sont locales (`timezone`).
    """

    race_name: str
    race_date: date | None = None
    distance_km: float | None = None
    country_code: str | None = None
    timezone: str = "Europe/Paris"
    official_url: HttpUrl | None = None
    regulation_url: HttpUrl | None = None
    start_time: time | None = None
    start_location: str | None = None
    start_waves: str | None = None
    corrals_open: time | None = None
    corrals_close_before_wave: timedelta | None = None
    bag_drop: str | None = None
    bib_pickup_location: str | None = None
    bib_pickup_windows: list[PickupWindow] = Field(default_factory=list)
    bib_pickup_race_day: bool | None = None
    bib_pickup_proxy_allowed: bool | None = None
    time_limit: timedelta | None = None
    time_gates: list[TimeGate] = Field(default_factory=list)
    aid_stations: str | None = None
    min_age: int | None = None
    registration_deadline: datetime | None = None
    entry_paths: list[EntryPath] = Field(default_factory=list)
    field_sources: dict[str, FieldSource] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    origin: Literal["fixture", "cache", "linkup"] = "linkup"
    verified_on: date | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def source_url(self, field: str) -> str | None:
        source = self.field_sources.get(field)
        return str(source.url) if source else None


class Light(str, Enum):
    green = "vert"
    orange = "orange"
    red = "rouge"


class Reason(BaseModel):
    level: Light
    code: str
    message: str
    source_url: str | None = None


class HumanTodo(BaseModel):
    """À faire par l'humain lui-même (document, certificat, signature). L'agent ne le coche jamais :
    il n'y a volontairement pas de champ « fait »."""

    kind: RequirementKind
    label: str
    detail: str | None = None
    cost_eur: float | None = None
    deadline: str | None = None
    source_url: str | None = None


class RunnerSituation(BaseModel):
    """Ce que RunAI sait du coureur en plus de `RunnerProfile` (données fictives en démo)."""

    residence_country: str = "FR"
    license: LicenseKind = LicenseKind.none
    license_federation: str | None = None
    wants_competitive: bool = True
    has_runcard: bool = False
    has_valid_medical_certificate: bool = False


class RecentResult(BaseModel):
    distance_km: float
    time: timedelta


class RunnerGoal(BaseModel):
    """Objectif du coureur, ex. `RunnerGoal.parse("2h10-2h15", 21.0975)`."""

    distance_km: float
    target_low: timedelta | None = None
    target_high: timedelta | None = None
    recent_result: RecentResult | None = None

    @classmethod
    def parse(cls, text: str, distance_km: float, **kwargs) -> "RunnerGoal":
        from runai.logistics.durations import parse_duration_range

        low, high = parse_duration_range(text)
        return cls(distance_km=distance_km, target_low=low, target_high=high, **kwargs)


class Eligibility(BaseModel):
    light: Light
    reasons: list[Reason] = Field(default_factory=list)
    human_todo: list[HumanTodo] = Field(default_factory=list)
    entry_path_id: str | None = None
    alternative_path_id: str | None = None


class TransportLeg(BaseModel):
    """Trajet proposé par l'agent transport. Datetimes naïves = heure locale de la course."""

    mode: Literal["train", "flight", "bus", "car", "other"] = "train"
    origin: str
    destination: str
    depart: datetime
    arrive: datetime
    reference: str | None = None


class HotelStay(BaseModel):
    """Hôtel proposé par l'agent hébergement (heures locales de la course)."""

    name: str
    check_in: date
    check_out: date
    check_in_from: time = time(15, 0)
    check_out_until: time = time(11, 0)
    minutes_to_start: int = 30
    minutes_to_bib_pickup: int = 30


class AlertLevel(str, Enum):
    blocking = "bloquant"
    warning = "attention"
    info = "info"


class Alert(BaseModel):
    level: AlertLevel
    code: str
    message: str
    source_url: str | None = None


class TimelineEvent(BaseModel):
    """Événement daté (datetimes avec fuseau). `assumption` = déduit d'une hypothèse, pas lu dans le règlement."""

    start: datetime
    end: datetime
    title: str
    kind: Literal["transport", "bib_pickup", "hotel", "race", "prep", "info"]
    location: str | None = None
    detail: str | None = None
    assumption: bool = False
    source_url: str | None = None

    def in_timezone(self, tz: str = "Europe/Paris") -> "TimelineEvent":
        zone = ZoneInfo(tz)
        return self.model_copy(update={"start": self.start.astimezone(zone), "end": self.end.astimezone(zone)})


class Timeline(BaseModel):
    race_name: str
    timezone: str
    events: list[TimelineEvent] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(alert.level is AlertLevel.blocking for alert in self.alerts)
