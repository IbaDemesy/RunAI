"""Race names, cities and running terms: Gladia custom vocabulary/spelling and parser hints."""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from runai.contracts.framing import RaceCandidate


@dataclass(frozen=True)
class City:
    name: str
    country: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class RaceName:
    name: str
    city: str
    distance_km: float | None
    aliases: tuple[str, ...]
    language: str | None = None


@dataclass(frozen=True)
class Term:
    value: str
    language: str | None = None
    pronunciations: tuple[str, ...] = field(default_factory=tuple)
    proper: bool = True


HALF_MARATHON_KM = 21.0975
MARATHON_KM = 42.195

# The first alias is the French spoken form, the second the local name (used as a vocabulary entry).
CITIES: tuple[City, ...] = (
    City("Lisbonne", "PT", ("lisbonne", "lisboa", "lisbon")),
    City("Porto", "PT", ("porto", "oporto")),
    City("Milan", "IT", ("milan", "milano")),
    City("Rome", "IT", ("rome", "roma")),
    City("Paris", "FR", ("paris",)),
    City("Barcelone", "ES", ("barcelone", "barcelona")),
    City("Madrid", "ES", ("madrid",)),
    City("Valence", "ES", ("valence", "valencia")),
    City("Berlin", "DE", ("berlin",)),
    City("Londres", "GB", ("londres", "london")),
)

# Only official names said explicitly set `RaceQuery.name`: "le semi de Lisbonne" stays a city
# plus a distance, because several half marathons take place in Lisbon.
RACES: tuple[RaceName, ...] = (
    RaceName("Meia Maratona de Lisboa", "Lisbonne", HALF_MARATHON_KM,
             ("meia maratona de lisboa", "lisbon half marathon"), "pt"),
    RaceName("Maratona de Lisboa", "Lisbonne", MARATHON_KM,
             ("maratona de lisboa", "lisbon marathon"), "pt"),
    RaceName("Milano Marathon", "Milan", MARATHON_KM,
             ("milano marathon", "maratona di milano", "milan marathon"), "it"),
    RaceName("Stramilano", "Milan", HALF_MARATHON_KM, ("stramilano",), "it"),
    RaceName("Semi de Paris", "Paris", HALF_MARATHON_KM,
             ("semi de paris", "semi-marathon de paris", "paris half marathon"), "fr"),
    RaceName("Marathon de Paris", "Paris", MARATHON_KM,
             ("marathon de paris", "paris marathon"), "fr"),
)

TERMS: tuple[Term, ...] = (
    Term("Njuko", None, ("nyouko", "niouko")),
    Term("Klikego", "fr", ("clic ego", "click ego")),
    Term("RunAI", "en", ("run a i", "run ai")),
    Term("Booking.com", "en", ("booking dot com", "booking point com")),
    Term("Accor", "fr", ("a core",)),
    Term("PPS", "fr", ("pé pé esse", "p p s")),
    Term("FFA", "fr", ("èf èf a",)),
    Term("Meia Maratona", "pt", ("maya maratona", "meia maratone")),
    Term("Praça do Comércio", "pt", ("prassa do comercio",)),
    Term("Ponte 25 de Abril", "pt"),
    Term("Duomo", "it"),
    Term("semi-marathon", "fr", ("semi marathon",), proper=False),
    Term("half marathon", "en", proper=False),
    Term("10K", "en", ("ten k",), proper=False),
    Term("bib pickup", "en", ("bib pick up",), proper=False),
    Term("start corral", "en", proper=False),
    Term("medical certificate", "en", proper=False),
)

_CITY_LANGUAGE = {
    "ES": "es", "DE": "de", "GB": "en", "PT": "pt", "IT": "it", "FR": "fr",
    "NL": "nl", "BE": "fr", "LU": "fr", "CH": "fr", "US": "en",
}
# Gladia live only uses a per-entry language that is part of the session languages.
LIVE_LANGUAGES = ("fr", "en", "pt")
PROPER_NAME_INTENSITY = 0.45
GENERIC_TERM_INTENSITY = 0.4
# Above this, Gladia starts forcing vocabulary words onto unrelated speech.
MAX_INTENSITY = 0.6
MAX_ENTRIES = 80


def vocabulary_for(
    candidates: Sequence[RaceCandidate] = (),
    *,
    origin: str | None = None,
    extra: Iterable[str] = (),
) -> list[dict]:
    """`custom_vocabulary_config.vocabulary` entries seeded with the races the runner is choosing from.

    Dynamic entries (candidate names and cities, origin city, extra words) come first, then the
    static base; duplicates are dropped case- and accent-insensitively and the list is capped.
    """
    entries: list[dict] = []
    for candidate in candidates:
        language = _CITY_LANGUAGE.get(candidate.country.upper())
        entries.append(_entry(candidate.name, language))
        entries.append(_entry(candidate.city, language))
    if origin:
        entries.append(_entry(origin, None))
    entries.extend(_entry(value, None) for value in extra)
    entries.extend(_static_entries())
    return _dedupe(entries)[:MAX_ENTRIES]


def gladia_vocabulary() -> list[dict]:
    """Static vocabulary for Gladia live (no race picked yet)."""
    return vocabulary_for()


def custom_spelling_for() -> dict:
    """`realtime_processing.custom_spelling_config`: misheard spellings mapped to the right word."""
    dictionary: dict[str, list[str]] = {}
    for term in TERMS:
        if term.proper and term.pronunciations:
            dictionary[term.value] = list(term.pronunciations)
    return {"spelling_dictionary": dictionary}


def _static_entries() -> list[dict]:
    entries = [_entry(race.name, race.language) for race in RACES]
    for city in CITIES:
        local = city.aliases[1] if len(city.aliases) > 1 else city.name
        entries.append(_entry(city.name, "fr"))
        if local.lower() != city.name.lower():
            entries.append(_entry(local.title(), _CITY_LANGUAGE.get(city.country)))
    entries.extend(
        _entry(term.value, term.language, term.pronunciations,
               PROPER_NAME_INTENSITY if term.proper else GENERIC_TERM_INTENSITY)
        for term in TERMS
    )
    return entries


def _entry(
    value: str,
    language: str | None,
    pronunciations: tuple[str, ...] = (),
    intensity: float = PROPER_NAME_INTENSITY,
) -> dict:
    entry: dict = {"value": " ".join(value.split()), "intensity": min(intensity, MAX_INTENSITY)}
    if pronunciations:
        entry["pronunciations"] = list(pronunciations)
    if language in LIVE_LANGUAGES:
        entry["language"] = language
    return entry


def _key(value: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", stripped.casefold()).strip()


def _dedupe(entries: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for entry in entries:
        key = _key(entry["value"])
        if key and key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique
