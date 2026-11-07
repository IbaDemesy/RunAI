"""Plan B « course complète » : statut, liste d'attente / revente officielle, 3 alternatives vérifiées.

Usage : python plan_b.py "EDP Meia Maratona de Lisboa 2027" --registration-url URL --out results/lisbon.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import httpx
import linkup
from linkup import LinkupClient

sys.path.insert(0, str(Path(__file__).parent))
from models import (
    Alternative,
    Metrics,
    OfficialOption,
    PlanB,
    RegStatus,
    Rejected,
    SourcedStatus,
    TargetRace,
)
from travel import MAX_MINUTES, lookup, norm

# Prix publics Linkup (docs.linkup.so/pages/documentation/platform/pricing.md, nov. 2026)
PRICE = {"no_result": 0.0, "search_standard_structured": 0.006, "search_deep_structured": 0.055, "fetch_js_schema": 0.006}
WINDOW_DAYS = 21
VERIFY_TOP = 8
STATUSES = ["open", "sold_out", "closed", "not_yet_open", "waitlist", "unknown"]


class Linkup:
    """Client Linkup asynchrone qui compte appels, latences et coût."""

    def __init__(self) -> None:
        self.client = LinkupClient()
        self.calls: Counter[str] = Counter()
        self.sem = asyncio.Semaphore(6)  # limite Linkup : 10 req/s par organisation

    async def search(self, query: str, schema: dict, depth: str = "standard") -> tuple[dict, list[str]]:
        try:
            async with self.sem:
                r = await self.client.async_search(
                    query=query, depth=depth, output_type="structured",
                    structured_output_schema=json.dumps(schema), include_sources=True,
                )
        except linkup.LinkupNoResultError:  # non facturé par Linkup
            self.calls["no_result"] += 1
            return {}, []
        self.calls[f"search_{depth}_structured"] += 1
        data = r.data if hasattr(r, "data") else r
        sources = [s.url for s in getattr(r, "sources", []) or [] if getattr(s, "url", None)]
        return data or {}, sources

    async def fetch(self, url: str, schema: dict, instructions: str) -> dict:
        async with self.sem:
            r = await self.client.async_fetch(url=url, render_js=True, schema=json.dumps(schema), instructions=instructions)
        self.calls["fetch_js_schema"] += 1
        return r.data or {}

    def cost(self) -> float:
        return round(sum(PRICE[k] * n for k, n in self.calls.items()), 4)


def balance() -> float | None:
    key = os.environ.get("LINKUP_API_KEY")
    if not key:
        return None
    try:
        r = httpx.get("https://api.linkup.so/v1/credits/balance", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        return float(r.json()["balance"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None
    except ValueError:
        return None


def status(s: str | None) -> RegStatus:
    try:
        return RegStatus(s)
    except ValueError:
        return RegStatus.unknown


# ---------- 1. Statut de la course visée ----------

TARGET_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD of this edition"},
    "distance_km": {"type": "number"}, "city": {"type": "string"}, "country": {"type": "string"},
    "official_url": {"type": "string"}, "registration_url": {"type": "string"},
    "registration_status": {"type": "string", "enum": STATUSES},
    "status_evidence": {"type": "string", "description": "short quote from the source"},
    "status_source_url": {"type": "string"},
}}

PAGE_SCHEMA = {"type": "object", "properties": {
    "races": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "distance_km": {"type": "number"},
        "status": {"type": "string", "enum": STATUSES},
        "evidence": {"type": "string", "description": "exact quote from the page"},
        "general_entry_open": {"type": "boolean", "description": "a normal runner can buy a bib now (not charity/ballot/password only)"},
        "price_eur": {"type": "number"}, "date": {"type": "string", "description": "YYYY-MM-DD"}}}},
    "waitlist_url": {"type": "string"}, "resale_url": {"type": "string"},
}}
PAGE_INSTR = ("List every race offered on this page with its registration status. 'open' only if the page lets you "
              "register now (button/form/price shown and no sold-out notice). Quote any banner saying sold out / complet / "
              "esgotada / agotado / agotados / ausverkauft / uitverkocht, or registration closed. If only charity, ballot, "
              "corporate or password places remain ('missed out on general entry? charity place'), status is sold_out. "
              "Report any waiting list or official resale link.")

POLICY_SCHEMA = {"type": "object", "properties": {
    "waitlist_exists": {"type": "boolean"}, "waitlist_url": {"type": "string"}, "waitlist_how": {"type": "string"},
    "official_resale_exists": {"type": "boolean"}, "official_resale_url": {"type": "string"},
    "official_resale_how": {"type": "string"},
    "transfer_allowed": {"type": "boolean"}, "transfer_rule": {"type": "string"},
    "policy_source_url": {"type": "string", "description": "official organiser page (FAQ/rules) stating the policy"},
}}


NEGATIVE = {RegStatus.sold_out, RegStatus.closed, RegStatus.waitlist}


def page_status(race: dict, url: str) -> SourcedStatus:
    st = status(race.get("status"))
    if st == RegStatus.open and race.get("general_entry_open") is not True:
        st = RegStatus.sold_out if race.get("general_entry_open") is False else RegStatus.unknown
    return SourcedStatus(status=st, evidence=race.get("evidence", ""), source_url=url, checked_by="linkup_fetch")


def fuse(details: list[SourcedStatus]) -> SourcedStatus:
    """Prudent : une seule source « complet/fermé » suffit ; « ouvert » exige la page d'inscription lue."""
    neg = [d for d in details if d.status in NEGATIVE]
    if neg:
        return neg[-1]
    page = [d for d in details if d.checked_by == "linkup_fetch" and d.status != RegStatus.unknown]
    return page[-1] if page else details[0]


def pick_race(races: list[dict], distance: float | None) -> dict | None:
    if not races:
        return None
    if distance:
        close = [r for r in races if r.get("distance_km") and abs(r["distance_km"] - distance) < 1.0]
        if close:
            return close[0]
    return races[0]


async def check_target(lk: Linkup, query: str, reg_url: str | None, today: date) -> TargetRace:
    info, src = await lk.search(
        f"{query}: official race page and official registration page, exact date, distance, city. "
        "Is registration for this edition open, sold out, closed or not yet open? Quote the source.", TARGET_SCHEMA)
    t = TargetRace(
        query=query, name=info.get("name"), date=parse_date(info.get("date")), distance_km=info.get("distance_km"),
        city=info.get("city"), country=info.get("country"), official_url=info.get("official_url"),
        registration_url=reg_url or info.get("registration_url"),
        status=SourcedStatus(status=status(info.get("registration_status")), evidence=info.get("status_evidence", ""),
                             source_url=info.get("status_source_url") or (src[0] if src else None), checked_by="linkup_search"),
    )
    t.status_details.append(t.status)
    if t.registration_url:
        page = await lk.fetch(t.registration_url, PAGE_SCHEMA, PAGE_INSTR)
        race = pick_race(page.get("races") or [], t.distance_km)
        if race:
            t.status_details.append(page_status(race, t.registration_url))
    t.status = fuse(t.status_details)
    if t.date and t.date < today:
        t.status = SourcedStatus(status=RegStatus.past, evidence=f"date {t.date} < {today}", checked_by="linkup_search",
                                 source_url=t.official_url)
    return t


async def official_options(lk: Linkup, query: str) -> list[OfficialOption]:
    p, src = await lk.search(
        f"{query}: according to the organiser's official FAQ or rules, is there an official waiting list, an official "
        "bib resale/exchange platform, or can a registration be transferred to another runner? Give official URLs.",
        POLICY_SCHEMA)
    source = p.get("policy_source_url") or (src[0] if src else None)
    return [
        OfficialOption(kind="waitlist", available=p.get("waitlist_exists"), url=p.get("waitlist_url") or None,
                       how=p.get("waitlist_how", ""), source_url=source),
        OfficialOption(kind="resale", available=p.get("official_resale_exists"), url=p.get("official_resale_url") or None,
                       how=p.get("official_resale_how", ""), source_url=source),
        OfficialOption(kind="transfer", available=p.get("transfer_allowed"), how=p.get("transfer_rule", ""), source_url=source),
    ]


# ---------- 2. Courses alternatives ----------

REGIONS = {
    "fr_be_lu": "France, Belgium and Luxembourg (Paris, Lille, Lyon, Rennes, Strasbourg, Bordeaux, Nantes, Marseille, Nice, Toulouse, Brussels)",
    "es": "Spain (Barcelona, Valencia, Bilbao, San Sebastián, Irún, Palma, Madrid)",
    "it_ch": "Italy and Switzerland (Milan, Turin, Venice, Bologna, Florence, Pisa, Geneva, Zurich, Lausanne, Basel)",
    "uk_ie": "the United Kingdom and Ireland (London, Bath, Manchester, Liverpool, Edinburgh, Dublin, Cork)",
    "nl_de": "the Netherlands and Germany (Amsterdam, The Hague, Rotterdam, Eindhoven, Frankfurt, Cologne, Munich, Berlin, Hamburg)",
    "dk_cz": "Denmark and the Czech Republic (Copenhagen, Prague)",
}
LIST_SCHEMA = {"type": "object", "properties": {"races": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "city": {"type": "string"}, "country": {"type": "string"},
    "date": {"type": "string", "description": "YYYY-MM-DD of the edition in the requested window"},
    "distance_km": {"type": "number"}, "official_url": {"type": "string"}}}}}}

