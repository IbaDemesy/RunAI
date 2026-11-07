"""Client API Strava officiel (OAuth) -> meilleurs efforts récents -> JSON pour l'estimateur.

ATTENTION CGU : la Strava API Policy (en vigueur le 1er juin 2026, §5.3) interdit d'utiliser les données
de l'API, ou toute donnée dérivée, « in connection with the ... operation of any AI Application », y
compris l'« ingestion into a context window ». RunAI est une application IA : ce client sert à
prouver le format, en mode fixture. Ne pas brancher le mode live sur RunAI (voir README).

    python strava_client.py                      # fixture (fixtures/strava_*.json)
    python strava_client.py --auth-url           # URL OAuth (STRAVA_CLIENT_ID, STRAVA_REDIRECT_URI)
    STRAVA_ACCESS_TOKEN=... python strava_client.py --live --jours 90
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

API = "https://www.strava.com/api/v3"
ICI = Path(__file__).parent
SPORTS_COURSE = {"Run", "TrailRun", "VirtualRun"}
EFFORTS_UTILES = {"1K", "1 mile", "5K", "10K", "15K", "10 mile", "20K", "Half-Marathon", "30K", "Marathon"}


def url_autorisation(client_id: str, redirect_uri: str, scope: str = "activity:read_all") -> str:
    return "https://www.strava.com/oauth/authorize?" + urlencode(
        {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
         "approval_prompt": "auto", "scope": scope})


def echanger_code(client_id: str, client_secret: str, code: str) -> dict:
    r = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "grant_type": "authorization_code"}, timeout=30)
    r.raise_for_status()
    return r.json()


def rafraichir(client_id: str, client_secret: str, refresh_token: str) -> dict:
    r = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token,
        "grant_type": "refresh_token"}, timeout=30)
    r.raise_for_status()
    return r.json()


def lire_live(token: str, jours: int, max_details: int) -> tuple[list[dict], list[dict]]:
    """1 + ceil(n/100) + min(n, max_details) requêtes (limite par défaut : 100 lectures / 15 min)."""
    h = {"Authorization": f"Bearer {token}"}
    apres = int(time.time()) - jours * 86400
    resumes, page = [], 1
    with httpx.Client(timeout=30, headers=h) as c:
        while True:
            r = c.get(f"{API}/athlete/activities", params={"after": apres, "per_page": 100, "page": page})
            r.raise_for_status()
            lot = r.json()
            resumes += lot
            if len(lot) < 100:
                break
            page += 1
        courses = [a for a in resumes if a.get("sport_type", a.get("type")) in SPORTS_COURSE]
        details = []
        for a in sorted(courses, key=lambda a: a["start_date"], reverse=True)[:max_details]:
            r = c.get(f"{API}/activities/{a['id']}")
            r.raise_for_status()
            details.append(r.json())
    return resumes, details


def lire_fixture() -> tuple[list[dict], list[dict]]:
    return (json.loads((ICI / "fixtures/strava_activities.json").read_text(encoding="utf-8")),
            json.loads((ICI / "fixtures/strava_details.json").read_text(encoding="utf-8")))


def profil_coureur(resumes: list[dict], details: list[dict], jours: int, maintenant: datetime | None = None,
                   source: str = "strava_api") -> dict:
    maintenant = maintenant or datetime.now(UTC)
    debut = maintenant - timedelta(days=jours)
    courses = [a for a in resumes if a.get("sport_type", a.get("type")) in SPORTS_COURSE
               and datetime.fromisoformat(a["start_date"]) >= debut]
    semaines = max(jours / 7, 1)
    meilleurs: dict[str, dict] = {}
    for act in details:
        for e in act.get("best_efforts", []):
            if e["name"] not in EFFORTS_UTILES:
                continue
            if e["name"] not in meilleurs or e["elapsed_time"] < meilleurs[e["name"]]["temps_s"]:
                meilleurs[e["name"]] = {"nom": e["name"], "distance_m": e["distance"], "temps_s": e["elapsed_time"],
                                        "date": e["start_date_local"][:10], "activity_id": act["id"]}
    return {
        "source": source,
        "fenetre_jours": jours,
        "nb_sorties": len(courses),
        "sorties_par_semaine": round(len(courses) / semaines, 1),
        "km_par_semaine": round(sum(a["distance"] for a in courses) / 1000 / semaines, 1),
        "plus_longue_sortie_km": round(max((a["distance"] for a in courses), default=0) / 1000, 1),
        "d_plus_par_semaine_m": round(sum(a.get("total_elevation_gain", 0) for a in courses) / semaines),
        "meilleurs_efforts": sorted(meilleurs.values(), key=lambda e: e["distance_m"]),
        "activites_detaillees": len(details),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    p.add_argument("--auth-url", action="store_true")
    p.add_argument("--jours", type=int, default=90)
    p.add_argument("--max-details", type=int, default=20)
    a = p.parse_args()
    if a.auth_url:
        print(url_autorisation(os.environ["STRAVA_CLIENT_ID"], os.environ["STRAVA_REDIRECT_URI"]))
        return
    if a.live:
        resumes, details = lire_live(os.environ["STRAVA_ACCESS_TOKEN"], a.jours, a.max_details)
        profil = profil_coureur(resumes, details, a.jours)
    else:
        resumes, details = lire_fixture()
        profil = profil_coureur(resumes, details, a.jours, datetime(2026, 11, 7, tzinfo=UTC), "fixture")
    from niveau import estimer

    print(json.dumps({"profil": profil, "estimation": estimer(profil)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
