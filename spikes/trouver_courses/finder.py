"""Axe B : a partir d'un profil coureur, proposer 3-5 courses OUVERTES.

Pipeline :
1. Decouverte : 2 recherches Linkup /search (standard, sortie structuree).
2. Filtre deterministe : fenetre de dates, distance, temps de trajet estime
   (geocodage Open-Meteo / api-adresse.data.gouv.fr + haversine).
3. Verification : Linkup /fetch (renderJs + schema) sur la page d'inscription
   de chaque candidat retenu ; statut lu sur la page, jamais deduit.
4. Classement et raison de la recommandation, en code (pas de LLM).

Aucun appel H ici. Les pages que Linkup ne sait pas lire (ex. Njuko, SPA)
sont marquees "a_verifier_par_H".
"""

from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Literal

import httpx
from linkup import LinkupClient
from pydantic import BaseModel, Field

# Sites exclus de la decouverte : CGU interdisant agents/IA/calendriers
# derives (Finishers, art. 13.4) ou anti-agents (Booking, Airbnb, Strava).
EXCLUDED_DOMAINS = [
    "finishers.com",
    "booking.com",
    "airbnb.com",
    "airbnb.fr",
    "strava.com",
]
# Agregateurs : un statut lu ici n'est pas verifie a la source.
AGGREGATORS = [
    "sasdepart.fr",
    "followmysport.com",
    "worldsmarathons.com",
    "running.life",
    "milesrepublic.com",
    "ahotu.com",
    "kikourou.net",
    "jogging-international.net",
    "marathons.com",
    "sortiraparis.com",
    "athle.fr",
    "trainerday.com",
]
EUROPE = {
    "AD",
    "AL",
    "AT",
    "BA",
    "BE",
    "BG",
    "CH",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GB",
    "GR",
    "HR",
    "HU",
    "IE",
    "IS",
    "IT",
    "LI",
    "LT",
    "LU",
    "LV",
    "MC",
    "ME",
    "MK",
    "MT",
    "NL",
    "NO",
    "PL",
    "PT",
    "RO",
    "RS",
    "SE",
    "SI",
    "SK",
    "SM",
}
REGISTRATION_PLATFORMS = [
    "klikego.com",
    "protiming.fr",
    "njuko.net",
    "in.njuko.com",
    "chronostart.com",
    "sportinnovation.fr",
    "sporkrono.fr",
    "ipitos.com",
    "espace-competition.com",
    "yaka-inscription.com",
    "onsinscrit.com",
    "adeorun.com",
    "wedosport.net",
    "timepulse.fr",
    "endu.net",
    "racemap.com",
]

# Couts mesures par delta du solde Linkup (1 appel isole, 07/11/2026).
PRICE_SEARCH_STANDARD = 0.006
PRICE_SEARCH_DEEP = 0.055  # tarif doc, non mesure
PRICE_FETCH_JS_SCHEMA = 0.012
PRICE_FETCH_SCHEMA = 0.008

UA = {"User-Agent": "RunAI-spike/0.1 (hackathon; camille.martin@example.com)"}
TODAY = date(2026, 11, 7)


class RunnerProfile(BaseModel):
    id: str
    label: str
    distance_km: float
    distance_tolerance_km: float | None = None
    distance_label: str
    date_from: str
    date_to: str
    origin_city: str
    max_travel_h: float
    travel_mode: Literal["ground", "flight"] = "ground"
    terrain: Literal["plat", "vallonne", "indifferent"] = "indifferent"
    race_size: Literal["petite", "grande", "indifferent"] = "indifferent"
    level: Literal["debutant", "intermediaire", "confirme"] = "intermediaire"
    zone_hint: str = ""
    foreign: bool = False

    def tolerance(self) -> float:
        if self.distance_tolerance_km is not None:
            return self.distance_tolerance_km
        return max(1.0, 0.06 * self.distance_km)

    def min_prep_weeks(self) -> int:
        base = {"debutant": 8, "intermediaire": 8, "confirme": 6}[self.level]
        return base + (4 if self.distance_km >= 21 else 0)


# --- Schemas Linkup -------------------------------------------------------


