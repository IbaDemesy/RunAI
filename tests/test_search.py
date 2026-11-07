import json
from datetime import date
from types import SimpleNamespace

import httpx

from runai.search import (
    GeoPoint,
    IssueLevel,
    NominatimGeocoder,
    RaceSheet,
    locate_race,
    parse_response,
    search_race,
)
from runai.search.geo import geocode_queries
from runai.search.linkup_search import RACE_SCHEMA

TODAY = date(2026, 11, 7)

MILAN = {
    "name": "Wizz Air Milano Marathon 2027",
    "city": "Milan",
    "country": "Italy",
    "country_code": "it",
    "race_date": "2027-04-04",
    "start_time": "08:00",
    "distance_km": 42.195,
    "official_url": "https://www.milanomarathon.it/en/",
    "registration_url": "https://in.njuko.com/wizz-air-milano-marathon-2027",
    "start_location": "Corso Sempione",
    "bib_pickup_location": "Superstudio Maxi",
    "bib_pickup_address": "Via Moncucco 35, Milano",
    "bib_pickup_days": ["2027-04-03", "2027-04-01", "2027-04-02"],
    "bib_pickup_hours": "10:00-20:00",
    "race_date_source_url": "https://www.milanomarathon.it/en/marathon/",
}


def _source(url, name="page"):
    return SimpleNamespace(url=url, name=name)


def _response(data, urls=("https://www.milanomarathon.it/en/marathon/",)):
    return SimpleNamespace(data=data, sources=[_source(url) for url in urls])


class FakeLinkup:
    def __init__(self, responses, pages=None):
        self.responses = list(responses)
        self.pages = pages or {}
        self.searches = []
        self.fetches = []

    def search(self, query, **kwargs):
        self.searches.append({"query": query, **kwargs})
        return self.responses.pop(0)

    def fetch(self, url, **kwargs):
        self.fetches.append(url)
        return SimpleNamespace(markdown=self.pages.get(url, ""))


class FakeGeocoder:
    def __init__(self, places):
        self.places = places
        self.queries = []

    def geocode(self, query, country_code=None):
        self.queries.append(query)
        if query not in self.places:
            return None
        lat, lon = self.places[query]
        return GeoPoint(lat=lat, lon=lon, label=query, query=query, provider="fake")


def _fields(issues, level=None):
    return {issue.field for issue in issues if level is None or issue.level is level}


def test_parse_complete_sheet():
    sheet = parse_response("marathon de Milan 2027", _response(MILAN), today=TODAY)
    assert sheet.country_code == "IT"
    assert sheet.race_date == date(2027, 4, 4)
    assert sheet.bib_pickup.days[0] == date(2027, 4, 1)
    assert str(sheet.field_sources["race_date"]).startswith("https://www.milanomarathon.it")
    assert sheet.missing_fields == []
    assert sheet.issues == []
    assert sheet.is_reliable


def test_missing_fields_are_reported_not_invented():
    data = {key: value for key, value in MILAN.items() if key not in {"start_time", "bib_pickup_hours"}}
    sheet = parse_response("marathon de Milan 2027", _response(data), today=TODAY)
    assert sheet.start_time is None
    assert sheet.missing_fields == ["start_time", "bib_pickup.hours"]
    assert _fields(sheet.issues, IssueLevel.warning) == {"start_time", "bib_pickup.hours"}
    assert sheet.is_reliable


def test_past_or_wrong_edition_is_an_error():
    sheet = parse_response("marathon de Milan 2027", _response({**MILAN, "race_date": "2026-04-12"}), today=TODAY)
    assert "race_date" in _fields(sheet.issues, IssueLevel.error)
    assert not sheet.is_reliable


def test_distance_must_match_request():
    sheet = parse_response("semi de Lisbonne 2027", _response({**MILAN, "distance_km": 7}), today=TODAY)
    assert "distance_km" in _fields(sheet.issues, IssueLevel.error)


def test_registration_on_aggregator_or_unknown_domain_is_an_error():
    for url in ("https://www.ahotu.com/event/milano-marathon", "https://cheap-bibs.example.com/milan"):
        sheet = parse_response("marathon de Milan 2027", _response({**MILAN, "registration_url": url}), today=TODAY)
        assert "registration_url" in _fields(sheet.issues, IssueLevel.error)


def test_registration_on_official_subdomain_is_accepted():
    data = {
        **MILAN,
        "official_url": "https://maratonaclubedeportugal.com/corrida-marco/edp-meia-maratona-de-lisboa/",
        "registration_url": "https://meia-maratona.inscricoes.maratonaclubedeportugal.com/ballot/",
    }
    assert "registration_url" not in _fields(parse_response("x", _response(data), today=TODAY).issues)


def test_bib_pickup_after_race_is_flagged():
    sheet = parse_response("marathon de Milan 2027", _response({**MILAN, "bib_pickup_days": ["2027-04-05"]}), today=TODAY)
    assert "bib_pickup.days" in _fields(sheet.issues, IssueLevel.warning)


def test_garbage_values_are_dropped_with_a_warning():
    data = {**MILAN, "race_date": "next spring", "registration_url": "not a url", "distance_km": "long"}
    sheet = parse_response("marathon de Milan 2027", _response(data), today=TODAY)
    assert sheet.race_date is None and sheet.registration_url is None and sheet.distance_km is None
    assert {"race_date", "registration_url", "distance_km"} <= set(sheet.missing_fields)


