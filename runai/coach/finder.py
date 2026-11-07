"""Recherche de courses ouvertes avec Linkup (port de `spike/trouver_courses`).

Pipeline de `RaceFinder.run(query)` :
1. Découverte : 2 `/search` Linkup `standard` en sortie structurée (+ 1 `/fetch` d'une page
   calendrier citée), plus 1 `/search` par course citée par le coureur (`seed_races`).
2. Filtre déterministe : fenêtre de dates, tolérance de distance, trajet estimé (géocodage
   Open-Meteo + vol d'oiseau).
3. URL d'inscription : 1 `/search` ciblé par course retenue qui n'en a pas.
4. Vérification : `/fetch` de la page d'inscription avec schéma ; le statut est lu sur la page,
   jamais déduit. Pages SPA connues (Njuko, HOKA Semi de Paris : HTTP 400 mesuré) et erreurs de
   fetch -> `a_verifier` (à confier à un agent H en lecture seule).
5. Moins de 3 ouvertes : 2e tour avec une autre formulation.

Aucune session H ici. Mesuré sur 4 profils (07/11/2026) : 20 à 61 s, environ 0,07 $ par profil,
précision 8/12 sur les courses dites ouvertes.
"""

import math
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from runai.coach.models import (
    CandidateRace,
    DiscoveryResult,
    FinderMetrics,
    RegistrationStatus,
    RejectedRace,
    SearchQuery,
    StatusSource,
)
from runai.config import get_settings

