"""Extraction du règlement d'une course (Linkup structuré), avec fixtures vérifiées et cache disque."""

import json
import os
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import HttpUrl, TypeAdapter, ValidationError

from runai.config import get_settings
from runai.logistics.durations import parse_duration
from runai.logistics.models import (
    EntryPath,
    FieldSource,
    LicenseKind,
    PickupWindow,
    RaceRules,
    Requirement,
    RequirementKind,
    TimeGate,
)
from runai.models import Race

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CRITICAL_FIELDS = ("race_date", "start_time", "bib_pickup_windows", "time_limit", "entry_paths")
EXCLUDED_DOMAINS = ["finishers.com"]
COUNTRY_TIMEZONES = {
    "AT": "Europe/Vienna",
    "BE": "Europe/Brussels",
    "CH": "Europe/Zurich",
    "DE": "Europe/Berlin",
    "ES": "Europe/Madrid",
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "IT": "Europe/Rome",
    "LU": "Europe/Luxembourg",
    "NL": "Europe/Amsterdam",
    "PT": "Europe/Lisbon",
}

_HH_MM = {"type": "string", "description": "Local time, 24h HH:MM"}
_URL_HINT = "URL of the official page or regulation PDF where you read it"

RULES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["race_name"],
    "properties": {
        "race_name": {"type": "string", "description": "Official name of the race, with the edition year"},
        "race_date": {"type": "string", "description": "Race day, ISO 8601 YYYY-MM-DD"},
        "distance_km": {"type": "number", "description": "Distance of the main race in km"},
        "country_code": {"type": "string", "description": "ISO 3166-1 alpha-2 country code"},
        "official_url": {"type": "string", "description": "Official website"},
        "regulation_url": {"type": "string", "description": "Official regulation (page or PDF) of this edition"},
        "start_time": {**_HH_MM, "description": "Start time of the main race (first wave), 24h HH:MM"},
        "start_location": {"type": "string", "description": "Start area (street, square)"},
        "start_waves": {"type": "string", "description": "Start waves / corrals and how they are assigned"},
        "corrals_open_time": {**_HH_MM, "description": "Time the start corrals open, 24h HH:MM"},
        "corrals_close_minutes_before_wave": {
            "type": "integer",
            "description": "Minutes before its wave start when a corral closes",
        },
        "bag_drop": {"type": "string", "description": "Bag drop location and rules"},
        "start_source_url": {"type": "string", "description": _URL_HINT},
        "race_date_source_url": {"type": "string", "description": _URL_HINT},
        "bib_pickup_location": {"type": "string", "description": "Bib pick-up venue (expo)"},
        "bib_pickup_windows": {
            "type": "array",
            "description": "One item per bib pick-up day",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "opens": _HH_MM,
                    "closes": _HH_MM,
                },
            },
        },
        "bib_pickup_race_day": {"type": "boolean", "description": "Can bibs be collected on race morning?"},
        "bib_pickup_proxy_allowed": {"type": "boolean", "description": "Can someone else collect the bib?"},
        "bib_pickup_source_url": {"type": "string", "description": _URL_HINT},
        "time_limit": {"type": "string", "description": "Overall time limit, H:MM"},
        "time_gates": {
            "type": "array",
            "description": "Intermediate cut-off gates",
            "items": {
                "type": "object",
                "properties": {
                    "km": {"type": "number"},
                    "max_elapsed": {"type": "string", "description": "Max race time at this km, H:MM"},
                    "clock_time": {**_HH_MM, "description": "Published clock time of the gate, if any"},
                },
            },
        },
        "time_limit_source_url": {"type": "string", "description": _URL_HINT},
        "aid_stations": {"type": "string", "description": "Aid stations: number, kilometres, what is served"},
        "aid_stations_source_url": {"type": "string", "description": _URL_HINT},
        "min_age": {"type": "integer", "description": "Minimum age to enter the main race"},
        "license_accepted": {"type": "boolean", "description": "Is an athletics federation licence accepted?"},
        "license_details": {"type": "string", "description": "Which licences are accepted"},
        "medical_certificate_required": {
            "type": "boolean",
            "description": "Do runners without licence need a medical certificate (or PPS in France)?",
        },
        "medical_certificate_details": {
            "type": "string",
            "description": "Certificate wording, mandatory exams (e.g. stress ECG), validity, foreign runners",
        },
        "runcard_required": {"type": "boolean", "description": "Is an Italian RUNCARD required without licence?"},
        "non_competitive_option": {
            "type": "boolean",
            "description": "Is there a non-competitive entry without medical certificate?",
        },
        "non_competitive_details": {"type": "string", "description": "Conditions and limits of that entry"},
        "documents_source_url": {"type": "string", "description": _URL_HINT},
        "registration_deadline": {"type": "string", "description": "Registration closing date, YYYY-MM-DD"},
        "registration_deadline_source_url": {"type": "string", "description": _URL_HINT},
    },
}

