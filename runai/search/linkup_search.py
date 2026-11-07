import json
import re
from datetime import date
from typing import Any, Literal, Protocol

from pydantic import HttpUrl, TypeAdapter, ValidationError

from runai.config import get_settings
from runai.models import Source, TraceEvent
from runai.search.checks import (
    KNOWN_REGISTRATION_PLATFORMS,
    check_sheet,
    host_of,
    is_aggregator,
    missing_fields,
    on_domain,
    registration_url_issue,
)
from runai.search.models import Issue, IssueLevel, RaceSheet
from runai.telemetry import timed
from runai.tracing import TraceWriter

Depth = Literal["standard", "deep"]

_GEOCODE_HINT = "Short place name in the local language, as written on OpenStreetMap, e.g. 'Ponte 25 de Abril, Almada'"

FIELD_SCHEMAS: dict[str, dict[str, Any]] = {
    "name": {"type": "string", "description": "Official name of the race, including the edition year"},
    "city": {"type": "string", "description": "City where the race starts"},
    "country": {"type": "string", "description": "Country name in English"},
    "country_code": {"type": "string", "description": "ISO 3166-1 alpha-2 country code, e.g. PT"},
    "race_date": {"type": "string", "description": "Race day, ISO 8601 date YYYY-MM-DD"},
    "start_time": {"type": "string", "description": "Start time of this distance, 24h HH:MM local time"},
    "distance_km": {"type": "number", "description": "Distance of this race in kilometres"},
    "official_url": {"type": "string", "description": "Official website of the race organiser"},
    "registration_url": {
        "type": "string",
        "description": "Official registration page (organiser site or its ticketing platform)",
    },
    "start_location": {"type": "string", "description": "Name of the start area or landmark"},
    "start_address": {"type": "string", "description": "Street address of the start, if published"},
    "start_geocode_query": {"type": "string", "description": _GEOCODE_HINT},
    "bib_pickup_location": {"type": "string", "description": "Name of the bib pick-up venue (race expo)"},
    "bib_pickup_address": {"type": "string", "description": "Street address of the bib pick-up venue"},
    "bib_pickup_geocode_query": {"type": "string", "description": _GEOCODE_HINT},
    "bib_pickup_days": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Bib pick-up days, ISO 8601 dates YYYY-MM-DD",
    },
    "bib_pickup_hours": {"type": "string", "description": "Bib pick-up opening hours, e.g. 10:00-20:00"},
    "race_date_source_url": {"type": "string", "description": "URL of the page giving the date"},
    "registration_source_url": {"type": "string", "description": "URL of the page linking to registration"},
    "bib_pickup_source_url": {"type": "string", "description": "URL of the page giving bib pick-up details"},
    "start_source_url": {"type": "string", "description": "URL of the page giving the start location"},
}

RACE_SCHEMA: dict[str, Any] = {"type": "object", "properties": FIELD_SCHEMAS, "required": ["name"]}

_FIELD_SOURCES = {
    "race_date": "race_date_source_url",
    "registration_url": "registration_source_url",
    "bib_pickup": "bib_pickup_source_url",
    "start_location": "start_source_url",
}

_FOLLOW_UP_KEYS = {
    "race_date": ["race_date", "race_date_source_url"],
    "start_time": ["start_time"],
    "distance_km": ["distance_km"],
    "registration_url": ["registration_url", "registration_source_url"],
    "start_location": ["start_location", "start_address", "start_geocode_query", "start_source_url"],
    "bib_pickup.location": [
        "bib_pickup_location",
        "bib_pickup_address",
        "bib_pickup_geocode_query",
        "bib_pickup_source_url",
    ],
    "bib_pickup.days": ["bib_pickup_days", "bib_pickup_source_url"],
    "bib_pickup.hours": ["bib_pickup_hours", "bib_pickup_source_url"],
}

_REGISTRATION_HINT = re.compile(r"inscri|regist|iscri|sign-?up|entry|entries|anmeld", re.IGNORECASE)
_LINK = re.compile(r"https?://[^\s)\"'<>\]]+")

_URL = TypeAdapter(HttpUrl)


