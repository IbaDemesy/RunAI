"""Offline candidates backed by recorded fixtures."""

import re
import unicodedata
from calendar import month_name

from runai.contracts.common import DataMode, Limitation, Provenance
from runai.contracts.framing import RaceCandidate, Slot, SlotName
from runai.framing.interpret import MONTHS
from runai.models import Race
from runai.search.candidates import (
    CandidateSearchError,
    CandidateSearchResult,
    location_hint,
)


def normalized(value: object) -> str:
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold().strip()


class FixtureCandidateSearch:
    def __init__(self, races: list[Race], mode: DataMode):
        if mode is DataMode.live:
            raise ValueError("Fixtures are not live data")
        if mode is DataMode.demo and not races:
            raise ValueError("Demo search requires at least one recorded race")
        self.races = races
        self.mode = mode

    async def find_candidates(
        self, slots: dict[SlotName, Slot], request_text: str | None = None
    ) -> list[RaceCandidate]:
        return (await self.search(slots, request_text=request_text)).candidates

    async def search(
        self, slots: dict[SlotName, Slot], request_text: str | None = None
    ) -> CandidateSearchResult:
        place = location_hint(request_text)
        has_city_or_race = any(
            name in slots and slots[name].is_known
            for name in (SlotName.city, SlotName.race)
        )
        races = [] if place and not has_city_or_race else self.races

        def value(name):
            slot = slots.get(name)
            return slot.value if slot and slot.is_known else None

        matches = []
        closest = []
        for index, race in enumerate(races):
            city, name = value(SlotName.city), value(SlotName.race)
            race_matches = name and (
                normalized(name) in normalized(race.name)
                or normalized(name) == normalized(race.city)
            )
            if not race_matches and (name or (city and normalized(city) != normalized(race.city))):
                continue
            day, distance = value(SlotName.race_date), value(SlotName.distance_km)
            is_close = bool((day and str(day) != str(race.race_date)) or (distance and distance != race.distance_km))
            window = normalized(value(SlotName.date_window) or "")
            if window and race.race_date:
                months = [i for i in range(1, 13) if normalized(MONTHS[i - 1]) in window or month_name[i].casefold() in window]
                years = re.findall(r"\b\d{4}\b", window)
                is_close |= bool((months and race.race_date.month not in months) or (years and str(race.race_date.year) not in years))
            candidate = RaceCandidate(
                id=f"{self.mode.value}-{index}", name=race.name, city=race.city,
                country=race.country, race_date=race.race_date,
                distances_km=[race.distance_km] if race.distance_km else [],
                official_url=race.sources[0].url if race.sources else None,
                registration_url=race.registration_url, sources=race.sources,
                provenance=Provenance(
                    kind="fixture" if self.mode is DataMode.demo else "replay",
                    label=f"{self.mode.value}: recorded event, not live",
                ),
                limitations=[Limitation(code="close_match", message="Recorded race differs from the requested distance or date.")] if is_close else [],
            )
            (closest if is_close else matches).append(candidate)
        matches = matches or closest
        limitations = []
        if not matches and self.mode is DataMode.demo:
            fallback = await self.search({})
            matches = fallback.candidates
            limitations = [Limitation(
                code="demo_closest",
                message="Demo mode: no recorded race for that request — pick one of the recorded demo races below.",
            )]
            for candidate in matches:
                candidate.limitations.append(Limitation(code="close_match", message="Recorded demo alternative."))
        elif not matches:
            limitations = [Limitation(code="fixture_missing", message="No recorded fixture matches this request.")]
        return CandidateSearchResult(candidates=matches, limitations=limitations)


class UnavailableCandidateSearch:
    def __init__(self, message: str):
        self.message = message

    async def find_candidates(self, slots, request_text: str | None = None):
        raise CandidateSearchError(self.message)
