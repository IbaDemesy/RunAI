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


class _NextEdition(BaseModel):
    race_date: str | None = None
    source_url: HttpUrl | None = None


SEARCH_SLOTS = (
    SlotName.city, SlotName.race, SlotName.edition, SlotName.race_date,
    SlotName.date_window, SlotName.distance_km, SlotName.preferences,
)


def build_candidate_prompt(
    slots: dict[SlotName, Slot],
    today: date | None = None,
    *,
    relaxed: bool = False,
) -> str:
    known = {name.value: slots[name].value for name in SEARCH_SLOTS
             if name in slots and slots[name].is_known and slots[name].value is not None}
    prompt = (
        "Find running race candidates matching only these known constraints: "
        + json.dumps(known, ensure_ascii=False, default=str)
        + ". Return distinct events with name, city, country, race_date (ISO if published), "
        "distances_km, official_url, registration_url, source_url and relevant sources. "
        "Use sourced facts; leave unpublished details empty. Do not infer unspecified constraints. "
        f"Prefer the next edition on or after {(today or date.today()).isoformat()}; "
        "if its date is not published yet, return the latest edition with its date."
    )
    if relaxed:
        prompt += (
            " No exact match was found; also include races in nearby cities (about 50 km) "
            "and other distances or dates."
        )
    return prompt


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
        today = self.today or date.today()
        try:
            response = await asyncio.to_thread(
                self._search, build_candidate_prompt(slots, today=today)
            )
            candidates = self._parse_candidates(response, slots, today=today)
        except Exception as exc:
            raise CandidateSearchError("Recherche Linkup impossible") from exc
        if candidates:
            candidates = await self._lookup_next_editions(
                self._rank_candidates(candidates), today
            )
            return self._result(self._rank_candidates(candidates))

        fallback_slots = self._relaxed_slots(slots)
        if fallback_slots is None:
            return self._result([])
        try:
            response = await asyncio.to_thread(
                self._search,
                build_candidate_prompt(fallback_slots, today=today, relaxed=True),
            )
            candidates = self._parse_candidates(
                response, fallback_slots, today=today, close_match=True
            )
        except Exception as exc:
            raise CandidateSearchError("Recherche Linkup impossible") from exc
        candidates = await self._lookup_next_editions(
            self._rank_candidates(candidates), today
        )
        return self._result(self._rank_candidates(candidates))

    @staticmethod
    def _relaxed_slots(
        slots: dict[SlotName, Slot],
    ) -> dict[SlotName, Slot] | None:
        known_to_relax = (
            SlotName.distance_km,
            SlotName.race_date,
            SlotName.date_window,
            SlotName.edition,
            SlotName.race,
        )
        if not any(
            name in slots and slots[name].is_known for name in known_to_relax
        ):
            return None
        relaxed = dict(slots)
        for name in known_to_relax[:-1]:
            relaxed.pop(name, None)
        city = relaxed.get(SlotName.city)
        if city and city.is_known and city.value:
            relaxed.pop(SlotName.race, None)
        return relaxed

    def _parse_candidates(
        self,
        response: Any,
        slots: dict[SlotName, Slot],
        *,
        today: date,
        close_match: bool = False,
    ) -> list[RaceCandidate]:
        data = getattr(response, "data", response)
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
            raise TypeError("réponse candidats invalide")
        response_sources = _sources(
            (response.get("sources", []) if isinstance(response, dict) else getattr(response, "sources", [])) or []
        )
        rows: list[tuple[_Candidate, date | None]] = []
        for raw in data["candidates"]:
            if not isinstance(raw, dict):
                continue
            raw = dict(raw)
            raw["sources"] = _sources(raw.get("sources") or [])
            try:
                row = _Candidate.model_validate(raw)
            except ValidationError:
                continue
            rows.append((row, parse_date(row.race_date)))
        future_events = {
            (norm_name(row.name), norm_name(row.city), norm_name(row.country))
            for row, when in rows
            if when and when >= today
        }
        merged: dict[str, RaceCandidate] = {}
        for row, when in rows:
            event = (norm_name(row.name), norm_name(row.city), norm_name(row.country))
            past_date = when if when and when < today else None
            if past_date:
                if event in future_events:
                    continue
                when = None
            target = slots.get(SlotName.distance_km)
            if (
                not close_match
                and
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
            if past_date:
                limits.append(Limitation(
                    code="next_edition_unconfirmed",
                    message=(
                        f"Dernière édition connue le {past_date:%d/%m/%Y} ; "
                        "date de la prochaine édition à confirmer."
                    ),
                ))
            elif not when:
                limits.append(Limitation(code="race_date_unknown", message="Date de course à confirmer."))
            if close_match:
                limits.append(Limitation(
                    code="close_match",
                    message="Proche de votre demande, pas exactement ce que vous avez demandé.",
                ))
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
                if any(
                    limitation.code == "next_edition_unconfirmed"
                    for limitation in candidate.limitations
                ):
                    candidate.limitations = [
                        limitation
                        for limitation in candidate.limitations
                        if limitation.code != "race_date_unknown"
                    ]
            merged[key] = candidate
        return list(merged.values())

    @staticmethod
    def _rank_candidates(candidates: list[RaceCandidate]) -> list[RaceCandidate]:
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                any(limitation.code == "close_match" for limitation in candidate.limitations),
                candidate.race_date is None,
                candidate.race_date or date.max,
            ),
        )
        return ranked[:5]

    async def _lookup_next_editions(
        self, candidates: list[RaceCandidate], today: date
    ) -> list[RaceCandidate]:
        pending = [
            candidate
            for candidate in candidates
            if any(
                limitation.code == "next_edition_unconfirmed"
                for limitation in candidate.limitations
            )
        ][:3]
        results = await asyncio.gather(
            *(
                asyncio.to_thread(self._search_next_edition, candidate, today)
                for candidate in pending
            )
        )
        for candidate, result in zip(pending, results):
            if result is None:
                continue
            race_date, sources = result
            candidate.race_date = race_date
            candidate.sources = _sources([*candidate.sources, *sources])
            candidate.limitations = [
                limitation
                for limitation in candidate.limitations
                if limitation.code != "next_edition_unconfirmed"
            ]
        return candidates

    def _search_next_edition(
        self, candidate: RaceCandidate, today: date
    ) -> tuple[date, list[Source]] | None:
        query = (
            f'Find the date of the next edition, on or after {today}, of the running race '
            f'"{candidate.name}" in {candidate.city}, {candidate.country}.'
        )
        if candidate.official_url:
            query += f" Check its official website {candidate.official_url} first."
        query += (
            " Return race_date as ISO only if it is officially published, with the source_url; "
            "otherwise leave it empty."
        )
        try:
            if self._client is None:
                self._client = default_client()
            response = self._client.search(
                query=query,
                depth="standard",
                output_type="structured",
                structured_output_schema=_NextEdition,
                include_sources=True,
                exclude_domains=EXCLUDED_DOMAINS,
            )
            data = getattr(response, "data", response)
            if isinstance(data, BaseModel):
                data = data.model_dump(mode="json")
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                return None
            edition = _NextEdition.model_validate(data)
            when = parse_date(edition.race_date)
            if when is None or when < today:
                return None
            response_sources = (
                response.get("sources", [])
                if isinstance(response, dict)
                else getattr(response, "sources", [])
            ) or []
            sources = _sources(
                [
                    *([str(edition.source_url)] if edition.source_url else []),
                    *response_sources,
                ]
            )
            sources = [source for source in sources if not _blocked(source.url)]
            return (when, sources) if sources else None
        except Exception:  # noqa: BLE001
            return None

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