CAND_SCHEMA = {"type": "object", "properties": {
    "date": {"type": "string", "description": "YYYY-MM-DD"}, "distance_km": {"type": "number"},
    "registration_url": {"type": "string", "description": "page where a runner registers (official or official ticketing platform)"},
    "registration_platform": {"type": "string", "description": "e.g. Njuko, Klikego, Active, Ahotu, own website"},
    "registration_status": {"type": "string", "enum": STATUSES},
    "status_evidence": {"type": "string"}, "price_eur": {"type": "number"},
}}


def label(km: float) -> str:
    if abs(km - 21.1) < 1:
        return "half marathon (21.1 km)"
    if abs(km - 42.2) < 1:
        return "marathon (42.195 km)"
    return f"{km:g} km road race"


async def discover(lk: Linkup, km: float, start: date, end: date) -> list[dict]:
    mid = start + (end - start) / 2
    windows = [(start, mid), (mid + timedelta(days=1), end)]  # 2 sous-fenêtres : Linkup liste mieux sur 3 semaines

    async def one(region: str, a: date, b: date) -> list[dict]:
        d, _ = await lk.search(
            f"List every {label(km)} taking place between {a:%d %B %Y} and {b:%d %B %Y} in {region}. "
            "For each: name, city, country, exact date of that edition, official website.", LIST_SCHEMA)
        return d.get("races") or []

    res = await asyncio.gather(*(one(r, a, b) for r in REGIONS.values() for a, b in windows), return_exceptions=True)
    return [r for x in res if isinstance(x, list) for r in x]


def same_race(c: dict, t: TargetRace) -> bool:
    return bool(t.city and c.get("city") and norm(t.city) in norm(c["city"]) and parse_date(c.get("date")) == t.date)


async def verify(lk: Linkup, c: dict, km: float) -> tuple[dict, list[SourcedStatus], float | None]:
    info, src = await lk.search(
        f"{c['name']} {c['date'][:4]} ({c.get('city')}, {c['date']}, {label(km)}): official registration page, "
        "registration platform, is registration currently open, price.", CAND_SCHEMA)
    details = [SourcedStatus(status=status(info.get("registration_status")), evidence=info.get("status_evidence", ""),
                             source_url=src[0] if src else c.get("official_url"), checked_by="linkup_search")]
    price = info.get("price_eur")
    url = info.get("registration_url") or c.get("official_url")
    if url:
        try:
            page = await lk.fetch(url, PAGE_SCHEMA, PAGE_INSTR)
            race = pick_race(page.get("races") or [], km)
            if race:
                details.append(page_status(race, url))
                price = race.get("price_eur") or price
        except (linkup.LinkupFailedFetchError, linkup.LinkupFetchTargetUnreachableError,
                linkup.LinkupFetchTargetNotFoundError, linkup.LinkupTimeoutError, linkup.LinkupNoResultError,
                linkup.LinkupFetchUnsupportedContentTypeError, linkup.LinkupFetchResponseTooLargeError,
                linkup.LinkupUnknownError, httpx.HTTPError) as e:  # page illisible : on garde la recherche
            details.append(SourcedStatus(status=RegStatus.unknown, evidence=f"fetch error: {e}"[:200],
                                         source_url=url, checked_by="linkup_fetch"))
    info["registration_url"] = url
    return info, details, price


def reject_reason(c: dict, d: date | None, t: TargetRace, km: float, start: date, end: date) -> str | None:
    if not d:
        return "date inconnue"
    if not start <= d <= end:
        return f"hors fenêtre {start}..{end}"
    if c.get("distance_km") and abs(c["distance_km"] - km) > 1:
        return f"distance {c['distance_km']} km"
    tr = lookup(c.get("city"))
    if tr is None:
        return "durée depuis Paris inconnue (ville hors table)"
    if tr.minutes > MAX_MINUTES:
        return f"{tr.mode} {tr.minutes} min > {MAX_MINUTES} min"
    if same_race(c, t):
        return "course visée"
    return None