FIELD_GROUPS = {
    "race_date": "race_date",
    "distance_km": "race_date",
    "start_time": "start",
    "start_location": "start",
    "start_waves": "start",
    "corrals_open": "start",
    "corrals_close_before_wave": "start",
    "bag_drop": "start",
    "bib_pickup_location": "bib_pickup",
    "bib_pickup_windows": "bib_pickup",
    "bib_pickup_race_day": "bib_pickup",
    "bib_pickup_proxy_allowed": "bib_pickup",
    "time_limit": "time_limit",
    "time_gates": "time_limit",
    "aid_stations": "aid_stations",
    "min_age": "documents",
    "entry_paths": "documents",
    "registration_deadline": "registration_deadline",
}

_URL = TypeAdapter(HttpUrl)
_TIME = re.compile(r"(\d{1,2})\s*[h:.]\s*(\d{2})?")
_PPS = re.compile(r"\bPPS\b|pass pr[ée]vention|parcours pr[ée]vention", re.IGNORECASE)


class SearchClient(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any: ...


def default_client() -> SearchClient:
    from linkup import LinkupClient

    api_key = get_settings().linkup_api_key
    if not api_key:
        raise RuntimeError("LINKUP_API_KEY manquante : renseignez-la dans .env")
    return LinkupClient(api_key=api_key)


def default_cache_dir() -> Path:
    return Path(os.getenv("RUNAI_LOGISTICS_CACHE") or get_settings().traces_dir / "logistics-cache")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize(text)).strip("-")


def build_rules_prompt(name: str, race: Race | None = None) -> str:
    when = f" on {race.race_date.isoformat()}" if race and race.race_date else ""
    where = f" in {race.city}" if race and race.city else ""
    return (
        f'Read the official regulation of the running race "{name}"{when}{where} (organiser website, regulation '
        "PDF, practical information / FAQ of this edition; ignore aggregators, travel agencies and blogs). "
        "Return: start time of the main race and start waves/corrals (opening time, closing minutes before each "
        "wave), start area, bag drop, bib pick-up venue with one item per pick-up day (date, opening and closing "
        "time), whether bibs can be collected on race morning or by someone else, overall time limit and "
        "intermediate cut-off gates (km, max race time, published clock time), aid stations, minimum age, "
        "registration deadline, and entry requirements for a runner living in France without licence: accepted "
        "licences, medical certificate and mandatory exams (e.g. ECG after exercise), RUNCARD, non-competitive "
        "entry. Give, for each group, the URL of the official page you read. "
        "If something is not published, leave it empty: never guess."
    )


