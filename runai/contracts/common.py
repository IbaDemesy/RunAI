"""Provenance et mode partagés par le cadrage, la mission et le séjour."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl

from runai.models import utcnow


class DataMode(str, Enum):
    """`live` = vrais fournisseurs ; `demo` = fakes/fixtures ; `replay` = trace rejouée. Jamais mélangés."""

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
    """Ce que RunAI fait sur un poste : agent H autorisé, lien officiel manuel, ou rien."""

    automated = "automated"
    manual = "manual"
    not_covered = "not_covered"


class Limitation(BaseModel):
    """Limite précise et alternative manuelle ; remplace un refus global ou une fausse promesse."""

    code: str
    message: str
    step: str | None = None
    manual_url: HttpUrl | None = None