async def alternatives(lk: Linkup, t: TargetRace, km: float, today: date, rejected: list[Rejected]):
    center = t.date if t.date and t.date >= today else None
    if center is None:  # course passée : même période l'année suivante
        base = t.date or today
        center = base.replace(year=base.year + 1) if t.date else today + timedelta(days=60)
    start, end = max(today, center - timedelta(days=WINDOW_DAYS)), center + timedelta(days=WINDOW_DAYS)
    raw = await discover(lk, km, start, end)

    seen, cands = set(), []
    for c in raw:
        d = parse_date(c.get("date"))
        why = reject_reason(c, d, t, km, start, end)
        if why:
            rejected.append(Rejected(name=c.get("name") or "?", city=c.get("city"), date=c.get("date"), reason=why))
            continue
        key = (norm(c.get("city", "")), d)
        if key in seen:
            continue
        seen.add(key)
        c["date"], c["_d"], c["_travel"] = d.isoformat(), d, lookup(c.get("city"))
        cands.append(c)
    cands.sort(key=lambda c: (abs((c["_d"] - center).days), c["_travel"].minutes))
    top = cands[:VERIFY_TOP]
    for c in cands[VERIFY_TOP:]:
        rejected.append(Rejected(name=c["name"], city=c.get("city"), date=c["date"], reason="non vérifiée (hors top)"))

    checked = await asyncio.gather(*(verify(lk, c, km) for c in top), return_exceptions=True)
    alts = []
    for c, res in zip(top, checked):
        if isinstance(res, Exception):
            rejected.append(Rejected(name=c["name"], city=c.get("city"), date=c["date"], reason=f"erreur: {res}"[:200]))
            continue
        info, details, price = res
        final = fuse(details)
        ok = final.status == RegStatus.open and final.checked_by == "linkup_fetch"
        alt = Alternative(
            name=c["name"], city=c.get("city") or "", country=c.get("country"), date=c["_d"],
            days_from_target=(c["_d"] - center).days, distance_km=c.get("distance_km") or info.get("distance_km"),
            registration_url=info.get("registration_url"), platform=info.get("registration_platform"),
            price_eur=price, status=final, status_details=details, travel=c["_travel"], verified_open=ok,
        )
        if ok:
            alts.append(alt)
        else:
            rejected.append(Rejected(name=alt.name, city=alt.city, date=c["date"],
                                     reason=f"statut {final.status.value} ({final.checked_by})"))
    return alts[:3], (start, end)


async def run(query: str, reg_url: str | None, km_hint: float | None, today: date) -> PlanB:
    lk, stages, rejected = Linkup(), {}, []
    b0, t0 = balance(), time.perf_counter()

    async def timed(name, coro):
        s = time.perf_counter()
        out = await coro
        stages[name] = round(time.perf_counter() - s, 2)
        return out

    target, options = await asyncio.gather(timed("statut", check_target(lk, query, reg_url, today)),
                                           timed("options_officielles", official_options(lk, query)))
    km = km_hint or target.distance_km or 21.1
    unavailable = target.status.status in {RegStatus.sold_out, RegStatus.closed, RegStatus.past, RegStatus.waitlist}
    alts, window = await timed("alternatives", alternatives(lk, target, km, today, rejected))
    total = round(time.perf_counter() - t0, 2)
    b1 = balance()
    return PlanB(
        target=target, unavailable=unavailable, official_options=options, alternatives=alts, window=window,
        rejected=rejected,
        metrics=Metrics(total_s=total, stages_s=stages, linkup_calls=dict(lk.calls), linkup_cost_usd_computed=lk.cost(),
                        linkup_balance_delta_usd=round(b0 - b1, 4) if b0 is not None and b1 is not None else None),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--registration-url")
    ap.add_argument("--km", type=float)
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--out")
    a = ap.parse_args()
    if not os.environ.get("LINKUP_API_KEY"):
        sys.exit("LINKUP_API_KEY manquante")
    plan = asyncio.run(run(a.query, a.registration_url, a.km, date.fromisoformat(a.today)))
    out = plan.model_dump_json(indent=2)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
    t = plan.target
    print(f"{t.name} | {t.date} | statut={t.status.status.value} ({t.status.checked_by}) : {t.status.evidence[:160]}")
    for o in plan.official_options:
        print(f"  {o.kind}: {o.available} {o.url or ''} [{o.source_url}] {o.how[:120]}")
    for x in plan.alternatives:
        print(f"  ALT {x.date} ({x.days_from_target:+d} j) {x.name} - {x.city} | {x.travel.mode} {x.travel.minutes} min | "
              f"{x.platform} | {x.price_eur} EUR | {x.registration_url}")
    print(f"  rejetées: {len(plan.rejected)} | metrics: {plan.metrics.model_dump()}")


if __name__ == "__main__":
    main()
