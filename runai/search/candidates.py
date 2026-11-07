"""Recherche générique de courses, sans valeurs de cadrage implicites."""

import asyncio
import hashlib
import json
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, Field, HttpUrl, ValidationError

from runai.coach.finder import AGGREGATORS, EXCLUDED_DOMAINS, norm_name, parse_date
from runai.contracts.common import Limitation, Provenance, ProvenanceKind
from runai.contracts.framing import RaceCandidate, Slot, SlotName, matching_distance
from runai.models import Source
from runai.search.checks import host_of, is_aggregator, on_domain
from runai.search.linkup_search import SearchClient, default_client


class CandidateSearchError(RuntimeError):
    """Le fournisseur n'a pas pu effectuer la recherche."""


class CandidateSearchResult(BaseModel):
    candidates: list[RaceCandidate] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)


class _Candidate(BaseModel):
    name: str
    city: str = ""
    country: str = ""
    race_date: str | None = None
    distances_km: list[Annotated[float, Field(gt=0, allow_inf_nan=False)]] = Field(default_factory=list)
    official_url: HttpUrl | None = None
    registration_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    sources: list[Source] = Field(default_factory=list)


class _Candidates(BaseModel):
    candidates: list[_Candidate]


SEARCH_SLOTS = (
    SlotName.city, SlotName.race, SlotName.edition, SlotName.race_date,
    SlotName.date_window, SlotName.distance_km, SlotName.preferences,
)


def build_candidate_prompt(slots: dict[SlotName, Slot]) -> str:
    known = {name.value: slots[name].value for name in SEARCH_SLOTS
             if name in slots and slots[name].is_known and slots[name].value is not None}
    return (
        "Find running race candidates matching only these known constraints: "
        + json.dumps(known, ensure_ascii=False, default=str)
        + ". Return distinct events with name, city, country, race_date (ISO if published), "
        "distances_km, official_url, registration_url, source_url and relevant sources. "
        "Use sourced facts; leave unpublished details empty. Do not infer unspecified constraints."
    )


def _blocked(url: HttpUrl) -> bool:
    host = host_of(url)
    return is_aggregator(host) or any(on_domain(host, d) for d in [*AGGREGATORS, *EXCLUDED_DOMAINS])


def _sources(items: list[Any]) -> list[Source]:
    out: dict[str, Source] = {}
    for item in items:
        if isinstance(item, Source):
            source = item
        else:
            if isinstance(item, str):
                item = {"url": item}
            elif not isinstance(item, dict):
                item = {"url": getattr(item, "url", None), "title": getattr(item, "name", None)}
            try:
                source = Source.model_validate(item)
            except ValidationError:
                continue
        out[str(source.url)] = source
    return list(out.values())


class LinkupCandidateSearch:
    def __init__(self, client: SearchClient | None = None, *, today: date | None = None):
        self._client = client
        self.today = today

    async def find_candidates(self, slots: dict[SlotName, Slot]) -> list[RaceCandidate]:
        return (await self.search(slots)).candidates

    async def search(self, slots: dict[SlotName, Slot]) -> CandidateSearchResult:
        if not any(name in slots and slots[name].is_known and slots[name].value
                   for name in (SlotName.city, SlotName.race)):
            return self._result([])
        try:
            response = await asyncio.to_thread(self._search, build_candidate_prompt(slots))
            data = getattr(response, "data", response)
            if isinstance(data, BaseModel):
                data = data.model_dump(mode="json")
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
                raise TypeError("réponse candidats invalide")
        except Exception as exc:
            raise CandidateSearchError("Recherche Linkup impossible") from exc
        response_sources = _sources(
            (response.get("sources", []) if isinstance(response, dict) else getattr(response, "sources", [])) or []
        )
        merged: dict[str, RaceCandidate] = {}
        for raw in data["candidates"]:
            if not isinstance(raw, dict):
                continue
            raw = dict(raw)
            raw["sources"] = _sources(raw.get("sources") or [])
            try:
                row = _Candidate.model_validate(raw)
            except ValidationError:
                continue
            when = parse_date(row.race_date)
            if when and when < (self.today or date.today()):
                continue
            target = slots.get(SlotName.distance_km)
            if (
                target
                and target.is_known
                and target.value is not None
                and row.distances_km
                and matching_distance(row.distances_km, float(target.value)) is None
            ):
                continue
            urls = {str(s.url) for s in row.sources}
            urls.update(str(u) for u in (row.source_url, row.official_url, row.registration_url) if u)
            sources = _sources([
                *([str(row.source_url)] if row.source_url else []), *row.sources,
                *(s for s in response_sources if str(s.url) in urls),
            ])
            if not sources:
                continue
            limits = []
            if not when:
                limits.append(Limitation(code="race_date_unknown", message="Date de course à confirmer."))
            official = row.official_url if row.official_url and not _blocked(row.official_url) else None
            registration = row.registration_url
            if registration and _blocked(registration):
                registration = None
                limits.append(Limitation(code="registration_url_unverified", step="registration",
                                         message="Lien d'inscription non officiel : vérification humaine requise.",
                                         manual_url=official))
            key = json.dumps([norm_name(row.name), norm_name(row.city), norm_name(row.country),
                              when.isoformat() if when else "unknown"])
            candidate = RaceCandidate(
                id="race-" + hashlib.sha256(key.encode()).hexdigest()[:20], name=row.name,
                city=row.city, country=row.country, race_date=when, distances_km=row.distances_km,
                official_url=official, registration_url=registration, sources=sources,
                provenance=Provenance(kind=ProvenanceKind.linkup, url=sources[0].url), limitations=limits,
            )
            if key in merged:
                old = merged[key]
                candidate.sources = _sources([*old.sources, *candidate.sources])
                candidate.distances_km = sorted(set(old.distances_km + candidate.distances_km))
                candidate.official_url = old.official_url or candidate.official_url
                candidate.registration_url = old.registration_url or candidate.registration_url
                candidate.limitations = list({x.model_dump_json(): x for x in [*old.limitations, *limits]}.values())
            merged[key] = candidate
        return self._result(list(merged.values()))

    def _search(self, prompt: str) -> Any:
        if self._client is None:
            self._client = default_client()
        return self._client.search(query=prompt, depth="standard", output_type="structured",
                                   structured_output_schema=_Candidates, include_sources=True,
                                   exclude_domains=EXCLUDED_DOMAINS)

    @staticmethod
    def _result(candidates: list[RaceCandidate]) -> CandidateSearchResult:
        return CandidateSearchResult(candidates=candidates, limitations=[] if candidates else [
            Limitation(code="no_candidate_found", message="Aucune course candidate sourcée trouvée.")
        ])
