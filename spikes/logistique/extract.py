"""Extraction de la logistique d'une course via Linkup /search structuré (standard puis deep)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv
from linkup import LinkupClient
from linkup._errors import LinkupNoResultError
from models import OpenRaceList, RaceLogistics, Source

load_dotenv()

PRICE_USD = {("standard", "structured"): 0.006, ("deep", "structured"): 0.055}
CRITICAL_FIELDS = ("date", "start_time", "start_location", "registration_url")
BALANCE_URL = "https://api.linkup.so/v1/credits/balance"


@dataclass
class CallMetrics:
    depth: str
    latency_s: float
    list_price_usd: float
    balance_delta_usd: float | None
    missing_critical: list[str] = field(default_factory=list)


def balance() -> float | None:
    key = os.environ.get("LINKUP_API_KEY")
    if not key:
        return None
    r = httpx.get(BALANCE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=10)
    return r.json().get("balance") if r.status_code == 200 else None


def _query(race_name: str) -> str:
    return (
        f"Course à pied « {race_name} » édition 2027. Trouve le site officiel et le règlement officiel de l'édition 2027 "
        "et donne : nom officiel, date, distance de l'épreuve principale, heure de départ, lieu exact du départ, "
        "retrait des dossards (lieu, jours, horaires, retrait possible le jour même ?), accès au départ (transports, parking), "
        "documents exigés (PPS, certificat médical, licence), ravitaillements, temps limite, "
        "plateforme d'inscription (Njuko, Klikego, site organisateur...) avec l'URL directe d'inscription, prix, "
        "statut des inscriptions (ouvert, complet ou inconnu), URL du site officiel et du règlement. "
        "Ne devine rien : laisse vide ce que les pages officielles ne disent pas."
    )


def _missing(race: RaceLogistics) -> list[str]:
    return [f for f in CRITICAL_FIELDS if not getattr(race, f)]


def search_once(client: LinkupClient, race_name: str, depth: str) -> tuple[RaceLogistics, CallMetrics]:
    before = balance()
    t0 = time.perf_counter()
    resp = client.search(
        query=_query(race_name),
        depth=depth,
        output_type="structured",
        structured_output_schema=RaceLogistics,
        include_sources=True,
    )
    latency = time.perf_counter() - t0
    after = balance()
    race = RaceLogistics.model_validate(resp.data)
    linkup_sources = [Source(url=s.url, title=getattr(s, "name", None)) for s in resp.sources]
    known = {s.url for s in race.sources}
    race.sources += [s for s in linkup_sources if s.url not in known]
    delta = round(before - after, 4) if before is not None and after is not None else None
    return race, CallMetrics(depth, round(latency, 2), PRICE_USD[(depth, "structured")], delta, _missing(race))


def extract_race(race_name: str, client: LinkupClient | None = None, allow_deep: bool = True):
    """standard d'abord ; deep seulement si un champ critique manque."""
    client = client or LinkupClient()
    race, m = search_once(client, race_name, "standard")
    calls = [m]
    if allow_deep and m.missing_critical:
        t0 = time.perf_counter()
        try:
            deep_race, m2 = search_once(client, race_name, "deep")
        except LinkupNoResultError:
            calls.append(CallMetrics("deep", round(time.perf_counter() - t0, 2), 0.0, None, ["no_result (non facturé)"]))
            return race, calls
        calls.append(m2)
        if len(m2.missing_critical) <= len(m.missing_critical):
            race = deep_race
    return race, calls


def _merge(base: RaceLogistics, extra: dict) -> RaceLogistics:
    data = base.model_dump()
    for k, v in extra.items():
        if k == "sources" or v in (None, "", [], {}):
            continue
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k] = {kk: data[k].get(kk) or vv for kk, vv in v.items()}
        elif not data.get(k) or data.get(k) == "inconnu":
            data[k] = v
    return RaceLogistics.model_validate(data)


def extract_race_fetch(race_name: str, client: LinkupClient | None = None):
    """Variante rapide : standard, puis /fetch + schema sur le règlement (ou le site officiel) au lieu de deep."""
    client = client or LinkupClient()
    race, m = search_once(client, race_name, "standard")
    calls = [m]
    for url in [u for u in (race.regulation_url, race.official_url) if u][:1]:
        if not m.missing_critical:
            break
        before = balance()
        t0 = time.perf_counter()
        try:
            page = client.fetch(url=url, render_js=True, schema=RaceLogistics)
        except Exception as e:  # noqa: BLE001
            calls.append(CallMetrics("fetch", round(time.perf_counter() - t0, 2), 0.0, None, [f"erreur {type(e).__name__}"]))
            continue
        latency = time.perf_counter() - t0
        after = balance()
        if page.data:
            race = _merge(race, page.data)
            race.sources.append(Source(url=url, title="fetch"))
        delta = round(before - after, 4) if before is not None and after is not None else None
        calls.append(CallMetrics("fetch", round(latency, 2), 0.006, delta, _missing(race)))
    return race, calls


def find_open_races(client: LinkupClient | None = None) -> tuple[OpenRaceList, CallMetrics]:
    client = client or LinkupClient()
    before = balance()
    t0 = time.perf_counter()
    resp = client.search(
        query=(
            "Liste de courses à pied (10 km, semi-marathon, marathon) en France ou en Europe en 2027 "
            "dont les inscriptions sont ouvertes sur Njuko ou Klikego, avec nom, date, ville, distance, "
            "plateforme, URL d'inscription et prix."
        ),
        depth="standard",
        output_type="structured",
        structured_output_schema=OpenRaceList,
        include_domains=["njuko.com", "njuko.net", "klikego.com"],
    )
    latency = time.perf_counter() - t0
    after = balance()
    delta = round(before - after, 4) if before is not None and after is not None else None
    return OpenRaceList.model_validate(resp), CallMetrics("standard", round(latency, 2), 0.006, delta)


if __name__ == "__main__":
    import sys

    r, calls = extract_race(" ".join(sys.argv[1:]) or "Wizz Air Milano Marathon 2027")
    print(json.dumps(r.model_dump(), ensure_ascii=False, indent=2))
    print([c.__dict__ for c in calls])