def extract_rules(
    race: Race | str,
    *,
    client: SearchClient | None = None,
    cache_dir: Path | Literal[False] | None = None,
    use_fixtures: bool = True,
    refresh: bool = False,
    depth: Literal["standard", "deep"] = "standard",
) -> RaceRules:
    """Règlement sourcé d'une course.

    Ordre : fixture vérifiée à la main (ex. Milan 2027), puis cache disque, puis un appel Linkup `/search`
    structuré (≈ 0,006 $ en `standard`). `refresh=True` ignore fixture et cache. `cache_dir=False` désactive
    le cache (par défaut `RUNAI_LOGISTICS_CACHE` ou `traces/logistics-cache/`).
    """
    name = race.name if isinstance(race, Race) else race
    year = race.race_date.year if isinstance(race, Race) and race.race_date else _year_in(name)
    if use_fixtures and not refresh and (fixture := find_fixture(name, year)):
        return fixture
    directory = None if cache_dir is False else cache_dir or default_cache_dir()
    cache_file = directory / f"{slugify(name)}.json" if directory else None
    if cache_file and cache_file.is_file() and not refresh:
        rules = RaceRules.model_validate_json(cache_file.read_text(encoding="utf-8"))
        return rules.model_copy(update={"origin": "cache"})
    client = client or default_client()
    response = client.search(
        query=build_rules_prompt(name, race if isinstance(race, Race) else None),
        depth=depth,
        output_type="structured",
        structured_output_schema=json.dumps(RULES_SCHEMA),
        include_sources=True,
        exclude_domains=EXCLUDED_DOMAINS,
    )
    rules = parse_rules_response(name, response)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(rules.model_dump_json(indent=2), encoding="utf-8")
    return rules


def find_fixture(name: str, year: int | None = None) -> RaceRules | None:
    """Fixture vérifiée correspondant au nom (alias) et à l'année, s'il y en a une."""
    normalized = f" {_normalize(name)} "
    year = year if year is not None else _year_in(name)
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if year is not None and payload.get("year") not in (None, year):
            continue
        if any(f" {_normalize(alias)} " in normalized for alias in payload.get("aliases", [])):
            return RaceRules.model_validate(payload["rules"])
    return None


def parse_rules_response(name: str, response: Any) -> RaceRules:
    """Transforme la réponse structurée Linkup en `RaceRules` ; valeurs illisibles ignorées et notées."""
    data = _data(response)
    notes: list[str] = []
    groups = {
        group: _source(data.get(f"{group}_source_url"))
        for group in ("race_date", "start", "bib_pickup", "time_limit", "aid_stations", "documents")
    }
    groups["registration_deadline"] = _source(data.get("registration_deadline_source_url"))
    country = (_text(data.get("country_code")) or "").upper() or None
    values: dict[str, Any] = {
        "race_date": _date(data.get("race_date")),
        "distance_km": _number(data.get("distance_km")),
        "start_time": _time(data.get("start_time")),
        "start_location": _text(data.get("start_location")),
        "start_waves": _text(data.get("start_waves")),
        "corrals_open": _time(data.get("corrals_open_time")),
        "corrals_close_before_wave": _minutes(data.get("corrals_close_minutes_before_wave")),
        "bag_drop": _text(data.get("bag_drop")),
        "bib_pickup_location": _text(data.get("bib_pickup_location")),
        "bib_pickup_windows": _windows(data.get("bib_pickup_windows")),
        "bib_pickup_race_day": _bool(data.get("bib_pickup_race_day")),
        "bib_pickup_proxy_allowed": _bool(data.get("bib_pickup_proxy_allowed")),
        "time_limit": _duration(data.get("time_limit")),
        "time_gates": _gates(data.get("time_gates")),
        "aid_stations": _text(data.get("aid_stations")),
        "min_age": _int(data.get("min_age")),
        "registration_deadline": _deadline(data.get("registration_deadline")),
        "entry_paths": _entry_paths(data, groups["documents"]),
    }
    field_sources: dict[str, FieldSource] = {}
    for field, value in values.items():
        if value in (None, "", []):
            continue
        source = groups[FIELD_GROUPS[field]]
        if source:
            field_sources[field] = source
        else:
            notes.append(f"{field} : Linkup n'a pas donné de source, à confirmer")
    timezone = COUNTRY_TIMEZONES.get(country or "", "Europe/Paris")
    if country and country not in COUNTRY_TIMEZONES:
        notes.append(f"Fuseau inconnu pour {country} : Europe/Paris par défaut, à confirmer")
    missing = [field for field in CRITICAL_FIELDS if values[field] in (None, [])]
    return RaceRules(
        race_name=_text(data.get("race_name")) or name,
        country_code=country,
        timezone=timezone,
        official_url=_url(data.get("official_url")),
        regulation_url=_url(data.get("regulation_url")),
        field_sources=field_sources,
        missing_fields=missing,
        notes=notes,
        origin="linkup",
        **{key: value for key, value in values.items() if value not in (None, "")},
    )