def test_no_sources_is_an_error():
    sheet = parse_response("marathon de Milan 2027", _response(MILAN, urls=()), today=TODAY)
    assert "sources" in _fields(sheet.issues, IssueLevel.error)


def test_search_race_uses_structured_output_and_follows_up_on_missing_fields():
    first = {key: value for key, value in MILAN.items() if not key.startswith("bib_pickup")}
    follow_up = {
        "bib_pickup_location": "Superstudio Maxi",
        "bib_pickup_days": ["2027-04-01"],
        "bib_pickup_hours": "10:00-20:00",
        "name": "must not overwrite",
    }
    client = FakeLinkup([_response(first), _response(follow_up, urls=("https://www.milanomarathon.it/en/practical-info/",))])
    sheet = search_race("marathon de Milan 2027", client=client, today=TODAY)

    assert client.searches[0]["output_type"] == "structured"
    assert json.loads(client.searches[0]["structured_output_schema"]) == RACE_SCHEMA
    assert client.searches[1]["include_domains"] == ["milanomarathon.it", "in.njuko.com"]
    assert "bib pick-up" in client.searches[1]["query"]
    assert sheet.name == "Wizz Air Milano Marathon 2027"
    assert sheet.bib_pickup.location == "Superstudio Maxi"
    assert len(sheet.sources) == 2
    assert sheet.missing_fields == []
    assert client.fetches == []


def test_unknown_registration_domain_is_replaced_by_the_link_on_the_official_page():
    official = "https://maratonaclubedeportugal.com/corrida-marco/edp-meia-maratona-de-lisboa/"
    data = {**MILAN, "official_url": official, "registration_url": "https://www.running-portugal.com/registration.html"}
    page = "[Facebook](https://www.facebook.com/mcp) [Inscrições](https://meia-maratona.inscricoes.maratonaportugal.org/?prova_id=3769)"
    client = FakeLinkup([_response(data)], pages={official: page})
    sheet = search_race("semi de Lisbonne 2027", client=client, follow_up=False, today=TODAY)

    assert client.fetches == [official]
    assert str(sheet.registration_url) == "https://meia-maratona.inscricoes.maratonaportugal.org/?prova_id=3769"
    assert sheet.registration_verified
    assert "registration_url" not in _fields(sheet.issues, IssueLevel.error)
    assert "registration_url" in _fields(sheet.issues, IssueLevel.warning)


def test_unknown_registration_domain_stays_an_error_without_official_link():
    data = {**MILAN, "registration_url": "https://cheap-bibs.example.com/milan"}
    client = FakeLinkup([_response(data)], pages={MILAN["official_url"]: "no links here"})
    sheet = search_race("marathon de Milan 2027", client=client, follow_up=False, today=TODAY)
    assert not sheet.registration_verified
    assert not sheet.is_reliable


def test_to_race_flattens_bib_pickup():
    race = parse_response("marathon de Milan 2027", _response(MILAN), today=TODAY).to_race()
    assert race.country == "IT"
    assert race.bib_pickup.startswith("Superstudio Maxi ; Via Moncucco 35")


def test_geocode_queries_strip_parentheses_and_add_city():
    queries = geocode_queries("Centro de Congressos de Lisboa (CCL), Praça das Indústrias", city="Lisbon")
    assert queries == [
        "Centro de Congressos de Lisboa, Praça das Indústrias",
        "Centro de Congressos de Lisboa, Praça das Indústrias, Lisbon",
        "Centro de Congressos de Lisboa, Lisbon",
    ]


def test_locate_race_falls_back_and_rejects_far_away_matches():
    sheet = RaceSheet(
        query="marathon de Milan 2027",
        city="Milan",
        country_code="IT",
        start_location="Corso Sempione",
        start_geocode_query="Corso Sempione, Milano",
    )
    sheet.bib_pickup.geocode_query = "Superstudio Maxi"
    sheet.bib_pickup.address = "Via Moncucco 35, Milano"
    geocoder = FakeGeocoder(
        {
            "Milan": (45.4642, 9.19),
            "Corso Sempione, Milano": (45.4795, 9.1667),
            "Superstudio Maxi": (40.0, 9.0),
            "Via Moncucco 35, Milano": (45.4389, 9.1669),
        }
    )
    locations = locate_race(sheet, geocoder)
    assert locations.start.query == "Corso Sempione, Milano"
    assert locations.bib_pickup.query == "Via Moncucco 35, Milano"


def test_locate_race_returns_none_when_place_is_unknown():
    sheet = RaceSheet(query="x", city="Milan")
    locations = locate_race(sheet, FakeGeocoder({"Milan": (45.46, 9.19)}))
    assert locations.start is None and locations.bib_pickup is None


def test_nominatim_geocoder_parses_and_caches():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"lat": "45.48", "lon": "9.17", "display_name": "Corso Sempione, Milano"}])

    geocoder = NominatimGeocoder(httpx.Client(transport=httpx.MockTransport(handler)), min_interval_s=0)
    point = geocoder.geocode("Corso Sempione", "IT")
    assert (point.lat, point.lon) == (45.48, 9.17)
    assert geocoder.geocode("Corso Sempione", "IT") == point
    assert len(calls) == 1
    assert calls[0].url.params["countrycodes"] == "it"
