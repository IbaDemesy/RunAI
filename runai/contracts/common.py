"""Provenance and mode shared by framing, missions and journeys."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl

from runai.models import utcnow


class DataMode(str, Enum):
    """`live` = real providers; `demo` = fakes/fixtures; `replay` = recorded trace. Never mixed."""

    live = "live"
    demo = "demo"
    replay = "replay"


class ProvenanceKind(str, Enum):
    human = "human"
    linkup = "linkup"
    h_agent = "h_agent"
    gladia = "gladia"
    official_api = "official_api"
    derived = "derived"
    fixture = "fixture"
    replay = "replay"


class Confidence(str, Enum):
    verified = "verified"
    estimated = "estimated"
    illustrative = "illustrative"
    unknown = "unknown"


class Provenance(BaseModel):
    kind: ProvenanceKind
    url: HttpUrl | None = None
    label: str | None = None
    collected_at: datetime = Field(default_factory=utcnow)


class Automation(str, Enum):
    """What RunAI does for a step: allowed H agent, manual official link, or nothing."""

    automated = "automated"
    manual = "manual"
    not_covered = "not_covered"


class Limitation(BaseModel):
    """Specific limitation and manual alternative instead of a blanket refusal or false promise."""

    code: str
    message: str
    step: str | None = None
    manual_url: HttpUrl | None = None