def _entry_paths(data: dict[str, Any], source: FieldSource | None) -> list[EntryPath]:
    paths: list[EntryPath] = []
    if _bool(data.get("license_accepted")):
        paths.append(
            EntryPath(
                id="license",
                label="Avec licence d'athlétisme",
                licenses=[LicenseKind.host_federation, LicenseKind.foreign_federation],
                requirements=[
                    Requirement(
                        kind=RequirementKind.license,
                        label="Licence valide le jour de la course",
                        detail=_text(data.get("license_details")),
                    )
                ],
                source=source,
            )
        )
    certificate = _bool(data.get("medical_certificate_required"))
    runcard = _bool(data.get("runcard_required"))
    details = _text(data.get("medical_certificate_details"))
    requirements: list[Requirement] = []
    if runcard:
        requirements.append(Requirement(kind=RequirementKind.runcard, label="Runcard FIDAL valide le jour de la course"))
    if certificate:
        label = "Certificat médical d'aptitude à la course en compétition"
        if details and _PPS.search(details):
            label = "PPS (Pass Prévention Santé) ou certificat médical"
        requirements.append(Requirement(kind=RequirementKind.medical_certificate, label=label, detail=details))
    if requirements or certificate is False:
        paths.append(
            EntryPath(
                id="no_license",
                label="Sans licence",
                licenses=[LicenseKind.none],
                requirements=requirements,
                source=source,
            )
        )
    if _bool(data.get("non_competitive_option")):
        limits = _text(data.get("non_competitive_details"))
        paths.append(
            EntryPath(
                id="non_competitive",
                label="Participation non compétitive",
                competitive=False,
                licenses=[LicenseKind.none],
                requirements=[Requirement(kind=RequirementKind.waiver, label="Décharge et déclaration santé à signer")],
                limitations=[limits] if limits else [],
                source=source,
            )
        )
    return paths


def _normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _year_in(text: str) -> int | None:
    match = re.search(r"\b(20\d{2})\b", text)
    return int(match.group(1)) if match else None


def _data(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", response)
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _url(value: Any) -> HttpUrl | None:
    text = _text(value)
    if not text or not text.startswith(("http://", "https://")):
        return None
    try:
        return _URL.validate_python(text)
    except ValidationError:
        return None


def _source(value: Any) -> FieldSource | None:
    url = _url(value)
    return FieldSource(url=url) if url else None


def _date(value: Any) -> date | None:
    text = _text(value)
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _deadline(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        day = _date(text)
        return datetime.combine(day, time(23, 59)) if day else None
    return parsed if len(text) > 10 else datetime.combine(parsed.date(), time(23, 59))


def _time(value: Any) -> time | None:
    text = _text(value)
    match = _TIME.search(text) if text else None
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2) or 0)
    return time(hours, minutes) if hours < 24 and minutes < 60 else None


def _duration(value: Any) -> timedelta | None:
    text = _text(value)
    if not text:
        return None
    try:
        return parse_duration(text)
    except ValueError:
        return None


def _minutes(value: Any) -> timedelta | None:
    number = _int(value)
    return timedelta(minutes=number) if number is not None and number >= 0 else None


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ".").lower().removesuffix("km").strip()) if value not in (None, "") else None
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = (_text(value) or "").lower()
    return {"true": True, "yes": True, "oui": True, "false": False, "no": False, "non": False}.get(text)


def _windows(value: Any) -> list[PickupWindow]:
    windows = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        day, opens, closes = _date(item.get("date")), _time(item.get("opens")), _time(item.get("closes"))
        if day and opens and closes and opens < closes:
            windows.append(PickupWindow(day=day, opens=opens, closes=closes))
    return sorted(windows, key=lambda window: (window.day, window.opens))


def _gates(value: Any) -> list[TimeGate]:
    gates = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        km, elapsed = _number(item.get("km")), _duration(item.get("max_elapsed"))
        if km and elapsed:
            gates.append(TimeGate(km=km, max_elapsed=elapsed, clock_time=_time(item.get("clock_time"))))
    return sorted(gates, key=lambda gate: gate.km)
