import math
import re
import time
from typing import Protocol

import httpx

from runai.search.models import GeoPoint, RaceLocations, RaceSheet

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "RunAI-hackathon/0.1 (+https://github.com/IbaDemesy/RunAI)"
MAX_DISTANCE_FROM_CITY_KM = 30.0

_PARENTHESES = re.compile(r"\s*\([^)]*\)")


class Geocoder(Protocol):
    def geocode(self, query: str, country_code: str | None = None) -> GeoPoint | None: ...


class NominatimGeocoder:
    """Géocodage OpenStreetMap : 1 requête par seconde au plus, User-Agent identifiant (politique Nominatim)."""

    provider = "nominatim"

    def __init__(self, client: httpx.Client | None = None, min_interval_s: float = 1.0):
        self._client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10)
        self._min_interval_s = min_interval_s
        self._last_call = 0.0
        self._cache: dict[tuple[str, str | None], GeoPoint | None] = {}

    def geocode(self, query: str, country_code: str | None = None) -> GeoPoint | None:
        key = (query, country_code)
        if key in self._cache:
            return self._cache[key]
        wait = self._min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        params: dict[str, str | int] = {"q": query, "format": "jsonv2", "limit": 1}
        if country_code:
            params["countrycodes"] = country_code.lower()
        response = self._client.get(NOMINATIM_URL, params=params)
        self._last_call = time.monotonic()
        response.raise_for_status()
        results = response.json()
        point = None
        if results:
            first = results[0]
            point = GeoPoint(
                lat=float(first["lat"]),
                lon=float(first["lon"]),
                label=first.get("display_name", query),
                query=query,
                provider=self.provider,
            )
        self._cache[key] = point
        return point


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def geocode_queries(*places: str | None, city: str | None) -> list[str]:
    queries: list[str] = []
    for place in places:
        if not place:
            continue
        cleaned = _PARENTHESES.sub("", place).strip(" ,")
        variants = [cleaned]
        if city and city.lower() not in cleaned.lower():
            variants.append(f"{cleaned}, {city}")
        head = cleaned.split(",")[0].strip()
        if head != cleaned and city:
            variants.append(f"{head}, {city}")
        for query in variants:
            if query and query not in queries:
                queries.append(query)
    return queries


def _first_match(
    geocoder: Geocoder, queries: list[str], country_code: str | None, city_center: GeoPoint | None
) -> GeoPoint | None:
    for query in queries:
        point = geocoder.geocode(query, country_code)
        if point is None:
            continue
        if city_center is not None and distance_km(point, city_center) > MAX_DISTANCE_FROM_CITY_KM:
            continue
        return point
    return None


def locate_race(sheet: RaceSheet, geocoder: Geocoder | None = None) -> RaceLocations:
    """Coordonnées du départ et du retrait du dossard.

    `None` si le lieu est inconnu, introuvable ou à plus de 30 km de la ville : jamais de centre-ville par défaut.
    """
    geocoder = geocoder or NominatimGeocoder()
    country_code = sheet.country_code
    city_center = geocoder.geocode(sheet.city, country_code) if sheet.city else None
    start = _first_match(
        geocoder,
        geocode_queries(sheet.start_geocode_query, sheet.start_address, sheet.start_location, city=sheet.city),
        country_code,
        city_center,
    )
    pickup = sheet.bib_pickup
    bib_pickup = _first_match(
        geocoder,
        geocode_queries(pickup.geocode_query, pickup.address, pickup.location, city=sheet.city),
        country_code,
        city_center,
    )
    return RaceLocations(start=start, bib_pickup=bib_pickup)
