"""Estimation du niveau d'un coureur et objectifs realistes (spike RunAI, axe A).

Tout est deterministe : pas d'appel reseau, pas de LLM. Le LLM (ou le parseur
de secours) produit un RunnerProfile ; ce module en tire niveau, fourchettes de
temps par distance, delai de preparation et garde-fous.

Formules :
- Riegel (1977) : T2 = T1 * (D2 / D1) ** k, k = 1.06 (borne optimiste) a 1.10.
- Daniels & Gilbert (1979), "VDOT" : VO2 de course et fraction de VO2max
  soutenable en fonction de la duree ; implementation libre ci-dessous.
- Cooper (1968) : VO2max = (distance_12min_m - 504.9) / 44.73.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

DISTANCES_KM: dict[str, float] = {
    "5k": 5.0,
    "10k": 10.0,
    "semi": 21.0975,
    "marathon": 42.195,
}


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


class RunnerProfile(BaseModel):
    """Reponses vocales transcrites. Un champ non dit reste a None, jamais invente."""

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


Source = Literal["chrono", "test_cooper", "sortie", "declaratif"]
Confidence = Literal["haute", "moyenne", "basse"]
Verdict = Literal["recommande", "possible", "deconseille", "bloque"]


def format_hms(seconds: float) -> str:
    total = round(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}'{s:02d}" if h else f"{m}'{s:02d}"


class TimeRange(BaseModel):
    distance: str
    low_s: int
    high_s: int

    @computed_field
    @property
    def label(self) -> str:
        return f"{format_hms(self.low_s)} - {format_hms(self.high_s)}"

    @computed_field
    @property
    def pace_label(self) -> str:
        km = DISTANCES_KM.get(self.distance, 1.0)
        return f"{format_hms(self.low_s / km)} - {format_hms(self.high_s / km)} /km"


class LevelEstimate(BaseModel):
    level: Level
    source: Source
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
    profile: RunnerProfile
    estimate: LevelEstimate
    weeks_available: int | None
    advice: list[DistanceAdvice]

    @computed_field
    @property
    def recommended(self) -> list[str]:
        return [a.distance for a in self.advice if a.verdict == "recommande"]


# --- Daniels & Gilbert --------------------------------------------------------


def _vo2_cost(velocity_m_min: float) -> float:
    return -4.60 + 0.182258 * velocity_m_min + 0.000104 * velocity_m_min**2


def _fraction_vo2max(minutes: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * minutes) + 0.2989558 * math.exp(-0.1932605 * minutes)


def vdot_from_performance(distance_km: float, time_s: float) -> float:
    minutes = time_s / 60
    return _vo2_cost(distance_km * 1000 / minutes) / _fraction_vo2max(minutes)


def time_from_vdot(distance_km: float, vdot: float) -> float:
    """Temps (s) predit par Daniels pour un VDOT, par dichotomie."""
    lo, hi = 60.0, 60.0 * 60 * 12
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot_from_performance(distance_km, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def riegel(time_s: float, from_km: float, to_km: float, exponent: float = 1.06) -> float:
    return time_s * (to_km / from_km) ** exponent


def cooper_vo2max(distance_m: float) -> float:
    return (distance_m - 504.9) / 44.73


# --- Estimation ---------------------------------------------------------------


def _weekly_km(p: RunnerProfile) -> float | None:
    if p.weekly_km is not None:
        return p.weekly_km
    if p.sessions_per_week is not None:
        per_session = 6.0
        if p.longest_recent_run is not None:
            per_session = max(3.0, min(p.longest_recent_run.distance_km * 0.7, 15.0))
        return p.sessions_per_week * per_session
    return None


def _declarative_vdot(p: RunnerProfile) -> tuple[float, float]:
    km = _weekly_km(p) or 0.0
    table = ((10, 25, 33), (20, 28, 38), (35, 32, 43), (50, 36, 48), (80, 40, 54))
    low, high = 42.0, 58.0
    for limit, lo, hi in table:
        if km < limit:
            low, high = lo, hi
            break
    if p.running_since_months is not None and p.running_since_months < 6:
        high -= 4
    if p.age is not None and p.age >= 60:
        low, high = low - 3, high - 4
    return low, high


def _upper_exponent(p: RunnerProfile, from_km: float, to_km: float) -> float:
    km = _weekly_km(p)
    if to_km / from_km <= 1.5:
        return 1.07
    if to_km >= 30 and (km is None or km < 40):
        return 1.12
    return 1.09


def _level(vdot_mid: float, p: RunnerProfile) -> Level:
    if vdot_mid < 34:
        level = Level.debutant
    elif vdot_mid < 43:
        level = Level.intermediaire
    elif vdot_mid < 53:
        level = Level.confirme
    else:
        level = Level.expert
    km = _weekly_km(p)
    young_practice = p.running_since_months is not None and p.running_since_months < 6
    if level != Level.debutant and ((km is not None and km < 12) or young_practice):
        level = Level(list(Level)[list(Level).index(level) - 1].value)
    return level


def estimate_level(p: RunnerProfile) -> LevelEstimate:
    notes: list[str] = []
    anchor: tuple[float, float, float] | None = None  # distance_km, temps_s rapide, temps_s lent

    if p.recent_race is not None:
        race = p.recent_race
        source: Source = "chrono"
        vdot = vdot_from_performance(race.distance_km, race.time_s)
        spread = 0.02 + min(race.months_ago, 24) / 3 * 0.01
        vdot_low, vdot_high = vdot * (1 - spread), vdot * (1 + 0.02)
        confidence: Confidence = "haute" if race.months_ago <= 6 else "moyenne"
        if race.months_ago > 6:
            notes.append(f"Chrono vieux de {race.months_ago:.0f} mois : fourchette elargie.")
        anchor = (race.distance_km, race.time_s, race.time_s * (1 + spread))
    elif p.cooper_m is not None:
        source = "test_cooper"
        daniels = vdot_from_performance(p.cooper_m / 1000, 720)
        cooper = cooper_vo2max(p.cooper_m)
        vdot_low, vdot_high = min(daniels, cooper) * 0.97, max(daniels, cooper)
        confidence = "moyenne"
        notes.append("Test de Cooper : depend beaucoup de l'effort fourni, a confirmer par un chrono.")
    elif p.longest_recent_run is not None and p.longest_recent_run.duration_min:
        run = p.longest_recent_run
        source = "sortie"
        time_s = run.duration_min * 60
        distance = run.distance_km + (run.d_plus_m or 0) / 100
        vdot_low = vdot_from_performance(distance, time_s * 0.97)
        vdot_high = vdot_from_performance(distance, time_s * 0.85)
        confidence = "moyenne"
        notes.append("Sortie d'entrainement : l'allure de course est supposee 3 a 15 % plus rapide.")
    else:
        source = "declaratif"
        vdot_low, vdot_high = _declarative_vdot(p)
        confidence = "basse"
        notes.append("Aucun chrono : fourchette prudente selon frequence et volume. Un test de 12 min l'affinerait.")

    predictions: dict[str, TimeRange] = {}
    for name, km in DISTANCES_KM.items():
        fast = time_from_vdot(km, vdot_high)
        slow = time_from_vdot(km, vdot_low)
        if anchor is not None:
            a_km, a_fast, a_slow = anchor
            fast = min(fast, riegel(a_fast, a_km, km, 1.06))
            slow = max(slow, riegel(a_slow, a_km, km, _upper_exponent(p, a_km, km)))
        elif km >= 21:
            slow *= 1.05 if km < 30 else 1.10
        predictions[name] = TimeRange(distance=name, low_s=round(fast), high_s=round(slow))

    level = _level((vdot_low + vdot_high) / 2, p)
    return LevelEstimate(
        level=level,
        source=source,
        confidence=confidence,
        vdot_low=round(vdot_low, 1),
        vdot_high=round(vdot_high, 1),
        predictions=predictions,
        notes=notes,
    )


# --- Preparation et garde-fous ---------------------------------------------------

TARGET_LONG_RUN_KM = {"5k": 5.0, "10k": 9.0, "semi": 16.0, "marathon": 30.0}
MIN_WEEKS = {
    "5k": {Level.debutant: 4, Level.intermediaire: 3, Level.confirme: 2, Level.expert: 2},
    "10k": {Level.debutant: 6, Level.intermediaire: 4, Level.confirme: 3, Level.expert: 3},
    "semi": {Level.debutant: 12, Level.intermediaire: 8, Level.confirme: 6, Level.expert: 5},
    "marathon": {Level.debutant: 24, Level.intermediaire: 16, Level.confirme: 12, Level.expert: 10},
}
LONG_RUN_STEP_KM = {Level.debutant: 1.0, Level.intermediaire: 1.5, Level.confirme: 2.0, Level.expert: 2.5}
TAPER_WEEKS = {"5k": 0, "10k": 1, "semi": 1, "marathon": 2}
# Distances maximales hors stade par categorie d'age (reglement FFA, a reverifier).
MAX_KM_BY_AGE = ((16, 10.0), (18, 15.0), (20, 25.0))


def _current_long_run(p: RunnerProfile) -> float:
    if p.longest_recent_run is not None:
        return p.longest_recent_run.distance_km
    if p.recent_race is not None and p.recent_race.months_ago <= 6:
        return p.recent_race.distance_km
    km = _weekly_km(p)
    return max(3.0, km * 0.35) if km else 3.0


def weeks_needed(p: RunnerProfile, distance: str, level: Level) -> tuple[int, int]:
    gap = max(0.0, TARGET_LONG_RUN_KM[distance] - _current_long_run(p))
    progression = math.ceil(gap / LONG_RUN_STEP_KM[level])
    low = max(MIN_WEEKS[distance][level], progression + TAPER_WEEKS[distance])
    sessions = p.sessions_per_week
    if sessions is not None and sessions < 3 and distance in ("semi", "marathon"):
        low += 4
    return low, math.ceil(low * 1.3)


def advise_distance(p: RunnerProfile, estimate: LevelEstimate, distance: str, weeks_available: int | None) -> DistanceAdvice:
    level = estimate.level
    low, high = weeks_needed(p, distance, level)
    km = DISTANCES_KM[distance]

    def advice(verdict: Verdict, reason: str) -> DistanceAdvice:
        return DistanceAdvice(distance=distance, verdict=verdict, weeks_needed_low=low, weeks_needed_high=high, reason=reason)

    if p.age is not None:
        for age_limit, max_km in MAX_KM_BY_AGE:
            if p.age < age_limit and km > max_km:
                return advice("bloque", f"Distance au-dessus du maximum autorise avant {age_limit} ans ({max_km:g} km).")
    if distance == "marathon":
        if weeks_available is not None and weeks_available < 12:
            return advice("bloque", f"Marathon en {weeks_available} semaines : trop court quel que soit le niveau (12 minimum).")
        if level == Level.debutant and weeks_available is not None and weeks_available < MIN_WEEKS["marathon"][Level.debutant]:
            return advice("bloque", "Debutant : marathon seulement avec 6 mois de preparation et un semi deja couru.")
        sessions = p.sessions_per_week
        if sessions is not None and sessions < 3:
            return advice("deconseille", "Moins de 3 sorties par semaine : pas assez pour un marathon en securite.")
    if distance == "semi" and level == Level.debutant and weeks_available is not None and weeks_available < 8:
        return advice("bloque", "Debutant : un semi demande au moins 8 semaines, viser d'abord un 10 km.")
    if weeks_available is None:
        return advice("possible", f"Prevoir {low} a {high} semaines de preparation.")
    if weeks_available >= high:
        return advice("recommande", f"{weeks_available} semaines disponibles pour {low} a {high} necessaires.")
    if weeks_available >= low:
        return advice("possible", f"Juste : {weeks_available} semaines pour {low} a {high} conseillees, objectif finir.")
    return advice("deconseille", f"{weeks_available} semaines pour {low} minimum : risque de blessure, viser plus court.")


def assess(p: RunnerProfile, weeks_available: int | None = None) -> Assessment:
    estimate = estimate_level(p)
    advice = [advise_distance(p, estimate, d, weeks_available) for d in DISTANCES_KM]
    return Assessment(profile=p, estimate=estimate, weeks_available=weeks_available, advice=advice)


def trail_time_range(p: RunnerProfile, distance_km: float, d_plus_m: int) -> TimeRange:
    """Trail : distance-effort = km + D+/100, puis +10 a +25 % pour la technicite."""
    estimate = estimate_level(p)
    effort_km = distance_km + d_plus_m / 100
    fast = time_from_vdot(effort_km, estimate.vdot_high) * 1.10
    slow = time_from_vdot(effort_km, estimate.vdot_low) * 1.25
    return TimeRange(distance=f"trail_{distance_km:g}k_{d_plus_m}dplus", low_s=round(fast), high_s=round(slow))
