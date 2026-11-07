"""Choix de 3 à 5 courses adaptées au niveau, à partir des résultats du finder (live ou cache)."""

import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from runai.coach.cache import DiscoveryCache
from runai.coach.finder import RaceFinder, norm_name, on_domains
from runai.coach.level import advise_distance, race_time_range, trail_time_range
from runai.coach.models import (
    DISTANCE_LABELS,
    DISTANCES_KM,
    Assessment,
    CandidateRace,
    DiscoveryResult,
    Goal,
    RacePreferences,
    RaceRecommendation,
    Recommendations,
    RegistrationStatus,
    RejectedRace,
    SearchQuery,
)

Mode = Literal["auto", "replay", "live"]

MIN_RACES, MAX_RACES = 3, 5
# CGU interdisant explicitement les agents : pas de vérification par H, l'humain vérifie.
NO_AGENT_DOMAINS = ["timeto.com", "finishers.com"]
VERDICT_LABELS = {"recommande": "recommandé", "possible": "possible", "deconseille": "déconseillé", "bloque": "bloqué"}
STATUS_LABELS = {
    RegistrationStatus.complet: "complet",
    RegistrationStatus.liste_attente: "liste d'attente",
    RegistrationStatus.pas_encore_ouvert: "inscriptions pas encore ouvertes",
    RegistrationStatus.ferme: "inscriptions closes",
}


class CacheMiss(LookupError):
    """Mode `replay` sans résultat pré-calculé pour cette requête."""


def _km(value: float) -> str:
    return f"{value:.1f}".replace(".0", "").replace(".", ",")


def distance_category(distance_km: float, elevation_gain_m: float | None = None) -> str:
    """Catégorie de préparation (`5k`…`marathon`) d'après la distance-effort (km + D+/100)."""
    effort = distance_km + (elevation_gain_m or 0) / 100
    if effort < 7.5:
        return "5k"
    if effort < 15:
        return "10k"
    if effort < 32:
        return "semi"
    return "marathon"


def choose_distance(assessment: Assessment) -> str:
    """Distance par défaut : premier 10 km si c'est l'envie, sinon la plus longue recommandée."""
    if Goal.premier_10k in assessment.profile.goals:
        return "10k"
    for name in reversed(list(DISTANCES_KM)):
        if name in assessment.recommended:
            return name
    for name in reversed(list(DISTANCES_KM)):
        if name in assessment.possible and not (name == "marathon" and assessment.estimate.level.value == "debutant"):
            return name
    return "10k"