class SearchClient(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any: ...

    def fetch(self, url: str, **kwargs: Any) -> Any: ...


def build_prompt(request: str) -> str:
    return (
        f'Find the next edition of this running race: "{request}". '
        "Use the official organiser website, its official regulations and its official registration platform; "
        "ignore race aggregators, travel agencies and ticket resellers. "
        "Return the race name, city, country and ISO country code, race date, start time and distance of this race "
        "(not of side races sharing the event), the official website, the official registration page URL, "
        "the start location and address, and the bib pick-up (race expo) venue, address, days and opening hours. "
        "For the date, registration, bib pick-up and start, give the URL of the page you read. "
        "If a piece of information is not published, leave the field empty: never guess."
    )


def build_follow_up_prompt(sheet: RaceSheet, missing: list[str]) -> str:
    labels = ", ".join(field.replace("bib_pickup.", "bib pick-up ").replace("_", " ") for field in missing)
    when = f" on {sheet.race_date.isoformat()}" if sheet.race_date else ""
    return (
        f'For the running race "{sheet.name or sheet.query}"{when} in {sheet.city or "its city"}, '
        f"find only these details on the official pages (practical info, FAQ, regulations, expo page): {labels}. "
        "Give the URL of the page you read. If a detail is not published, leave it empty: never guess."
    )


def default_client() -> SearchClient:
    from linkup import LinkupClient

    api_key = get_settings().linkup_api_key
    if not api_key:
        raise RuntimeError("LINKUP_API_KEY missing: set it in .env")
    return LinkupClient(api_key=api_key)


def _text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _parse_url(text: str | None, field: str, issues: list[Issue]) -> HttpUrl | None:
    if text is None:
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        return _URL.validate_python(text)
    except ValidationError:
        issues.append(Issue(field=field, level=IssueLevel.warning, message=f"Invalid URL ignored: {text!r}"))
        return None


def _date(value: Any, field: str, issues: list[Issue]) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        issues.append(Issue(field=field, level=IssueLevel.warning, message=f"Unrecognized date ignored: {value!r}"))
        return None


def _float(value: Any, field: str, issues: list[Issue]) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).lower().replace(",", ".").removesuffix("km").strip())
    except ValueError:
        issues.append(Issue(field=field, level=IssueLevel.warning, message=f"Unrecognized distance: {value!r}"))
        return None


def _sources(response: Any) -> list[Source]:
    sources: list[Source] = []
    for item in getattr(response, "sources", None) or []:
        url = getattr(item, "url", None)
        if not url:
            continue
        try:
            sources.append(Source(url=url, title=getattr(item, "name", None) or None))
        except ValidationError:
            continue
    return sources