class Candidate(BaseModel):
    name: str
    date: str | None = Field(None, description="Date de la course, ISO YYYY-MM-DD")
    city: str | None = Field(None, description="Ville du depart")
    country: str | None = None
    distance_km: float | None = Field(
        None, description="Distance de l'epreuve visee, en km"
    )
    elevation_gain_m: float | None = Field(None, description="D+ en metres si indique")
    registration_url: str | None = Field(
        None, description="URL de la page d'inscription (plateforme ou site officiel)"
    )
    official_url: str | None = None
    platform: str | None = Field(
        None,
        description="Plateforme d'inscription (Njuko, Klikego, Protiming, site officiel...)",
    )
    registration_status: str | None = Field(
        None,
        description="Statut des inscriptions tel qu'ecrit par la source : ouvertes, complet, pas encore ouvertes, inconnu",
    )
    participants: int | None = Field(
        None, description="Nombre de participants ou de dossards"
    )
    source_url: str | None = Field(
        None, description="URL de la page qui donne ces infos"
    )


class CandidateList(BaseModel):
    races: list[Candidate]


class RegistrationLookup(BaseModel):
    registration_url: str | None = Field(
        None, description="URL directe de la page d'inscription 2027"
    )
    official_url: str | None = None
    platform: str | None = None
    race_date: str | None = Field(None, description="Date 2027 ISO YYYY-MM-DD")
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    registration_status: str | None = None


class PageCheck(BaseModel):
    registration_status: Literal[
        "open", "full", "waitlist", "not_yet_open", "closed", "unknown"
    ] = Field(
        description="Statut des inscriptions pour l'epreuve visee, d'apres la page uniquement"
    )
    status_evidence: str | None = Field(
        None, description="Phrase exacte de la page qui justifie le statut"
    )
    race_name: str | None = None
    race_date: str | None = Field(None, description="ISO YYYY-MM-DD")
    city: str | None = None
    distances_km: list[float] | None = None
    target_distance_km: float | None = None
    elevation_gain_m: float | None = None
    current_price_eur: float | None = Field(
        None, description="Prix actuel de l'epreuve visee, en euros"
    )
    price_tier: str | None = Field(
        None, description="Palier tarifaire en cours si indique"
    )
    registration_deadline: str | None = None
    participants_max: int | None = None


# --- Outils ---------------------------------------------------------------


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


_GEO_CACHE: dict[str, tuple[float, float, str] | None] = {}


def geocode(
    city: str, country: str | None = None, europe_only: bool = True
) -> tuple[float, float, str] | None:
    key = f"{city}|{country}|{europe_only}"
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    name = re.split(r"[(,/]", city)[0].strip()
    for _ in range(3):
        try:
            r = httpx.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": name, "count": 5, "language": "fr"},
                headers=UA,
                timeout=10,
            )
            hits = r.json().get("results") or []
        except (httpx.HTTPError, ValueError):
            time.sleep(1)
            continue
        if country:
            c = country.lower()
            same = [
                h
                for h in hits
                if c
                in (h.get("country", "").lower(), h.get("country_code", "").lower())
            ]
            hits = same or hits
        if europe_only:
            hits = [
                h for h in hits if h.get("country_code", "").upper() in EUROPE
            ] or hits
        res = None
        if hits:
            h = max(hits, key=lambda x: x.get("population") or 0)
            res = (h["latitude"], h["longitude"], h.get("country_code", ""))
        _GEO_CACHE[key] = res
        return res
    return None


def travel_hours(km: float, mode: str) -> float:
    """Estimation grossiere : sol = 1,3 x vol d'oiseau a 90 km/h ; avion = 750 km/h + 0,5 h."""
    if mode == "flight":
        return km / 750 + 0.5
    return km * 1.3 / 90


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def norm_name(s: str) -> str:
    s = s.lower()
    s = re.sub(r"20\d\d", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)[:40]


# --- Pipeline -------------------------------------------------------------


class Metrics(BaseModel):
    search_calls: int = 0
    enrich_calls: int = 0
    calendar_fetch_calls: int = 0
    fetch_calls: int = 0
    fetch_errors: int = 0
    search_s: list[float] = []
    enrich_s: list[float] = []
    calendar_fetch_s: list[float] = []
    phases_s: dict[str, float] = {}
    fetch_s: list[float] = []
    total_s: float = 0
    cost_usd_computed: float = 0
    second_round: bool = False


CALENDAR_HINT = re.compile(
    r"calendrier|calendar|courses-pres-de|/run/|agenda", re.IGNORECASE
)


