from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, PrivateAttr

from runai.models import Race, Source


class IssueLevel(str, Enum):
    error = "error"
    warning = "warning"


class Issue(BaseModel):
    field: str
    level: IssueLevel
    message: str


class BibPickup(BaseModel):
    location: str | None = None
    address: str | None = None
    days: list[date] = Field(default_factory=list)
    hours: str | None = None
    geocode_query: str | None = None

    def describe(self) -> str | None:
        parts = [
            self.location,
            self.address,
            ", ".join(day.isoformat() for day in self.days) or None,
            self.hours,
        ]
        text = " ; ".join(part for part in parts if part)
        return text or None


class RaceSheet(BaseModel):
    """Sourced race details: unfound fields stay empty and are listed in `missing_fields`."""

    query: str
    name: str | None = None
    city: str | None = None
    country: str | None = None
    country_code: str | None = None
    race_date: date | None = None
    start_time: str | None = None
    distance_km: float | None = None
    official_url: HttpUrl | None = None
    registration_url: HttpUrl | None = None
    registration_verified: bool = False
    start_location: str | None = None
    start_address: str | None = None
    start_geocode_query: str | None = None
    bib_pickup: BibPickup = Field(default_factory=BibPickup)
    sources: list[Source] = Field(default_factory=list)
    field_sources: dict[str, HttpUrl] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    _notes: list[Issue] = PrivateAttr(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        return not any(issue.level is IssueLevel.error for issue in self.issues)

    def to_race(self) -> Race:
        return Race(
            name=self.name or self.query,
            city=self.city or "",
            country=self.country_code or self.country or "",
            race_date=self.race_date,
            start_time=self.start_time,
            distance_km=self.distance_km,
            registration_url=self.registration_url,
            bib_pickup=self.bib_pickup.describe(),
            start_location=self.start_address or self.start_location,
            sources=self.sources,
        )


class GeoPoint(BaseModel):
    lat: float
    lon: float
    label: str
    query: str
    provider: str


class RaceLocations(BaseModel):
    start: GeoPoint | None = None
    bib_pickup: GeoPoint | None = None
