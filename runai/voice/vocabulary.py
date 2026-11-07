"""Noms de courses, de villes et termes métier : vocabulaire Gladia et repères pour le parseur."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class City:
    name: str
    country: str
    aliases: tuple[str, ...]
    vocabulary: bool = True


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


HALF_MARATHON_KM = 21.0975
MARATHON_KM = 42.195

CITIES: tuple[City, ...] = (
    City("Lisbon", "PT", ("lisbonne", "lisboa", "lisbon")),
    City("Porto", "PT", ("porto", "oporto")),
    City("Milan", "IT", ("milan", "milano")),
    City("Rome", "IT", ("rome", "roma")),
    City("Paris", "FR", ("paris",)),
    City("Barcelona", "ES", ("barcelone", "barcelona")),
    City("Madrid", "ES", ("madrid",)),
    City("Valencia", "ES", ("valence", "valencia")),
    City("Berlin", "DE", ("berlin",)),
    City("London", "GB", ("londres", "london")),
    City("Tokyo", "JP", ("tokyo", "toquio"), vocabulary=False),
)

# Seuls les noms officiels dits explicitement fixent `RaceQuery.name` : « le semi de Lisbonne »
# reste une ville + une distance, car plusieurs semis ont lieu à Lisbonne.
RACES: tuple[RaceName, ...] = (
    RaceName("Meia Maratona de Lisboa", "Lisbon", HALF_MARATHON_KM,
             ("meia maratona de lisboa", "lisbon half marathon"), "pt"),
    RaceName("Maratona de Lisboa", "Lisbon", MARATHON_KM,
             ("maratona de lisboa", "lisbon marathon"), "pt"),
    RaceName("Milano Marathon", "Milan", MARATHON_KM,
             ("milano marathon", "maratona di milano", "milan marathon"), "it"),
    RaceName("Stramilano", "Milan", HALF_MARATHON_KM, ("stramilano",), "it"),
    RaceName("Semi de Paris", "Paris", HALF_MARATHON_KM,
             ("semi de paris", "semi-marathon de paris"), "fr"),
    RaceName("Marathon de Paris", "Paris", MARATHON_KM, ("marathon de paris",), "fr"),
)

TERMS: tuple[Term, ...] = (
    Term("semi-marathon", "fr", ("semi marathon",)),
    Term("Meia Maratona", "pt", ("maya maratona", "meia maratone")),
    Term("Njuko", None, ("nyouko", "niouko")),
    Term("Klikego", "fr", ("clic ego", "click ego")),
    Term("PPS", "fr", ("pé pé esse",)),
    Term("FFA", "fr", ("èf èf a",)),
    Term("Praça do Comércio", "pt", ("prassa do comercio",)),
    Term("Ponte 25 de Abril", "pt"),
    Term("Duomo", "it"),
)

_CITY_LANGUAGE = {"PT": "pt", "IT": "it", "ES": "es", "DE": "de", "GB": "en", "FR": "fr"}


def gladia_vocabulary() -> list[dict]:
    """Entrées `custom_vocabulary_config.vocabulary` pour le live Gladia."""
    entries: list[dict] = []
    for race in RACES:
        entries.append(_entry(race.name, race.language))
    for city in CITIES:
        if not city.vocabulary:
            continue
        display = city.aliases[0].title()
        local = city.aliases[1] if len(city.aliases) > 1 else display
        entries.append(_entry(display, "fr"))
        if local.lower() != display.lower():
            entries.append(_entry(local.title(), _CITY_LANGUAGE.get(city.country)))
    for term in TERMS:
        entries.append(_entry(term.value, term.language, term.pronunciations))
    return entries


def _entry(value: str, language: str | None, pronunciations: tuple[str, ...] = ()) -> dict:
    entry: dict = {"value": value}
    if pronunciations:
        entry["pronunciations"] = list(pronunciations)
    if language:
        entry["language"] = language
    return entry
