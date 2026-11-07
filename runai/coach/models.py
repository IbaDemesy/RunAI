"""Modèles du coach : profil sportif, niveau estimé, préférences et courses recommandées.

`CoachProfile` décrit la forme du coureur (réponses vocales). Il ne contient aucune donnée
d'identité : celle-ci reste dans `runai.models.RunnerProfile` (profil fictif des agents H).
"""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    computed_field,
)

from runai.models import Race, Source

DISTANCES_KM: dict[str, float] = {
    "5k": 5.0,
    "10k": 10.0,
    "semi": 21.0975,
    "marathon": 42.195,
}
DISTANCE_LABELS = {"5k": "5 km", "10k": "10 km", "semi": "semi-marathon", "marathon": "marathon"}
LEVEL_LABELS = {"debutant": "débutant", "intermediaire": "intermédiaire", "confirme": "confirmé", "expert": "expert"}


class Goal(str, Enum):
    premier_10k = "premier_10k"
    chrono = "chrono"
    trail = "trail"
    voyage = "voyage"
    finir = "finir"


class Level(str, Enum):
    debutant = "debutant"
    intermediaire = "intermediaire"
    confirme = "confirme"
    expert = "expert"


class RecentRace(BaseModel):
    distance_km: float = Field(gt=0.5, le=200)
    time_s: int = Field(gt=60)
    months_ago: float = Field(default=0, ge=0)


class RecentRun(BaseModel):
    distance_km: float = Field(gt=0, le=200)
    duration_min: float | None = Field(default=None, gt=0)
    d_plus_m: int | None = Field(default=None, ge=0)


class CoachProfile(BaseModel):
    """Réponses vocales transcrites. Un champ non dit reste à `None`, jamais inventé."""

    sessions_per_week: float | None = Field(default=None, ge=0, le=14)
    weekly_km: float | None = Field(default=None, ge=0, le=300)
    longest_recent_run: RecentRun | None = None
    recent_race: RecentRace | None = None
    cooper_m: int | None = Field(default=None, ge=800, le=5000)
    running_since_months: int | None = Field(default=None, ge=0)
    age: int | None = Field(default=None, ge=8, le=100)
    goals: list[Goal] = Field(default_factory=list)

    @computed_field
    @property
    def missing_fields(self) -> list[str]:
        wanted = ("sessions_per_week", "longest_recent_run", "recent_race", "age")
        return [name for name in wanted if getattr(self, name) is None]


EstimateSource = Literal["chrono", "test_cooper", "sortie", "declaratif"]
Confidence = Literal["haute", "moyenne", "basse"]
Verdict = Literal["recommande", "possible", "deconseille", "bloque"]


def format_hms(seconds: float) -> str:
    total = round(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}'{s:02d}" if h else f"{m}'{s:02d}"


class TimeRange(BaseModel):
    distance: str
    distance_km: float
    low_s: int
    high_s: int

    @computed_field
    @property
    def label(self) -> str:
        return f"{format_hms(self.low_s)} - {format_hms(self.high_s)}"

    @computed_field
    @property
    def pace_label(self) -> str:
        return f"{format_hms(self.low_s / self.distance_km)} - {format_hms(self.high_s / self.distance_km)} /km"


class LevelEstimate(BaseModel):
    level: Level
    source: EstimateSource
    confidence: Confidence
    vdot_low: float
    vdot_high: float
    predictions: dict[str, TimeRange]
    notes: list[str] = Field(default_factory=list)


class DistanceAdvice(BaseModel):
    distance: str
    verdict: Verdict
    weeks_needed_low: int
    weeks_needed_high: int
    reason: str


class Assessment(BaseModel):
    profile: CoachProfile
    estimate: LevelEstimate
    weeks_available: int | None
    advice: list[DistanceAdvice]

    @computed_field
    @property
    def recommended(self) -> list[str]:
        return [a.distance for a in self.advice if a.verdict == "recommande"]

    @computed_field
    @property
    def possible(self) -> list[str]:
        return [a.distance for a in self.advice if a.verdict == "possible"]

    @computed_field
    @property
    def not_advised(self) -> list[str]:
        return [a.distance for a in self.advice if a.verdict in ("deconseille", "bloque")]

    def advice_for(self, distance: str) -> DistanceAdvice:
        return next(a for a in self.advice if a.distance == distance)

    def summary(self) -> str:
        """Une phrase lisible à voix haute."""
        e = self.estimate
        parts = [f"Niveau {LEVEL_LABELS[e.level.value]} (confiance {e.confidence})."]
        for name in ("10k", "semi", "marathon"):
            parts.append(f"{DISTANCE_LABELS[name].capitalize()} : {e.predictions[name].label}.")
        if self.recommended:
            parts.append("Recommandé : " + ", ".join(DISTANCE_LABELS[d] for d in self.recommended) + ".")
        if self.not_advised:
            parts.append("Déconseillé : " + ", ".join(DISTANCE_LABELS[d] for d in self.not_advised) + ".")
        return " ".join(parts)


# --- Recherche et recommandation de courses ------------------------------------------------


class RegistrationStatus(str, Enum):
    """Statut lu sur la page d'inscription. `a_verifier` : page illisible ou ambiguë, à confier à H."""

    ouvert = "ouvert"
    a_verifier = "a_verifier"
    complet = "complet"
    liste_attente = "liste_attente"
    pas_encore_ouvert = "pas_encore_ouvert"
    ferme = "ferme"


StatusSource = Literal["page", "agregateur", "non_lu"]
Terrain = Literal["plat", "vallonne", "indifferent"]
RaceSize = Literal["petite", "grande", "indifferent"]
TravelMode = Literal["ground", "flight"]


class RacePreferences(BaseModel):
    """Contraintes du coureur pour chercher une course (dites à la voix ou saisies)."""

    origin_city: str = "Paris"
    date_from: date | None = Field(default=None, description="Défaut : aujourd'hui + 8 semaines")
    date_to: date | None = Field(default=None, description="Défaut : aujourd'hui + 26 semaines")
    distance_km: float | None = Field(default=None, gt=0, description="Défaut : choisie selon le niveau")
    distance_tolerance_km: float | None = Field(default=None, ge=0)
    trail: bool = False
    terrain: Terrain = "indifferent"
    race_size: RaceSize = "indifferent"
    max_travel_h: float = Field(default=3.0, gt=0)
    travel_mode: TravelMode = "ground"
    foreign: bool = False
    zone_hint: str = Field(default="", description="Zone en clair pour la recherche, ex. 'en Italie'")
    seed_races: list[str] = Field(default_factory=list, description="Courses citées par le coureur, cherchées en plus")


class SearchQuery(BaseModel):
    """Requête figée envoyée au finder ; sa clé identifie un résultat en cache."""

    distance_km: float
    distance_label: str
    tolerance_km: float
    date_from: date
    date_to: date
    origin_city: str
    max_travel_h: float
    travel_mode: TravelMode = "ground"
    terrain: Terrain = "indifferent"
    race_size: RaceSize = "indifferent"
    zone_hint: str = ""
    foreign: bool = False
    seed_races: list[str] = Field(default_factory=list)

    def cache_key(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()[:10]
        slug = re.sub(r"[^a-z0-9]+", "-", f"{self.distance_label} {self.origin_city}".lower()).strip("-")
        return f"{slug}-{digest}"


class CandidateRace(BaseModel):
    """Course trouvée par Linkup, filtrée (date, distance, trajet) puis vérifiée sur sa page."""

    name: str
    race_date: date | None = None
    city: str | None = None
    country: str | None = None
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    platform: str | None = None
    registration_url: str | None = None
    official_url: str | None = None
    participants: int | None = None
    status: RegistrationStatus = RegistrationStatus.a_verifier
    status_source: StatusSource = "non_lu"
    status_evidence: str | None = None
    status_from_search: str | None = None
    price_eur: float | None = None
    price_tier: str | None = None
    check_error: str | None = None
    km_from_origin: float | None = None
    travel_h_est: float | None = None
    sources: list[str] = Field(default_factory=list)
    seed: bool = Field(default=False, description="Course citée par le coureur (`seed_races`)")


class RejectedRace(BaseModel):
    name: str
    race_date: date | None = None
    city: str | None = None
    why: str


class FinderMetrics(BaseModel):
    search_calls: int = 0
    fetch_calls: int = 0
    fetch_errors: int = 0
    skipped_fetches: int = 0
    total_s: float = 0
    phases_s: dict[str, float] = Field(default_factory=dict)
    cost_usd_estimated: float = 0
    second_round: bool = False


def utcnow() -> datetime:
    return datetime.now(UTC)


class DiscoveryResult(BaseModel):
    """Sortie brute du finder, indépendante du niveau : c'est elle qui est mise en cache."""

    query: SearchQuery
    candidates: list[CandidateRace] = Field(default_factory=list)
    rejected: list[RejectedRace] = Field(default_factory=list)
    metrics: FinderMetrics = Field(default_factory=FinderMetrics)
    created_at: datetime = Field(default_factory=utcnow)
    origin: str = "linkup"
    notes: list[str] = Field(default_factory=list)


_URL = TypeAdapter(HttpUrl)


def _url(value: str | None) -> HttpUrl | None:
    if not value:
        return None
    try:
        return _URL.validate_python(value)
    except ValidationError:
        return None


class RaceRecommendation(BaseModel):
    name: str
    race_date: date | None = None
    city: str | None = None
    country: str | None = None
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    platform: str | None = None
    registration_url: str | None = None
    status: RegistrationStatus
    status_evidence: str | None = None
    needs_h_check: bool = Field(description="Statut, prix ou options à confirmer par un agent H (lecture seule)")
    price_eur: float | None = None
    travel_h_est: float | None = None
    prep_weeks: int | None = None
    prep_verdict: Verdict | None = None
    target_time: TimeRange | None = None
    score: float
    reason: str
    sources: list[str] = Field(default_factory=list)

    def to_race(self) -> Race:
        """Fiche `runai.models.Race` pour lancer une mission sur cette course."""
        sources = [Source(url=u) for u in (_url(s) for s in self.sources) if u is not None]
        return Race(
            name=self.name,
            city=self.city or "",
            country=self.country or "",
            race_date=self.race_date,
            distance_km=self.distance_km,
            registration_url=_url(self.registration_url),
            sources=sources,
        )


class Recommendations(BaseModel):
    query: SearchQuery
    races: list[RaceRecommendation] = Field(default_factory=list)
    excluded: list[RejectedRace] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    from_cache: bool = False
    discovered_at: datetime | None = None
    metrics: FinderMetrics = Field(default_factory=FinderMetrics)
