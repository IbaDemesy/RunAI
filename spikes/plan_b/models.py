"""Sortie Pydantic du plan B « course complète »."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RegStatus(str, Enum):
    open = "open"
    sold_out = "sold_out"
    closed = "closed"
    not_yet_open = "not_yet_open"
    waitlist = "waitlist"
    past = "past"
    unknown = "unknown"


class SourcedStatus(BaseModel):
    status: RegStatus
    evidence: str = ""
    source_url: str | None = None
    checked_by: Literal["linkup_search", "linkup_fetch", "h_agent", "manual"]


class TargetRace(BaseModel):
    query: str
    name: str | None = None
    date: dt.date | None = None
    distance_km: float | None = None
    city: str | None = None
    country: str | None = None
    official_url: str | None = None
    registration_url: str | None = None
    status: SourcedStatus
    status_details: list[SourcedStatus] = Field(default_factory=list)


class OfficialOption(BaseModel):
    kind: Literal["waitlist", "resale", "transfer"]
    available: bool | None
    url: str | None = None
    how: str = ""
    source_url: str | None = None


class TravelEstimate(BaseModel):
    mode: Literal["train", "flight", "local"]
    minutes: int
    via: str | None = None
    estimated: bool = True


class Alternative(BaseModel):
    name: str
    city: str
    country: str | None = None
    date: dt.date
    days_from_target: int
    distance_km: float | None = None
    registration_url: str | None = None
    platform: str | None = None
    price_eur: float | None = None
    status: SourcedStatus
    status_details: list[SourcedStatus] = Field(default_factory=list)
    travel: TravelEstimate
    verified_open: bool


class Rejected(BaseModel):
    name: str
    city: str | None = None
    date: str | None = None
    reason: str


class Metrics(BaseModel):
    total_s: float
    stages_s: dict[str, float]
    linkup_calls: dict[str, int]
    linkup_cost_usd_computed: float
    linkup_balance_delta_usd: float | None = None


class PlanB(BaseModel):
    target: TargetRace
    unavailable: bool
    official_options: list[OfficialOption]
    alternatives: list[Alternative]
    window: tuple[dt.date, dt.date] | None = None
    rejected: list[Rejected] = Field(default_factory=list)
    metrics: Metrics
