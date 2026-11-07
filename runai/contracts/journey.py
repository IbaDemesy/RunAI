"""JourneyPlan v1 : source unique de la carte, de la timeline et des exports.

L'adresse exacte du domicile n'apparaît jamais : `origin_public` est une ville ou un quartier.
Coordonnée inconnue = None ; liaison sans géométrie sourcée = `illustrative` ou `unavailable`.
"""

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from runai.contracts.common import (
    Automation,
    Confidence,
    DataMode,
    Limitation,
    Provenance,
)

SCHEMA_VERSION = "journey.v1"


class StopKind(str, Enum):
    home = "home"
    station = "station"
    airport = "airport"
    hotel = "hotel"
    bib_pickup = "bib_pickup"
    race_start = "race_start"
    race_finish = "race_finish"


class SegmentMode(str, Enum):
    walk = "walk"
    local = "local"
    train = "train"
    flight = "flight"
    race = "race"


class GeometryStatus(str, Enum):
    verified = "verified"
    approximate = "approximate"
    illustrative = "illustrative"
    unavailable = "unavailable"


class ChapterId(str, Enum):
    home = "home"
    departure_hub = "departure_hub"
    main_transport = "main_transport"
    arrival_hotel = "arrival_hotel"
    bib_pickup = "bib_pickup"
    race = "race"
    return_trip = "return_trip"


class CostCategory(str, Enum):
    registration = "registration"
    accommodation = "accommodation"
    transport = "transport"
    local = "local"
    other = "other"


class Coords(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Money(BaseModel):
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    collected_at: datetime
    confidence: Confidence = Confidence.estimated
    provenance: Provenance


class JourneyStop(BaseModel):
    id: str
    kind: StopKind
    label: str
    coords: Coords | None = None
    local_time: datetime | None = None
    timezone: str | None = None
    provenance: Provenance | None = None
    confidence: Confidence = Confidence.unknown


class JourneySegment(BaseModel):
    id: str
    from_stop_id: str
    to_stop_id: str
    mode: SegmentMode
    departure: datetime | None = None
    arrival: datetime | None = None
    timezone: str | None = None
    geometry: list[tuple[float, float]] | None = None
    geometry_status: GeometryStatus = GeometryStatus.unavailable
    duration_min: int | None = None
    cost: Money | None = None
    automation: Automation = Automation.not_covered
    manual_url: str | None = None
    provenance: Provenance | None = None
    limitation: Limitation | None = None

    @model_validator(mode="after")
    def _geometry_matches_status(self) -> "JourneySegment":
        if self.geometry_status is GeometryStatus.unavailable and self.geometry:
            raise ValueError(f"{self.id}: géométrie présente mais statut unavailable")
        if self.geometry_status is not GeometryStatus.unavailable and not self.geometry:
            raise ValueError(f"{self.id}: statut {self.geometry_status.value} sans géométrie")
        return self


class CostLine(BaseModel):
    id: str
    category: CostCategory
    label: str
    money: Money | None = None
    note: str | None = None


class Budget(BaseModel):
    """Poste sans `money` = total partiel ; jamais compté comme zéro."""

    currency: str = "EUR"
    cap: float | None = None
    lines: list[CostLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def _single_currency(self) -> "Budget":
        for line in self.lines:
            if line.money and line.money.currency != self.currency:
                raise ValueError(f"{line.id}: devise {line.money.currency} ≠ {self.currency}")
        return self

    @computed_field
    @property
    def known_total(self) -> float:
        return round(sum(line.money.amount for line in self.lines if line.money), 2)

    @computed_field
    @property
    def missing_line_ids(self) -> list[str]:
        return [line.id for line in self.lines if line.money is None]

    @computed_field
    @property
    def complete(self) -> bool:
        return bool(self.lines) and not self.missing_line_ids

    @computed_field
    @property
    def over_cap(self) -> bool | None:
        if self.cap is None:
            return None
        if self.known_total > self.cap:
            return True
        return False if self.complete else None


class Chapter(BaseModel):
    id: ChapterId
    label: str
    stop_ids: list[str] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    status: Literal["available", "partial", "unavailable"] = "available"


class JourneyPlan(BaseModel):
    schema_version: Literal["journey.v1"] = SCHEMA_VERSION
    mission_id: str
    revision: int = Field(ge=0)
    framing_revision: int | None = None
    mode: DataMode
    origin_public: str
    date_range: tuple[date, date] | None = None
    timezone: str
    currency: str = "EUR"
    stops: list[JourneyStop]
    segments: list[JourneySegment]
    chapters: list[Chapter]
    budget: Budget
    warnings: list[str] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    sources: list[Provenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> "JourneyPlan":
        stop_ids = {stop.id for stop in self.stops}
        segment_ids = {segment.id for segment in self.segments}
        if len(stop_ids) != len(self.stops) or len(segment_ids) != len(self.segments):
            raise ValueError("identifiants d'étape ou de liaison dupliqués")
        for segment in self.segments:
            for ref in (segment.from_stop_id, segment.to_stop_id):
                if ref not in stop_ids:
                    raise ValueError(f"{segment.id}: étape inconnue {ref}")
        for chapter in self.chapters:
            if unknown := (set(chapter.stop_ids) - stop_ids) | (set(chapter.segment_ids) - segment_ids):
                raise ValueError(f"chapitre {chapter.id.value}: références inconnues {sorted(unknown)}")
        if self.budget.currency != self.currency:
            raise ValueError("devise du budget ≠ devise du séjour")
        if self.date_range and self.date_range[0] > self.date_range[1]:
            raise ValueError("date_range inversée")
        return self
