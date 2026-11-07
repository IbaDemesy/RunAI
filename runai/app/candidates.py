"""Candidats hors réseau, limités aux fixtures explicitement sélectionnées."""

import unicodedata

from runai.contracts.common import DataMode, Limitation, Provenance
from runai.contracts.framing import RaceCandidate, Slot, SlotName
from runai.models import Race
from runai.search.candidates import CandidateSearchError, CandidateSearchResult


def normalized(value: object) -> str:
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold().strip()


class FixtureCandidateSearch:
    def __init__(self, races: list[Race], mode: DataMode):
        if mode is DataMode.live:
            raise ValueError("Les fixtures ne sont pas des données live")
        self.races = races
        self.mode = mode

    async def find_candidates(
        self, slots: dict[SlotName, Slot], request_text: str | None = None
    ) -> list[RaceCandidate]:
        return (await self.search(slots, request_text=request_text)).candidates

    async def search(
        self, slots: dict[SlotName, Slot], request_text: str | None = None
    ) -> CandidateSearchResult:
        def value(name):
            slot = slots.get(name)
            return slot.value if slot and slot.is_known else None

        matches = []
        for index, race in enumerate(self.races):
            city, name = value(SlotName.city), value(SlotName.race)
            if city and normalized(city) != normalized(race.city):
                continue
            if name and normalized(name) not in normalized(race.name):
                continue
            day, distance = value(SlotName.race_date), value(SlotName.distance_km)
            if day and str(day) != str(race.race_date):
                continue
            if distance and distance != race.distance_km:
                continue
            matches.append(RaceCandidate(
                id=f"{self.mode.value}-{index}", name=race.name, city=race.city,
                country=race.country, race_date=race.race_date,
                distances_km=[race.distance_km] if race.distance_km else [],
                official_url=race.sources[0].url if race.sources else None,
                registration_url=race.registration_url, sources=race.sources,
                provenance=Provenance(
                    kind="fixture" if self.mode is DataMode.demo else "replay",
                    label=f"{self.mode.value} : événement enregistré, non live",
                ),
            ))
        limitations = [] if matches else [Limitation(
            code="fixture_missing",
            message=f"Pas de fixture {self.mode.value} pour cette ville ou ces critères ; précisez un événement pour une préparation manuelle.",
        )]
        return CandidateSearchResult(candidates=matches, limitations=limitations)


class UnavailableCandidateSearch:
    def __init__(self, message: str):
        self.message = message

    async def find_candidates(self, slots, request_text: str | None = None):
        raise CandidateSearchError(self.message)