class Finder:
    def __init__(
        self,
        client: LinkupClient | None = None,
        max_verify: int = 8,
        calendar_fetch: bool = True,
    ):
        self.c = client or LinkupClient()
        self.max_verify = max_verify
        self.calendar_fetch = calendar_fetch
        self.m = Metrics()
        self.log: list[dict] = []
        self.sources: list[str] = []

    def _search(self, query: str, **kw) -> list[Candidate]:
        t = time.time()
        try:
            r = self.c.search(
                query=query,
                depth="standard",
                output_type="structured",
                structured_output_schema=CandidateList,
                include_sources=True,
                exclude_domains=EXCLUDED_DOMAINS
                if "include_domains" not in kw
                else None,
                **kw,
            )
        except Exception as e:  # noqa: BLE001
            self.log.append({"search_error": str(e)[:200], "query": query})
            return []
        finally:
            self.m.search_s.append(round(time.time() - t, 2))
            self.m.search_calls += 1
            self.m.cost_usd_computed += PRICE_SEARCH_STANDARD
        data = r.data if hasattr(r, "data") else r
        if isinstance(data, BaseModel):
            data = data.model_dump()
        races = [Candidate(**x) for x in (data or {}).get("races", []) if x.get("name")]
        self.sources += [s.url for s in getattr(r, "sources", [])]
        self.log.append(
            {
                "query": query,
                "kw": {k: v for k, v in kw.items()},
                "n_races": len(races),
                "sources": [s.url for s in getattr(r, "sources", [])][:10],
            }
        )
        return races

    def discover(self, p: RunnerProfile) -> list[Candidate]:
        months = f"entre le {p.date_from} et le {p.date_to}"
        relief = {
            "plat": "parcours plat et roulant",
            "vallonne": "parcours vallonne avec du denivele",
            "indifferent": "",
        }[p.terrain]
        fields = (
            "Pour chaque course donne : nom, date exacte (YYYY-MM-DD), ville et pays du depart, "
            "distance de l'epreuve, D+ si indique, URL de la page d'inscription, plateforme d'inscription, "
            "statut des inscriptions tel qu'ecrit (ouvertes, complet, pas encore ouvertes), nombre de participants, URL source. "
            "Liste toutes les courses trouvees, meme si le statut est inconnu."
        )
        q1 = f"Calendrier 2027 : courses de {p.distance_label} {p.zone_hint} {months}, {relief}. Liste 10 courses. {fields}"
        q2 = f"Inscriptions ouvertes {p.distance_label} 2027 {p.zone_hint} {months}. {fields}"
        with ThreadPoolExecutor(2) as ex:
            f1 = ex.submit(self._search, q1)
            if p.foreign:
                q2 = (
                    f"Half marathon 2027 in Europe outside France {months} with registration open, "
                    "flat and fast course, under 2 hours flight from Paris. For each race: name, exact date, city, country, "
                    "distance, registration URL, registration platform, registration status, number of runners, source URL."
                )
                f2 = ex.submit(self._search, q2)
            else:
                f2 = ex.submit(
                    self._search,
                    q2,
                    include_domains=REGISTRATION_PLATFORMS
                    + ["sasdepart.fr", "athle.fr"],
                )
            races = f1.result() + f2.result()
        if self.calendar_fetch:
            races += self._calendar(p)
        seen: dict[str, Candidate] = {}
        for r in races:
            k = norm_name(r.name)
            if k in seen:
                old = seen[k]
                for f, v in r.model_dump().items():
                    if getattr(old, f) in (None, "") and v not in (None, ""):
                        setattr(old, f, v)
            else:
                seen[k] = r
        return list(seen.values())

    def _calendar(self, p: RunnerProfile) -> list[Candidate]:
        """Lit la 1re page calendrier (liste) parmi les sources des recherches."""
        url = next(
            (
                u
                for u in self.sources
                if CALENDAR_HINT.search(u)
                and not any(d in u for d in EXCLUDED_DOMAINS + ["ahotu.com"])
            ),
            None,
        )
        if not url:
            return []
        t = time.time()
        try:
            r = self.c.fetch(
                url=url,
                schema=CandidateList,
                instructions=(
                    f"Liste toutes les courses entre le {p.date_from} et le {p.date_to} avec leur nom, date, ville, "
                    "distances, D+, lien d'inscription et statut des inscriptions tel qu'affiche."
                ),
            )
            data = (
                r.data.model_dump() if isinstance(r.data, BaseModel) else (r.data or {})
            )
            races = [
                Candidate(**{**x, "source_url": x.get("source_url") or url})
                for x in data.get("races", [])
                if x.get("name")
            ]
            self.m.cost_usd_computed += PRICE_FETCH_SCHEMA
        except Exception as e:  # noqa: BLE001
            races = []
            self.log.append(
                {"calendar_error": str(e).splitlines()[0][:160], "url": url}
            )
        self.m.calendar_fetch_calls += 1
        self.m.calendar_fetch_s.append(round(time.time() - t, 2))
        self.log.append({"calendar_url": url, "n_races": len(races)})
        return races

    def enrich(self, p: RunnerProfile, rows: list[dict]) -> None:
        """Trouve l'URL d'inscription des candidats qui n'en ont pas (1 /search standard chacun)."""
        for r in rows:
            u = r["cand"].registration_url
            if u and any(d in u for d in EXCLUDED_DOMAINS):
                r["cand"].registration_url = None
        todo = [r for r in rows[: self.max_verify] if not r["cand"].registration_url]

        def run(row):
            c = row["cand"]
            t = time.time()
            try:
                r = self.c.search(
                    query=(
                        f"Page d'inscription officielle de la course {c.name} ({c.city or ''}) edition 2027, "
                        f"epreuve {p.distance_label} : URL d'inscription, plateforme, date, distance, D+, statut des inscriptions."
                    ),
                    depth="standard",
                    output_type="structured",
                    structured_output_schema=RegistrationLookup,
                    exclude_domains=EXCLUDED_DOMAINS,
                )
                d = r.model_dump() if isinstance(r, BaseModel) else r
                d = d.get("data", d) if isinstance(d, dict) else {}
                return row, RegistrationLookup(**(d or {})), time.time() - t
            except Exception as e:  # noqa: BLE001
                self.log.append(
                    {"enrich_error": str(e).splitlines()[0][:160], "race": c.name}
                )
                return row, None, time.time() - t

        with ThreadPoolExecutor(5) as ex:
            out = list(ex.map(run, todo))
        for row, lk, dt in out:
            self.m.enrich_calls += 1
            self.m.enrich_s.append(round(dt, 2))
            self.m.cost_usd_computed += PRICE_SEARCH_STANDARD
            if not lk:
                continue
            c = row["cand"]
            c.registration_url = lk.registration_url or c.registration_url
            c.official_url = lk.official_url or c.official_url
            c.platform = c.platform or lk.platform
            c.date = c.date or lk.race_date
            c.distance_km = c.distance_km or lk.distance_km
            c.elevation_gain_m = c.elevation_gain_m or lk.elevation_gain_m
            c.registration_status = c.registration_status or lk.registration_status

    def prefilter(
        self, p: RunnerProfile, cands: list[Candidate]
    ) -> tuple[list[dict], list[dict]]:
        origin = geocode(p.origin_city, "FR")
        d0, d1 = parse_date(p.date_from), parse_date(p.date_to)
        kept, rejected = [], []
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda c: c.city and geocode(c.city, c.country), cands))
        for c in cands:
            row = {
                "cand": c,
                "why_rejected": None,
                "travel_h_est": None,
                "km_from_origin": None,
            }
            d = parse_date(c.date)
            if d and not (d0 <= d <= d1):
                row["why_rejected"] = f"date {d} hors fenetre"
            elif d and (d - TODAY).days < 7 * p.min_prep_weeks():
                row["why_rejected"] = "trop tot pour se preparer"
            elif c.distance_km and abs(c.distance_km - p.distance_km) > p.tolerance():
                row["why_rejected"] = f"distance {c.distance_km} km hors cible"
            if row["why_rejected"] is None and c.city and origin:
                g = geocode(c.city, c.country)
                if g:
                    km = haversine_km(origin[:2], g[:2])
                    row["km_from_origin"] = round(km)
                    row["travel_h_est"] = round(travel_hours(km, p.travel_mode), 2)
                    if p.foreign and g[2].upper() == "FR":
                        row["why_rejected"] = (
                            "en France alors que l'etranger est demande"
                        )
                    elif row["travel_h_est"] > p.max_travel_h:
                        row["why_rejected"] = (
                            f"trajet estime {row['travel_h_est']} h > {p.max_travel_h} h"
                        )
            (rejected if row["why_rejected"] else kept).append(row)
        kept.sort(
            key=lambda r: (r["cand"].registration_url is None, r["travel_h_est"] or 99)
        )
        return kept, rejected

    def _check(
        self, url: str, p: RunnerProfile, name: str
    ) -> tuple[PageCheck | None, str | None, float]:
        t = time.time()
        try:
            r = self.c.fetch(
                url=url,
                render_js=True,
                schema=PageCheck,
                instructions=(
                    f"Course visee : {name}, epreuve de {p.distance_label}. Lis uniquement ce que la page affiche. "
                    "open = bouton ou formulaire d'inscription actif pour cette epreuve ; full = complet / sold out ; "
                    "waitlist = liste d'attente ; not_yet_open = ouverture annoncee plus tard ; closed = cloturees ; "
                    "unknown si la page ne le dit pas. Ne devine pas les prix ni le D+."
                ),
            )
            data = r.data.model_dump() if isinstance(r.data, BaseModel) else r.data
            return (
                PageCheck(**(data or {"registration_status": "unknown"})),
                None,
                time.time() - t,
            )
        except Exception as e:  # noqa: BLE001
            return None, str(e).splitlines()[0][:160], time.time() - t

    def verify(self, p: RunnerProfile, rows: list[dict]) -> list[dict]:
        for r in rows:
            c = r["cand"]
            if c.registration_url and any(
                d in c.registration_url for d in EXCLUDED_DOMAINS
            ):
                c.registration_url = None
        todo = [
            r for r in rows if r["cand"].registration_url or r["cand"].official_url
        ][: self.max_verify]

        def run(row):
            c = row["cand"]
            url = c.registration_url or c.official_url
            chk, err, dt = self._check(url, p, c.name)
            return row, url, chk, err, dt

        with ThreadPoolExecutor(5) as ex:
            out = list(ex.map(run, todo))
        for row, url, chk, err, dt in out:
            self.m.fetch_calls += 1
            self.m.fetch_s.append(round(dt, 2))
            if err:
                self.m.fetch_errors += 1
            else:
                self.m.cost_usd_computed += PRICE_FETCH_JS_SCHEMA
            row["checked_url"] = url
            row["check"] = chk
            row["check_error"] = err
        return todo

    def score(self, p: RunnerProfile, row: dict) -> tuple[float, list[str]]:
        c: Candidate = row["cand"]
        chk: PageCheck | None = row.get("check")
        reasons, s = [], 0.0
        dist = (chk and chk.target_distance_km) or c.distance_km
        if dist:
            s += 3 - min(3, abs(dist - p.distance_km) / p.tolerance() * 3)
            reasons.append(f"{dist:g} km pour un objectif de {p.distance_km:g} km")
        d = parse_date((chk and chk.race_date) or c.date)
        if d:
            weeks = (d - TODAY).days // 7
            reasons.append(f"le {d.isoformat()}, soit {weeks} semaines de preparation")
            s += 1
        dplus = (chk and chk.elevation_gain_m) or c.elevation_gain_m
        if dplus is not None and dist:
            ratio = dplus / dist
            if p.terrain == "plat":
                s += 2 if ratio < 8 else (0 if ratio < 20 else -2)
                reasons.append(
                    f"D+ {dplus:g} m ({'plat' if ratio < 8 else 'vallonne'})"
                )
            elif p.terrain == "vallonne":
                s += 2 if 25 <= ratio <= 70 else 0.5
                reasons.append(f"D+ {dplus:g} m, soit {ratio:.0f} m/km")
        if row.get("travel_h_est") is not None:
            s += max(0, 2 - 2 * row["travel_h_est"] / p.max_travel_h)
            mode = "de vol" if p.travel_mode == "flight" else "de trajet"
            reasons.append(
                f"~{row['travel_h_est']:.1f} h {mode} estimees depuis {p.origin_city}"
            )
        n = (chk and chk.participants_max) or c.participants
        if n and p.race_size != "indifferent":
            big = n >= 3000
            if (p.race_size == "grande") == big:
                s += 1
                reasons.append(f"{'grande' if big else 'petite'} course ({n} coureurs)")
        if chk and chk.current_price_eur is not None:
            reasons.append(f"prix lu sur la page : {chk.current_price_eur:g} EUR")
        return round(s, 2), reasons

    def run(self, p: RunnerProfile) -> dict:
        t0 = time.time()
        cands = self.discover(p)
        t1 = time.time()
        kept, rejected = self.prefilter(p, cands)
        t2 = time.time()
        self.enrich(p, kept)
        t3 = time.time()
        checked = self.verify(p, kept)
        n_open = sum(
            1
            for r in checked
            if r.get("check") and r["check"].registration_status == "open"
        )
        if n_open < 3:
            # 2e tour : autre formulation, seulement sur les nouveaux candidats.
            known = {norm_name(r["cand"].name) for r in kept + rejected}
            extra = self._search(
                f"{p.distance_label} {p.zone_hint} entre le {p.date_from} et le {p.date_to} : courses dont les "
                "inscriptions 2027 sont deja ouvertes (bouton S'inscrire actif). Pour chaque course : nom, date "
                "YYYY-MM-DD, ville, pays, distance, D+, URL d'inscription, plateforme, statut, URL source."
            )
            extra = [c for c in extra if norm_name(c.name) not in known]
            k2, r2 = self.prefilter(p, extra)
            self.enrich(p, k2)
            checked += self.verify(p, k2)
            kept += k2
            rejected += r2
            self.m.second_round = True
        t4 = time.time()
        self.m.phases_s = {
            "decouverte": round(t1 - t0, 2),
            "filtre_geo": round(t2 - t1, 2),
            "url_inscription": round(t3 - t2, 2),
            "verification": round(t4 - t3, 2),
        }
        results = []
        for row in checked:
            c, chk = row["cand"], row.get("check")
            if row.get("check_error"):
                status = "a_verifier_par_H"
            else:
                status = chk.registration_status
            sc, reasons = self.score(p, row)
            results.append(
                {
                    "name": (chk and chk.race_name) or c.name,
                    "date": (chk and chk.race_date) or c.date,
                    "city": (chk and chk.city) or c.city,
                    "country": c.country,
                    "distance_km": (chk and chk.target_distance_km) or c.distance_km,
                    "elevation_gain_m": (chk and chk.elevation_gain_m)
                    or c.elevation_gain_m,
                    "platform": c.platform,
                    "registration_url": row["checked_url"],
                    "status_verified": status,
                    "status_evidence": chk and chk.status_evidence,
                    "status_from_search": c.registration_status,
                    "current_price_eur": chk and chk.current_price_eur,
                    "price_tier": chk and chk.price_tier,
                    "travel_h_est": row["travel_h_est"],
                    "score": sc,
                    "reason": "; ".join(reasons),
                    "sources": [u for u in {c.source_url, row["checked_url"]} if u],
                    "check_error": row.get("check_error"),
                }
            )
        d0, d1 = parse_date(p.date_from), parse_date(p.date_to)
        for r in results:
            d = parse_date(r["date"])
            url = r["registration_url"] or ""
            r["status_source"] = (
                "agregateur"
                if any(a in url for a in AGGREGATORS)
                else "page_inscription_ou_officielle"
            )
            if d and not (d0 <= d <= d1):
                r["status_verified"] = f"hors_fenetre ({d})"
            elif (
                r["distance_km"]
                and abs(r["distance_km"] - p.distance_km) > p.tolerance()
            ):
                r["status_verified"] = f"hors_distance ({r['distance_km']} km)"
            elif r["status_verified"] == "open" and r["status_source"] == "agregateur":
                r["status_verified"] = "open_selon_agregateur"
        results.sort(key=lambda r: -r["score"])
        open_ = [r for r in results if r["status_verified"] == "open"][:5]
        self.m.total_s = round(time.time() - t0, 2)
        return {
            "profile": p.model_dump(),
            "recommended_open": open_,
            "to_check_with_H": [
                r
                for r in results
                if r["status_verified"] in ("a_verifier_par_H", "unknown")
            ],
            "not_open": [
                r
                for r in results
                if r["status_verified"] not in ("open", "a_verifier_par_H", "unknown")
            ],
            "unverified_candidates": [
                {
                    "name": r["cand"].name,
                    "date": r["cand"].date,
                    "city": r["cand"].city,
                    "url": r["cand"].registration_url,
                }
                for r in kept
                if "check" not in r
            ],
            "rejected": [
                {
                    "name": r["cand"].name,
                    "date": r["cand"].date,
                    "city": r["cand"].city,
                    "why": r["why_rejected"],
                }
                for r in rejected
            ],
            "n_candidates": len(cands),
            "metrics": self.m.model_dump(),
            "linkup_log": self.log,
        }


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv
    from profiles import PROFILES

    load_dotenv()
    pid = sys.argv[1] if len(sys.argv) > 1 else PROFILES[0].id
    prof = next(x for x in PROFILES if x.id == pid)
    print(json.dumps(Finder().run(prof), ensure_ascii=False, indent=2, default=str))