def _data(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", response)
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def _apply(sheet: RaceSheet, data: dict[str, Any], issues: list[Issue], only_missing: bool) -> None:
    """Copy Linkup fields; `only_missing` never overwrites a previously found value."""

    def put(target: Any, attr: str, value: Any) -> None:
        if value in (None, "", []):
            return
        if only_missing and getattr(target, attr) not in (None, "", []):
            return
        setattr(target, attr, value)

    country_code = _text(data, "country_code")
    put(sheet, "name", _text(data, "name"))
    put(sheet, "city", _text(data, "city"))
    put(sheet, "country", _text(data, "country"))
    put(sheet, "country_code", country_code.upper() if country_code and len(country_code) == 2 else None)
    put(sheet, "race_date", _date(data.get("race_date"), "race_date", issues))
    put(sheet, "start_time", _text(data, "start_time"))
    put(sheet, "distance_km", _float(data.get("distance_km"), "distance_km", issues))
    put(sheet, "official_url", _parse_url(_text(data, "official_url"), "official_url", issues))
    put(sheet, "registration_url", _parse_url(_text(data, "registration_url"), "registration_url", issues))
    put(sheet, "start_location", _text(data, "start_location"))
    put(sheet, "start_address", _text(data, "start_address"))
    put(sheet, "start_geocode_query", _text(data, "start_geocode_query"))
    pickup = sheet.bib_pickup
    put(pickup, "location", _text(data, "bib_pickup_location"))
    put(pickup, "address", _text(data, "bib_pickup_address"))
    put(pickup, "geocode_query", _text(data, "bib_pickup_geocode_query"))
    put(pickup, "hours", _text(data, "bib_pickup_hours"))
    raw_days = data.get("bib_pickup_days")
    if isinstance(raw_days, str):
        raw_days = [raw_days]
    days = {day for value in raw_days or [] if (day := _date(value, "bib_pickup.days", issues))}
    put(pickup, "days", sorted(days))
    for field, key in _FIELD_SOURCES.items():
        url = _parse_url(_text(data, key), key, issues)
        if url and (not only_missing or field not in sheet.field_sources):
            sheet.field_sources[field] = url


def _add_sources(sheet: RaceSheet, sources: list[Source]) -> None:
    known = {str(source.url) for source in sheet.sources}
    for source in sources:
        if str(source.url) not in known:
            sheet.sources.append(source)
            known.add(str(source.url))


def _finalize(sheet: RaceSheet, today: date | None) -> RaceSheet:
    sheet.missing_fields = missing_fields(sheet)
    sheet.issues = sheet._notes + check_sheet(sheet, today=today)
    return sheet


def parse_response(request: str, response: Any, today: date | None = None) -> RaceSheet:
    sheet = RaceSheet(query=request)
    _apply(sheet, _data(response), sheet._notes, only_missing=False)
    _add_sources(sheet, _sources(response))
    return _finalize(sheet, today)


def _official_domains(sheet: RaceSheet) -> list[str]:
    urls = [sheet.official_url]
    if registration_url_issue(sheet) is None:
        urls.append(sheet.registration_url)
    hosts = [host_of(url) for url in urls if url is not None]
    return list(dict.fromkeys(host for host in hosts if host))


def complete_missing(
    sheet: RaceSheet, client: SearchClient, depth: Depth = "deep", today: date | None = None
) -> RaceSheet:
    """Follow-up search restricted to official domains, for missing fields only."""
    missing = [field for field in sheet.missing_fields if field in _FOLLOW_UP_KEYS]
    domains = _official_domains(sheet)
    if not missing or not domains:
        return sheet
    keys = list(dict.fromkeys(key for field in missing for key in _FOLLOW_UP_KEYS[field]))
    schema = {"type": "object", "properties": {key: FIELD_SCHEMAS[key] for key in keys}}
    with timed("linkup", "search.structured", depth=depth, output_type="structured",
               domains=domains) as call:
        response = client.search(
            query=build_follow_up_prompt(sheet, missing),
            depth=depth,
            output_type="structured",
            structured_output_schema=json.dumps(schema),
            include_sources=True,
            include_domains=domains,
        )
        call.meta["n_sources"] = len(_sources(response))
    data = {key: value for key, value in _data(response).items() if key in keys}
    _apply(sheet, data, sheet._notes, only_missing=True)
    _add_sources(sheet, _sources(response))
    return _finalize(sheet, today)


def links_on_page(client: SearchClient, url: str) -> list[str]:
    with timed("linkup", "fetch", domains=[host_of(url)]):
        response = client.fetch(url=url, render_js=True)
    markdown = getattr(response, "markdown", "") or ""
    return list(dict.fromkeys(link.rstrip(".,;") for link in _LINK.findall(markdown)))


def _is_registration_link(link: str) -> bool:
    host = host_of(link)
    if is_aggregator(host):
        return False
    return any(on_domain(host, domain) for domain in KNOWN_REGISTRATION_PLATFORMS) or bool(
        _REGISTRATION_HINT.search(link)
    )


def verify_registration_link(sheet: RaceSheet, client: SearchClient, today: date | None = None) -> RaceSheet:
    """Read the official page (Linkup /fetch); use its registration link if the current link is absent."""
    if sheet.official_url is None or registration_url_issue(sheet) is None:
        return sheet
    links = links_on_page(client, str(sheet.official_url))
    registration_host = host_of(sheet.registration_url)
    if not any(host_of(link) == registration_host for link in links):
        candidates = [link for link in links if _is_registration_link(link)]
        if not candidates:
            return sheet
        sheet._notes.append(
            Issue(
                field="registration_url",
                level=IssueLevel.warning,
                message=f"{sheet.registration_url} absent from the official page, "
                "replaced with the registration link it contains",
            )
        )
        sheet.registration_url = _URL.validate_python(candidates[0])
        sheet.field_sources["registration_url"] = sheet.official_url
    sheet.registration_verified = True
    return _finalize(sheet, today)


def search_race(
    request: str,
    *,
    client: SearchClient | None = None,
    depth: Depth = "deep",
    follow_up: bool = True,
    verify_registration: bool = True,
    today: date | None = None,
    trace: TraceWriter | None = None,
) -> RaceSheet:
    """Search for the race described in free text and return sourced, verified details."""
    client = client or default_client()
    with timed("linkup", "search.structured", depth=depth, output_type="structured",
               domains=[]) as call:
        response = client.search(
            query=build_prompt(request),
            depth=depth,
            output_type="structured",
            structured_output_schema=json.dumps(RACE_SCHEMA),
            include_sources=True,
        )
        call.meta["n_sources"] = len(_sources(response))
    sheet = parse_response(request, response, today=today)
    if follow_up:
        sheet = complete_missing(sheet, client, depth=depth, today=today)
    if verify_registration:
        sheet = verify_registration_link(sheet, client, today=today)
    if trace is not None:
        trace.write(
            TraceEvent(
                source="linkup",
                type="race_sheet",
                message=sheet.name or request,
                data=sheet.model_dump(mode="json"),
            )
        )
    return sheet


def search_race_tool(request: str) -> str:
    """Search for a running race (date, time, distance, official registration, bib pick-up, start).

    Return JSON details; `missing_fields` and `issues` flag unfound or unverified information."""
    return search_race(request).model_dump_json(indent=2)