def build_query(
    assessment: Assessment, preferences: RacePreferences, today: date | None = None
) -> tuple[SearchQuery, list[str]]:
    """Requête figée (et avertissements) : fenêtre de dates, distance cible, trajet."""
    today = today or date.today()
    warnings: list[str] = []
    date_from = preferences.date_from or today + timedelta(weeks=8)
    date_to = preferences.date_to or today + timedelta(weeks=26)
    weeks_max = max(0, (date_to - today).days // 7)

    if preferences.distance_km is not None:
        distance_km = preferences.distance_km
        category = distance_category(distance_km)
        if not preferences.trail:
            advice = advise_distance(assessment.profile, assessment.estimate, category, weeks_max)
            if advice.verdict in ("bloque", "deconseille"):
                fallback = choose_distance(assessment.model_copy(update={"advice": [
                    advise_distance(assessment.profile, assessment.estimate, d, weeks_max) for d in DISTANCES_KM
                ]}))
                warnings.append(
                    f"{DISTANCE_LABELS[category].capitalize()} {VERDICT_LABELS[advice.verdict]} d'ici le "
                    f"{date_to.strftime('%d/%m/%Y')} : {advice.reason} Recherche sur {DISTANCE_LABELS[fallback]}."
                )
                distance_km = DISTANCES_KM[fallback]
    else:
        weeks_min = max(0, (date_from - today).days // 7)
        feasible = [advise_distance(assessment.profile, assessment.estimate, d, weeks_min) for d in DISTANCES_KM]
        distance_km = DISTANCES_KM[choose_distance(assessment.model_copy(update={"advice": feasible}))]

    if preferences.trail:
        label = f"trail de {_km(distance_km)} km"
        tolerance = preferences.distance_tolerance_km if preferences.distance_tolerance_km is not None else max(3.0, 0.25 * distance_km)
    else:
        label = next((DISTANCE_LABELS[n] for n, km in DISTANCES_KM.items() if abs(km - distance_km) < 0.3), f"{_km(distance_km)} km")
        tolerance = preferences.distance_tolerance_km if preferences.distance_tolerance_km is not None else max(1.0, 0.06 * distance_km)

    query = SearchQuery(
        distance_km=round(distance_km, 4),
        distance_label=label,
        tolerance_km=round(tolerance, 2),
        date_from=date_from,
        date_to=date_to,
        origin_city=preferences.origin_city,
        max_travel_h=preferences.max_travel_h,
        travel_mode=preferences.travel_mode,
        terrain="vallonne" if preferences.trail and preferences.terrain == "indifferent" else preferences.terrain,
        race_size=preferences.race_size,
        zone_hint=preferences.zone_hint,
        foreign=preferences.foreign,
        seed_races=preferences.seed_races,
    )
    return query, warnings


def _status_text(c: CandidateRace, needs_h: bool) -> str:
    if c.status is RegistrationStatus.ouvert:
        quote = " ".join(re.sub(r"[\[\]\"]|:.*$", " ", c.status_evidence or "").split())
        evidence = f" (« {quote} » lu sur la page)" if quote else " (lu sur la page)"
        return "inscriptions ouvertes" + evidence
    if not needs_h:
        return "statut à vérifier soi-même (CGU interdisant les agents)"
    if c.check_error:
        return "statut à vérifier par un agent H (page illisible par Linkup)"
    if c.status_source == "agregateur":
        return "dit ouvert par un agrégateur, à confirmer par un agent H"
    return "statut à vérifier par un agent H"


def _rank_one(
    c: CandidateRace, q: SearchQuery, assessment: Assessment, today: date
) -> RaceRecommendation | RejectedRace:
    def reject(why: str) -> RejectedRace:
        return RejectedRace(name=c.name, race_date=c.race_date, city=c.city, why=why)

    if c.status not in (RegistrationStatus.ouvert, RegistrationStatus.a_verifier):
        return reject(STATUS_LABELS.get(c.status, c.status.value))
    if c.race_date and not q.date_from <= c.race_date <= q.date_to:
        return reject(f"date {c.race_date.isoformat()} hors fenêtre")
    if c.race_date and c.race_date <= today:
        return reject("course passée")
    distance = c.distance_km or q.distance_km
    if c.distance_km and abs(c.distance_km - q.distance_km) > q.tolerance_km:
        return reject(f"distance {c.distance_km:g} km hors cible")

    profile, estimate = assessment.profile, assessment.estimate
    trail = q.distance_label.startswith("trail")
    category = distance_category(distance, c.elevation_gain_m if trail else None)
    weeks = max(0, ((c.race_date or q.date_from) - today).days // 7)
    advice = advise_distance(profile, estimate, category, weeks)
    if advice.verdict in ("bloque", "deconseille"):
        return reject(f"préparation {VERDICT_LABELS[advice.verdict]} : {advice.reason}")

    score = 3 - min(3, abs(distance - q.distance_km) / max(q.tolerance_km, 0.1) * 3)
    when = c.race_date.strftime("%d/%m/%Y") if c.race_date else "date à confirmer"
    reasons = [f"{_km(distance)} km le {when}"]
    score += 1 + (2 if advice.verdict == "recommande" else 0.5)
    at_least = "" if c.race_date else "au moins "
    reasons.append(f"{at_least}{weeks} semaines de préparation ({VERDICT_LABELS[advice.verdict]})")
    if trail and c.elevation_gain_m is not None:
        target = trail_time_range(profile, distance, c.elevation_gain_m)
    elif trail:
        target = None
    else:
        target = race_time_range(profile, estimate, distance)
    if target is not None:
        reasons.append(f"objectif réaliste {target.label}")
    if c.elevation_gain_m is not None and distance:
        ratio = c.elevation_gain_m / distance
        if q.terrain == "plat":
            score += 2 if ratio < 8 else (0 if ratio < 20 else -2)
            reasons.append(f"{'parcours plat' if ratio < 8 else 'parcours vallonné'} (D+ {c.elevation_gain_m:g} m)")
        elif q.terrain == "vallonne":
            score += 2 if 25 <= ratio <= 70 else 0.5
            reasons.append(f"D+ {c.elevation_gain_m:g} m, soit {ratio:.0f} m/km")
    if c.travel_h_est is not None:
        score += max(0.0, 2 - 2 * c.travel_h_est / q.max_travel_h)
        mode = "de vol" if q.travel_mode == "flight" else "de trajet"
        reasons.append(f"~{_km(c.travel_h_est)} h {mode} depuis {q.origin_city} (estimé)")
    if c.participants and q.race_size != "indifferent":
        big = c.participants >= 3000
        if (q.race_size == "grande") == big:
            score += 1
            reasons.append(f"{'grande' if big else 'petite'} course ({c.participants} coureurs)")
    url = c.registration_url or c.official_url
    needs_h = c.status is not RegistrationStatus.ouvert and not on_domains(url, NO_AGENT_DOMAINS)
    if c.status is RegistrationStatus.ouvert:
        score += 2
    reasons.append(_status_text(c, needs_h))
    if c.price_eur is not None:
        reasons.append(f"{_km(c.price_eur)} € lus sur la page")
    if c.seed:
        reasons.insert(0, "course que tu as citée")

    return RaceRecommendation(
        name=c.name,
        race_date=c.race_date,
        city=c.city,
        country=c.country,
        distance_km=c.distance_km,
        elevation_gain_m=c.elevation_gain_m,
        platform=c.platform,
        registration_url=url,
        status=c.status,
        status_evidence=c.status_evidence,
        needs_h_check=needs_h,
        price_eur=c.price_eur,
        travel_h_est=c.travel_h_est,
        prep_weeks=weeks,
        prep_verdict=advice.verdict,
        target_time=target,
        score=round(score, 2),
        reason=" ; ".join(reasons) + ".",
        sources=c.sources,
    )


def _same_event(a: RaceRecommendation, b: RaceRecommendation) -> bool:
    """Même date et même lieu : Linkup renvoie souvent la même course sous plusieurs noms/langues."""
    if a.race_date is None or a.race_date != b.race_date or not (a.city and b.city):
        return False
    return _city_key(a.city) == _city_key(b.city)


def _city_key(city: str) -> str:
    plain = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()
    return norm_name(plain)


def rank_races(
    assessment: Assessment, discovery: DiscoveryResult, today: date | None = None, from_cache: bool = False
) -> Recommendations:
    """Classement déterministe (sans réseau) : ouvertes d'abord, complété par « à vérifier » jusqu'à 3."""
    today = today or date.today()
    q = discovery.query
    ranked: list[tuple[CandidateRace, RaceRecommendation]] = []
    excluded: list[RejectedRace] = list(discovery.rejected)
    for c in discovery.candidates:
        result = _rank_one(c, q, assessment, today)
        if isinstance(result, RejectedRace):
            excluded.append(result)
        else:
            ranked.append((c, result))
    ranked.sort(key=lambda pair: -pair[1].score)

    unique: list[tuple[CandidateRace, RaceRecommendation]] = []
    for c, r in sorted(ranked, key=lambda pair: not pair[0].seed):
        twin = next((u for _, u in unique if _same_event(u, r)), None)
        if twin is None:
            unique.append((c, r))
        else:
            excluded.append(RejectedRace(name=r.name, race_date=r.race_date, city=r.city, why=f"doublon de {twin.name}"))
    ranked = sorted(unique, key=lambda pair: -pair[1].score)

    seeds = [r for c, r in ranked if c.seed]
    opened = [r for c, r in ranked if not c.seed and r.status is RegistrationStatus.ouvert]
    to_check = [r for c, r in ranked if not c.seed and r.status is RegistrationStatus.a_verifier]
    chosen = (seeds + opened)[:MAX_RACES]
    for r in to_check:
        if len(chosen) >= MIN_RACES:
            break
        chosen.append(r)

    warnings: list[str] = []
    n_open = sum(r.status is RegistrationStatus.ouvert for r in chosen)
    if len(chosen) < MIN_RACES:
        warnings.append(f"Seulement {len(chosen)} course(s) adaptée(s) trouvée(s) : élargir la fenêtre ou la zone.")
    if n_open < len(chosen):
        warnings.append(f"{len(chosen) - n_open} course(s) à statut non confirmé : vérification H en lecture seule.")
    return Recommendations(
        query=q,
        races=chosen,
        excluded=excluded,
        warnings=warnings,
        from_cache=from_cache,
        discovered_at=discovery.created_at,
        metrics=discovery.metrics,
    )


def recommend_races(
    assessment: Assessment,
    preferences: RacePreferences | None = None,
    *,
    mode: Mode = "auto",
    finder: RaceFinder | None = None,
    cache: DiscoveryCache | None = None,
    today: date | None = None,
    max_cache_age: timedelta | None = timedelta(hours=24),
) -> Recommendations:
    """3 à 5 courses adaptées au niveau, avec raison lisible et statut d'inscription.

    - `mode="replay"` : uniquement le cache (fixtures de démo), aucun réseau ; `CacheMiss` sinon.
    - `mode="live"` : Linkup (20 à 60 s mesurés, ~0,07 $), puis écriture dans le cache.
    - `mode="auto"` (défaut) : cache s'il a moins de `max_cache_age` (les statuts changent), sinon live.
    Bloquant : depuis FastAPI, appeler via `anyio.to_thread.run_sync`.
    """
    preferences = preferences or RacePreferences()
    cache = cache or DiscoveryCache()
    query, warnings = build_query(assessment, preferences, today)
    discovery = None if mode == "live" else cache.get(query)
    stale = discovery is not None and max_cache_age is not None and datetime.now(UTC) - discovery.created_at > max_cache_age
    if mode == "auto" and stale:
        discovery = None
    from_cache = discovery is not None
    if discovery is None:
        if mode == "replay":
            raise CacheMiss(f"aucun résultat en cache pour {query.cache_key()}")
        discovery = (finder or RaceFinder()).run(query)
        cache.put(discovery)
    result = rank_races(assessment, discovery, today, from_cache=from_cache)
    result.warnings = warnings + result.warnings
    return result