# CGU hostiles aux agents/IA (Finishers art. 13.4) ou sans intérêt pour une inscription.
EXCLUDED_DOMAINS = ["finishers.com", "booking.com", "airbnb.com", "airbnb.fr", "strava.com"]
# Un statut lu sur un agrégateur n'est pas vérifié à la source.
AGGREGATORS = [
    "sasdepart.fr", "followmysport.com", "worldsmarathons.com", "running.life", "milesrepublic.com",
    "ahotu.com", "kikourou.net", "jogging-international.net", "marathons.com", "sortiraparis.com",
    "athle.fr", "trainerday.com",
]  # fmt: skip
REGISTRATION_PLATFORMS = [
    "klikego.com", "protiming.fr", "njuko.net", "in.njuko.com", "chronostart.com", "sportinnovation.fr",
    "sporkrono.fr", "ipitos.com", "espace-competition.com", "yaka-inscription.com", "onsinscrit.com",
    "adeorun.com", "wedosport.net", "timepulse.fr", "endu.net", "racemap.com",
]  # fmt: skip
# Pages d'inscription en SPA : Linkup /fetch renvoie HTTP 400 (mesuré), inutile de payer l'appel.
SPA_DOMAINS = ["in.njuko.com", "njuko.net", "reg.hokasemimarathondeparis.com"]
EUROPE = {"AD", "AL", "AT", "BA", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GB", "GR", "HR", "HU", "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MC", "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS", "SE", "SI", "SK", "SM"}

# Coûts unitaires mesurés par delta du solde Linkup (appels isolés, 07/11/2026).
PRICE_SEARCH_STANDARD = 0.006
PRICE_FETCH_JS_SCHEMA = 0.012
PRICE_FETCH_SCHEMA = 0.008

USER_AGENT = "RunAI-hackathon/0.1 (+https://github.com/IbaDemesy/RunAI)"
OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"


class LinkupLike(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any: ...

    def fetch(self, url: str, **kwargs: Any) -> Any: ...


class Geocoder(Protocol):
    def geocode(self, city: str, country: str | None = None) -> tuple[float, float, str] | None:
        """(latitude, longitude, code pays ISO) ou None."""
        ...


def default_linkup_client() -> LinkupLike:
    from linkup import LinkupClient

    api_key = get_settings().linkup_api_key
    if not api_key:
        raise RuntimeError("LINKUP_API_KEY manquante : renseignez-la dans .env")
    return LinkupClient(api_key=api_key)


class OpenMeteoGeocoder:
    """Géocodage de villes (API Open-Meteo, sans clé), avec cache en mémoire."""

    def __init__(self, client: httpx.Client | None = None, europe_only: bool = True):
        self._client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10)
        self._europe_only = europe_only
        self._cache: dict[tuple[str, str | None], tuple[float, float, str] | None] = {}

    def geocode(self, city: str, country: str | None = None) -> tuple[float, float, str] | None:
        key = (city, country)
        if key in self._cache:
            return self._cache[key]
        name = re.split(r"[(,/]", city)[0].strip()
        hits: list[dict[str, Any]] | None = None
        for _ in range(3):
            try:
                response = self._client.get(OPEN_METEO_URL, params={"name": name, "count": 5, "language": "fr"})
                hits = response.json().get("results") or []
                break
            except (httpx.HTTPError, ValueError):
                time.sleep(1)
        if hits is None:
            return None
        if country:
            wanted = country.lower()
            hits = [h for h in hits if wanted in (h.get("country", "").lower(), h.get("country_code", "").lower())] or hits
        if self._europe_only:
            hits = [h for h in hits if h.get("country_code", "").upper() in EUROPE] or hits
        result = None
        if hits:
            best = max(hits, key=lambda h: h.get("population") or 0)
            result = (best["latitude"], best["longitude"], best.get("country_code", ""))
        self._cache[key] = result
        return result


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def travel_hours(km: float, mode: str) -> float:
    """Estimation grossière : sol = 1,3 x vol d'oiseau à 90 km/h ; avion = 750 km/h + 0,5 h."""
    if mode == "flight":
        return km / 750 + 0.5
    return km * 1.3 / 90


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def norm_name(name: str) -> str:
    name = re.sub(r"20\d\d", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "", name)[:40]


def on_domains(url: str | None, domains: list[str]) -> bool:
    return bool(url) and any(d in url for d in domains)


# --- Schémas Linkup ---------------------------------------------------------------------------


class _Candidate(BaseModel):
    name: str
    date: str | None = Field(None, description="Date de la course, ISO YYYY-MM-DD")
    city: str | None = Field(None, description="Ville du départ")
    country: str | None = None
    distance_km: float | None = Field(None, description="Distance de l'épreuve visée, en km")
    elevation_gain_m: float | None = Field(None, description="D+ en mètres si indiqué")
    registration_url: str | None = Field(None, description="URL de la page d'inscription (plateforme ou site officiel)")
    official_url: str | None = None
    platform: str | None = Field(None, description="Plateforme d'inscription (Njuko, Klikego, Protiming, site officiel...)")
    registration_status: str | None = Field(
        None, description="Statut des inscriptions tel qu'écrit par la source : ouvertes, complet, pas encore ouvertes, inconnu"
    )
    participants: int | None = Field(None, description="Nombre de participants ou de dossards")
    source_url: str | None = Field(None, description="URL de la page qui donne ces infos")


class _CandidateList(BaseModel):
    races: list[_Candidate]


class _RegistrationLookup(BaseModel):
    registration_url: str | None = Field(None, description="URL directe de la page d'inscription de cette édition")
    official_url: str | None = None
    platform: str | None = None
    race_date: str | None = Field(None, description="Date ISO YYYY-MM-DD")
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    registration_status: str | None = None


class _PageCheck(BaseModel):
    registration_status: Literal["open", "full", "waitlist", "not_yet_open", "closed", "unknown"] = Field(
        description="Statut des inscriptions pour l'épreuve visée, d'après la page uniquement"
    )
    status_evidence: str | None = Field(None, description="Phrase exacte de la page qui justifie le statut")
    race_name: str | None = None
    race_date: str | None = Field(None, description="ISO YYYY-MM-DD")
    city: str | None = None
    target_distance_km: float | None = None
    elevation_gain_m: float | None = None
    current_price_eur: float | None = Field(None, description="Prix actuel de l'épreuve visée, en euros")
    price_tier: str | None = Field(None, description="Palier tarifaire en cours si indiqué")
    participants_max: int | None = None


PAGE_STATUS = {
    "open": RegistrationStatus.ouvert,
    "full": RegistrationStatus.complet,
    "waitlist": RegistrationStatus.liste_attente,
    "not_yet_open": RegistrationStatus.pas_encore_ouvert,
    "closed": RegistrationStatus.ferme,
    "unknown": RegistrationStatus.a_verifier,
}
ENGLISH_LABELS = {"5 km": "5K race", "10 km": "10K race", "semi-marathon": "Half marathon", "marathon": "Marathon"}
CALENDAR_HINT = re.compile(r"calendrier|calendar|courses-pres-de|/run/|agenda", re.IGNORECASE)


def _data(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", response)
    if isinstance(data, BaseModel):
        data = data.model_dump()
    return data if isinstance(data, dict) else {}


def _first_line(exc: Exception) -> str:
    return (str(exc).splitlines() or [type(exc).__name__])[0][:160]


class RaceFinder:
    """Trouve et vérifie des courses pour une `SearchQuery`. Client Linkup et géocodeur injectables."""

    def __init__(
        self,
        client: LinkupLike | None = None,
        geocoder: Geocoder | None = None,
        max_verify: int = 8,
        calendar_fetch: bool = True,
        workers: int = 3,
    ):
        self._client = client
        self._geocoder = geocoder
        self.max_verify = max_verify
        self.calendar_fetch = calendar_fetch
        self.workers = workers  # 8 appels parallèles -> HTTP 429 mesuré, 3 passent

    @property
    def client(self) -> LinkupLike:
        if self._client is None:
            self._client = default_linkup_client()
        return self._client

    @property
    def geocoder(self) -> Geocoder:
        if self._geocoder is None:
            self._geocoder = OpenMeteoGeocoder()
        return self._geocoder

    def run(self, query: SearchQuery) -> DiscoveryResult:
        metrics = FinderMetrics()
        log: list[str] = []
        sources: list[str] = []
        t0 = time.monotonic()

        candidates = self._discover(query, metrics, log, sources)
        t1 = time.monotonic()
        kept, rejected = self._prefilter(query, candidates)
        t2 = time.monotonic()
        self._enrich(query, kept, metrics, log)
        t3 = time.monotonic()
        verified = self._verify(query, kept, metrics)
        if sum(c.status is RegistrationStatus.ouvert for c in verified) < 3:
            known = {norm_name(c.name) for c in kept} | {norm_name(r.name) for r in rejected}
            extra = [
                c
                for c in self._search(self._second_round_prompt(query), metrics, log, sources)
                if norm_name(c.name) not in known
            ]
            k2, r2 = self._prefilter(query, extra)
            self._enrich(query, k2, metrics, log)
            self._verify(query, k2, metrics)
            kept += k2
            rejected += r2
            metrics.second_round = True
        t4 = time.monotonic()
        metrics.phases_s = {
            "decouverte": round(t1 - t0, 2),
            "filtre_geo": round(t2 - t1, 2),
            "url_inscription": round(t3 - t2, 2),
            "verification": round(t4 - t3, 2),
        }
        metrics.total_s = round(t4 - t0, 2)
        metrics.cost_usd_estimated = round(metrics.cost_usd_estimated, 3)
        return DiscoveryResult(query=query, candidates=kept, rejected=rejected, metrics=metrics, notes=log)

    # --- Découverte ---------------------------------------------------------------------------

    def _search(
        self, prompt: str, metrics: FinderMetrics, log: list[str], sources: list[str], **kwargs: Any
    ) -> list[CandidateRace]:
        metrics.search_calls += 1
        metrics.cost_usd_estimated += PRICE_SEARCH_STANDARD
        try:
            response = self.client.search(
                query=prompt,
                depth="standard",
                output_type="structured",
                structured_output_schema=_CandidateList,
                include_sources=True,
                exclude_domains=None if "include_domains" in kwargs else EXCLUDED_DOMAINS,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - une recherche ratée ne bloque pas les autres
            log.append(f"search_error: {_first_line(exc)}")
            return []
        found = [s.url for s in getattr(response, "sources", None) or [] if getattr(s, "url", None)]
        sources.extend(found)
        races = [self._to_candidate(raw) for raw in _data(response).get("races", []) or []]
        return [race for race in races if race is not None]

    @staticmethod
    def _to_candidate(raw: Any, seed: bool = False) -> CandidateRace | None:
        try:
            c = raw if isinstance(raw, _Candidate) else _Candidate.model_validate(raw)
        except ValidationError:
            return None
        if not c.name:
            return None
        return CandidateRace(
            name=c.name,
            race_date=parse_date(c.date),
            city=c.city,
            country=c.country,
            distance_km=c.distance_km,
            elevation_gain_m=c.elevation_gain_m,
            platform=c.platform,
            registration_url=None if on_domains(c.registration_url, EXCLUDED_DOMAINS) else c.registration_url,
            official_url=c.official_url,
            participants=c.participants,
            status_from_search=c.registration_status,
            sources=[c.source_url] if c.source_url else [],
            seed=seed,
        )

    @staticmethod
    def _fields_prompt() -> str:
        return (
            "Pour chaque course donne : nom, date exacte (YYYY-MM-DD), ville et pays du départ, distance de l'épreuve, "
            "D+ si indiqué, URL de la page d'inscription, plateforme d'inscription, statut des inscriptions tel "
            "qu'écrit (ouvertes, complet, pas encore ouvertes), nombre de participants, URL source. "
            "Liste toutes les courses trouvées, même si le statut est inconnu."
        )

    def _discover(
        self, q: SearchQuery, metrics: FinderMetrics, log: list[str], sources: list[str]
    ) -> list[CandidateRace]:
        window = f"entre le {q.date_from.isoformat()} et le {q.date_to.isoformat()}"
        relief = {"plat": "parcours plat et roulant", "vallonne": "parcours vallonné avec du dénivelé"}.get(q.terrain, "")
        year = q.date_from.year
        q1 = (
            f"Calendrier {year} : courses de {q.distance_label} {q.zone_hint} {window}, {relief}. "
            f"Liste 10 courses. {self._fields_prompt()}"
        )
        jobs: list[Callable[[], list[CandidateRace]]] = [lambda: self._search(q1, metrics, log, sources)]
        if q.foreign:
            english = ENGLISH_LABELS.get(q.distance_label, f"Trail race of about {q.distance_km:g} km")
            mode = "flight" if q.travel_mode == "flight" else "travel"
            q2 = (
                f"{english} {year} in Europe outside France between {q.date_from.isoformat()} and "
                f"{q.date_to.isoformat()} with registration open, under {q.max_travel_h:g} hours {mode} from "
                f"{q.origin_city}. For each race: name, exact date, city, country, distance, registration URL, "
                "registration platform, registration status, number of runners, source URL."
            )
            jobs.append(lambda: self._search(q2, metrics, log, sources))
        else:
            q2 = f"Inscriptions ouvertes {q.distance_label} {year} {q.zone_hint} {window}. {self._fields_prompt()}"
            domains = [*REGISTRATION_PLATFORMS, "sasdepart.fr", "athle.fr"]
            jobs.append(lambda: self._search(q2, metrics, log, sources, include_domains=domains))
        for seed in q.seed_races:
            jobs.append(lambda seed=seed: self._seed(seed, q, metrics, log))
        with ThreadPoolExecutor(self.workers) as pool:
            races = [race for batch in pool.map(lambda job: job(), jobs) for race in batch]
        if self.calendar_fetch:
            races += self._calendar(q, metrics, log, sources)

        merged: dict[str, CandidateRace] = {}
        for race in races:
            key = norm_name(race.name)
            if key not in merged:
                merged[key] = race
                continue
            old = merged[key]
            updates = {f: v for f, v in race.model_dump().items() if getattr(old, f) in (None, "", []) and v not in (None, "", [])}
            merged[key] = old.model_copy(update={**updates, "seed": old.seed or race.seed})
        return list(merged.values())

    def _seed(self, name: str, q: SearchQuery, metrics: FinderMetrics, log: list[str]) -> list[CandidateRace]:
        metrics.search_calls += 1
        metrics.cost_usd_estimated += PRICE_SEARCH_STANDARD
        try:
            response = self.client.search(
                query=(
                    f"Course à pied « {name} », épreuve {q.distance_label}, prochaine édition entre le "
                    f"{q.date_from.isoformat()} et le {q.date_to.isoformat()} : nom officiel, date, ville, pays, "
                    "distance, D+, URL de la page d'inscription officielle, plateforme, statut des inscriptions, URL source."
                ),
                depth="standard",
                output_type="structured",
                structured_output_schema=_Candidate,
                exclude_domains=EXCLUDED_DOMAINS,
            )
        except Exception as exc:  # noqa: BLE001
            log.append(f"seed_error ({name}): {_first_line(exc)}")
            return []
        race = self._to_candidate(_data(response), seed=True)
        return [race] if race is not None else []

    def _calendar(
        self, q: SearchQuery, metrics: FinderMetrics, log: list[str], sources: list[str]
    ) -> list[CandidateRace]:
        """Lit la 1re page calendrier citée par les recherches."""
        url = next(
            (u for u in sources if CALENDAR_HINT.search(u) and not on_domains(u, [*EXCLUDED_DOMAINS, "ahotu.com"])),
            None,
        )
        if url is None:
            return []
        metrics.fetch_calls += 1
        try:
            response = self.client.fetch(
                url=url,
                schema=_CandidateList,
                instructions=(
                    f"Liste toutes les courses entre le {q.date_from.isoformat()} et le {q.date_to.isoformat()} avec "
                    "leur nom, date, ville, distances, D+, lien d'inscription et statut des inscriptions tel qu'affiché."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            metrics.fetch_errors += 1
            log.append(f"calendar_error ({url}): {_first_line(exc)}")
            return []
        metrics.cost_usd_estimated += PRICE_FETCH_SCHEMA
        races = []
        for raw in _data(response).get("races", []) or []:
            if isinstance(raw, dict):
                raw = {**raw, "source_url": raw.get("source_url") or url}
            race = self._to_candidate(raw)
            if race is not None:
                races.append(race)
        return races

    # --- Filtre, URL d'inscription, vérification ----------------------------------------------

    def _prefilter(
        self, q: SearchQuery, candidates: list[CandidateRace]
    ) -> tuple[list[CandidateRace], list[RejectedRace]]:
        origin = self.geocoder.geocode(q.origin_city)
        kept: list[CandidateRace] = []
        rejected: list[RejectedRace] = []
        for c in candidates:
            why = None
            if c.race_date and not q.date_from <= c.race_date <= q.date_to:
                why = f"date {c.race_date.isoformat()} hors fenêtre"
            elif c.distance_km and abs(c.distance_km - q.distance_km) > q.tolerance_km:
                why = f"distance {c.distance_km:g} km hors cible"
            elif c.city and origin:
                point = self.geocoder.geocode(c.city, c.country)
                if point:
                    km = haversine_km(origin[:2], point[:2])
                    c.km_from_origin = round(km)
                    c.travel_h_est = round(travel_hours(km, q.travel_mode), 2)
                    if q.foreign and point[2].upper() == "FR":
                        why = "en France alors que l'étranger est demandé"
                    elif c.travel_h_est > q.max_travel_h:
                        why = f"trajet estimé {c.travel_h_est:g} h > {q.max_travel_h:g} h"
            if why:
                rejected.append(RejectedRace(name=c.name, race_date=c.race_date, city=c.city, why=why))
            else:
                kept.append(c)
        kept.sort(key=lambda c: (not c.seed, c.registration_url is None, c.travel_h_est or 99))
        return kept, rejected

    def _enrich(self, q: SearchQuery, rows: list[CandidateRace], metrics: FinderMetrics, log: list[str]) -> None:
        """Cherche l'URL d'inscription des candidats qui n'en ont pas (1 /search chacun)."""
        todo = [c for c in rows[: self.max_verify] if not c.registration_url]

        def lookup(c: CandidateRace) -> tuple[CandidateRace, _RegistrationLookup | None]:
            try:
                response = self.client.search(
                    query=(
                        f"Page d'inscription officielle de la course {c.name} ({c.city or ''}) édition "
                        f"{q.date_from.year}, épreuve {q.distance_label} : URL d'inscription, plateforme, date, "
                        "distance, D+, statut des inscriptions."
                    ),
                    depth="standard",
                    output_type="structured",
                    structured_output_schema=_RegistrationLookup,
                    exclude_domains=EXCLUDED_DOMAINS,
                )
                return c, _RegistrationLookup.model_validate(_data(response))
            except Exception as exc:  # noqa: BLE001
                log.append(f"enrich_error ({c.name}): {_first_line(exc)}")
                return c, None

        with ThreadPoolExecutor(self.workers) as pool:
            results = list(pool.map(lookup, todo))
        for c, found in results:
            metrics.search_calls += 1
            metrics.cost_usd_estimated += PRICE_SEARCH_STANDARD
            if found is None:
                continue
            if found.registration_url and not on_domains(found.registration_url, EXCLUDED_DOMAINS):
                c.registration_url = found.registration_url
            c.official_url = c.official_url or found.official_url
            c.platform = c.platform or found.platform
            c.race_date = c.race_date or parse_date(found.race_date)
            c.distance_km = c.distance_km or found.distance_km
            c.elevation_gain_m = c.elevation_gain_m or found.elevation_gain_m
            c.status_from_search = c.status_from_search or found.registration_status

    def _verify(self, q: SearchQuery, rows: list[CandidateRace], metrics: FinderMetrics) -> list[CandidateRace]:
        todo = [c for c in rows if c.registration_url or c.official_url][: self.max_verify]
        to_fetch = []
        for c in todo:
            url = c.registration_url or c.official_url
            if on_domains(url, SPA_DOMAINS):
                metrics.skipped_fetches += 1
                c.status = RegistrationStatus.a_verifier
                c.check_error = "page d'inscription en SPA, illisible par Linkup : à vérifier par un agent H"
                c.sources = list(dict.fromkeys([*c.sources, url]))
            else:
                to_fetch.append(c)

        def check(c: CandidateRace) -> tuple[CandidateRace, _PageCheck | None, str | None]:
            url = c.registration_url or c.official_url or ""
            try:
                response = self.client.fetch(
                    url=url,
                    render_js=True,
                    schema=_PageCheck,
                    instructions=(
                        f"Course visée : {c.name}, épreuve de {q.distance_label}. Lis uniquement ce que la page affiche. "
                        "open = bouton ou formulaire d'inscription actif pour cette épreuve ; full = complet / sold out ; "
                        "waitlist = liste d'attente ; not_yet_open = ouverture annoncée plus tard ; closed = clôturées ; "
                        "unknown si la page ne le dit pas. Ne devine pas les prix ni le D+."
                    ),
                )
                data = _data(response) or {"registration_status": "unknown"}
                return c, _PageCheck.model_validate(data), None
            except Exception as exc:  # noqa: BLE001
                return c, None, _first_line(exc)

        with ThreadPoolExecutor(self.workers) as pool:
            results = list(pool.map(check, to_fetch))
        for c, page, error in results:
            url = c.registration_url or c.official_url or ""
            c.sources = list(dict.fromkeys([*c.sources, url]))
            metrics.fetch_calls += 1
            if error or page is None:
                metrics.fetch_errors += 1
                c.status = RegistrationStatus.a_verifier
                c.check_error = error or "réponse vide"
                continue
            metrics.cost_usd_estimated += PRICE_FETCH_JS_SCHEMA
            source: StatusSource = "agregateur" if on_domains(url, AGGREGATORS) else "page"
            status = PAGE_STATUS[page.registration_status]
            if status is RegistrationStatus.ouvert and source == "agregateur":
                status = RegistrationStatus.a_verifier
            c.status, c.status_source, c.status_evidence = status, source, page.status_evidence
            c.name = page.race_name or c.name
            c.race_date = parse_date(page.race_date) or c.race_date
            c.city = page.city or c.city
            c.distance_km = page.target_distance_km or c.distance_km
            c.elevation_gain_m = page.elevation_gain_m if page.elevation_gain_m is not None else c.elevation_gain_m
            c.price_eur, c.price_tier = page.current_price_eur, page.price_tier
            c.participants = page.participants_max or c.participants
        return todo

    @staticmethod
    def _second_round_prompt(q: SearchQuery) -> str:
        return (
            f"{q.distance_label} {q.zone_hint} entre le {q.date_from.isoformat()} et le {q.date_to.isoformat()} : "
            f"courses dont les inscriptions {q.date_from.year} sont déjà ouvertes (bouton S'inscrire actif). "
            "Pour chaque course : nom, date YYYY-MM-DD, ville, pays, distance, D+, URL d'inscription, plateforme, "
            "statut, URL source."
        )
