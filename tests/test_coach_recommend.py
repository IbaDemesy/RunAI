import os
from datetime import date, timedelta
from types import SimpleNamespace
from typing import ClassVar

import pytest

from runai.coach import (
    DEMO_PREFERENCES,
    DEMO_TRANSCRIPT,
    CacheMiss,
    CandidateRace,
    CoachProfile,
    DiscoveryCache,
    DiscoveryResult,
    RaceFinder,
    RacePreferences,
    RecentRace,
    RecentRun,
    RegistrationStatus,
    assess,
    build_query,
    extract_profile,
    rank_races,
    recommend_races,
)
from runai.coach.models import SearchQuery
from runai.models import Race

TODAY = date(2026, 11, 7)
S = RegistrationStatus


@pytest.fixture
def camille():
    return assess(extract_profile(DEMO_TRANSCRIPT).profile)


@pytest.fixture
def beginner():
    return assess(CoachProfile(sessions_per_week=2, weekly_km=12, longest_recent_run=RecentRun(distance_km=6), recent_race=RecentRace(distance_km=5, time_s=33 * 60, months_ago=1)))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("appel réseau interdit dans les tests")

    monkeypatch.setattr("runai.coach.finder.default_linkup_client", boom)
    monkeypatch.setattr("httpx.Client.send", boom)


def test_demo_milan_replays_offline(camille):
    result = recommend_races(camille, DEMO_PREFERENCES["milan"], mode="replay", today=TODAY)
    assert result.from_cache and 3 <= len(result.races) <= 5
    first = result.races[0]
    assert first.name == "Wizz Air Milano Marathon" and first.race_date == date(2027, 4, 4)
    assert first.status is S.ouvert and "course que tu as citée" in first.reason
    assert all(r.status in (S.ouvert, S.a_verifier) for r in result.races)
    assert all("semaines de préparation" in r.reason for r in result.races)
    names = [r.name for r in result.races]
    assert "Marathon de Milan" not in names and len(set(names)) == len(names)
    race = first.to_race()
    assert isinstance(race, Race) and race.city == "Milan"


@pytest.mark.parametrize("preset", sorted(DEMO_PREFERENCES))
def test_every_demo_preset_has_a_fixture(camille, preset):
    result = recommend_races(camille, DEMO_PREFERENCES[preset], mode="replay", today=TODAY)
    assert result.from_cache and 1 <= len(result.races) <= 5
    for r in result.races:
        assert r.reason and r.status in (S.ouvert, S.a_verifier)
        assert r.needs_h_check == (r.status is S.a_verifier)


def test_replay_without_fixture_raises(camille, tmp_path):
    prefs = RacePreferences(origin_city="Brest", distance_km=10)
    with pytest.raises(CacheMiss):
        recommend_races(camille, prefs, mode="replay", cache=DiscoveryCache(tmp_path, fallbacks=()), today=TODAY)


def test_blocked_distance_falls_back_with_warning(beginner):
    prefs = RacePreferences(distance_km=42.195, date_from=date(2026, 12, 1), date_to=date(2027, 1, 15))
    query, warnings = build_query(beginner, prefs, TODAY)
    assert query.distance_km < 42 and warnings and "bloqué" in warnings[0]


def test_cache_key_is_stable_and_query_specific():
    q = SearchQuery(distance_km=10, distance_label="10 km", tolerance_km=1, date_from=TODAY, date_to=TODAY, origin_city="Paris", max_travel_h=1)
    assert q.cache_key() == q.model_copy().cache_key()
    assert q.cache_key() != q.model_copy(update={"max_travel_h": 2}).cache_key()


def _query(**kw):
    base = {"distance_km": 21.0975, "distance_label": "semi-marathon", "tolerance_km": 1.3, "date_from": date(2027, 3, 1), "date_to": date(2027, 5, 31), "origin_city": "Paris", "max_travel_h": 3}
    return SearchQuery(**{**base, **kw})


def test_rank_prefers_open_then_fills_with_to_check(camille):
    q = _query()
    cands = [
        CandidateRace(name="Semi A", race_date=date(2027, 4, 4), city="A", distance_km=21.1, status=S.ouvert, status_source="page", travel_h_est=1),
        CandidateRace(name="Semi B", race_date=date(2027, 4, 11), city="B", distance_km=21.1, status=S.a_verifier, registration_url="https://in.njuko.com/b", travel_h_est=0.5, check_error="SPA"),
        CandidateRace(name="Semi C", race_date=date(2027, 4, 18), city="C", distance_km=21.1, status=S.a_verifier, travel_h_est=0.5),
        CandidateRace(name="Semi D", race_date=date(2027, 4, 25), city="D", distance_km=21.1, status=S.complet, travel_h_est=0.5),
        CandidateRace(name="Semi E", race_date=date(2027, 5, 2), city="E", distance_km=21.1, status=S.a_verifier, travel_h_est=0.6),
        CandidateRace(name="Semi A bis", race_date=date(2027, 4, 4), city="A", distance_km=21.1, status=S.ouvert, travel_h_est=1),
        CandidateRace(name="Semi hiver", race_date=date(2026, 12, 6), city="F", distance_km=21.1, status=S.ouvert, travel_h_est=1),
    ]
    result = rank_races(camille, DiscoveryResult(query=q, candidates=cands), TODAY)
    assert next(r.name for r in result.races) == "Semi A"
    assert len(result.races) == 3
    assert {r.status for r in result.races[1:]} == {S.a_verifier}
    njuko = next(r for r in result.races if r.name == "Semi B")
    assert njuko.needs_h_check and "agent H" in njuko.reason
    why = {e.name: e.why for e in result.excluded}
    assert why["Semi D"] == "complet" and "doublon" in why["Semi A bis"] and "hors fenêtre" in why["Semi hiver"]
    assert any("non confirmé" in w for w in result.warnings)


def test_rank_rejects_races_too_soon_for_the_runner(beginner):
    q = _query(distance_km=42.195, distance_label="marathon", tolerance_km=2.5, date_from=date(2026, 11, 20))
    soon = CandidateRace(name="Marathon trop tôt", race_date=date(2026, 12, 6), distance_km=42.195, status=S.ouvert)
    result = rank_races(beginner, DiscoveryResult(query=q, candidates=[soon]), TODAY)
    assert result.races == [] and "préparation" in result.excluded[0].why


# --- Finder avec un faux Linkup -----------------------------------------------------------------


class FakeLinkup:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def search(self, query, **kwargs):
        self.calls.append(("search", query))
        schema = kwargs.get("structured_output_schema")
        name = getattr(schema, "__name__", "")
        if name == "_CandidateList":
            return SimpleNamespace(
                data={"races": [
                    {"name": "Semi de Lille", "date": "2027-03-14", "city": "Lille", "distance_km": 21.1, "registration_url": "https://lille.example/inscription"},
                    {"name": "Semi de Reims", "date": "2027-04-11", "city": "Reims", "distance_km": 21.1, "registration_url": "https://in.njuko.com/reims"},
                    {"name": "Semi de Nice", "date": "2027-04-18", "city": "Nice", "distance_km": 21.1},
                    {"name": "Semi de Rouen", "date": "2027-04-25", "city": "Rouen", "distance_km": 21.1, "registration_url": "https://www.ahotu.com/rouen"},
                    {"name": "Semi d'Orléans", "date": "2027-05-09", "city": "Orléans", "distance_km": 21.1},
                    {"name": "Semi d'été", "date": "2027-07-04", "city": "Lille", "distance_km": 21.1},
                ]},
                sources=[],
            )
        if name == "_RegistrationLookup":
            return SimpleNamespace(data={"registration_url": "https://orleans.example/inscription"} if "Orléans" in query else {})
        return SimpleNamespace(data={})

    def fetch(self, url, **kwargs):
        self.calls.append(("fetch", url))
        if "orleans" in url:
            raise RuntimeError("HTTP 400 Bad Request")
        if "ahotu" in url:
            return SimpleNamespace(data={"registration_status": "open", "status_evidence": "Inscriptions ouvertes"})
        return SimpleNamespace(data={"registration_status": "open", "status_evidence": "S'inscrire", "current_price_eur": 30})


class FakeGeocoder:
    POINTS: ClassVar[dict[str, tuple[float, float]]] = {"Paris": (48.85, 2.35), "Lille": (50.63, 3.06), "Reims": (49.26, 4.03), "Nice": (43.7, 7.27), "Rouen": (49.44, 1.1), "Orléans": (47.9, 1.9)}

    def geocode(self, city, country=None):
        point = self.POINTS.get(city)
        return (*point, "FR") if point else None


def test_finder_filters_and_verifies_without_network(camille, tmp_path):
    fake = FakeLinkup()
    finder = RaceFinder(client=fake, geocoder=FakeGeocoder(), calendar_fetch=False)
    prefs = RacePreferences(origin_city="Paris", distance_km=21.0975, date_from=date(2027, 3, 1), date_to=date(2027, 5, 31), max_travel_h=3)
    cache = DiscoveryCache(tmp_path, fallbacks=())
    result = recommend_races(camille, prefs, mode="auto", finder=finder, cache=cache, today=TODAY)

    by_name = {r.name: r for r in result.races}
    assert not result.from_cache
    assert by_name["Semi de Lille"].status is S.ouvert and by_name["Semi de Lille"].price_eur == 30
    assert "30 € lus sur la page" in by_name["Semi de Lille"].reason
    excluded = {e.name: e.why for e in result.excluded}
    assert "trajet" in excluded["Semi de Nice"] and "hors fenêtre" in excluded["Semi d'été"]
    fetched = [u for kind, u in fake.calls if kind == "fetch"]
    assert not any("njuko" in u for u in fetched)

    discovery = cache.get(result.query)
    status = {c.name: c for c in discovery.candidates}
    assert status["Semi de Reims"].status is S.a_verifier and "SPA" in status["Semi de Reims"].check_error
    assert status["Semi de Rouen"].status is S.a_verifier and status["Semi de Rouen"].status_source == "agregateur"
    assert status["Semi d'Orléans"].status is S.a_verifier and "HTTP 400" in status["Semi d'Orléans"].check_error
    assert discovery.metrics.second_round and discovery.metrics.fetch_errors >= 1

    n_calls = len(fake.calls)
    again = recommend_races(camille, prefs, finder=finder, cache=cache, today=TODAY)
    assert again.from_cache and len(fake.calls) == n_calls


@pytest.mark.skipif(not os.getenv("RUNAI_LIVE_TESTS"), reason="réseau Linkup : RUNAI_LIVE_TESTS=1 pour lancer")
def test_live_linkup_search(camille, tmp_path, monkeypatch):
    monkeypatch.undo()
    prefs = RacePreferences(origin_city="Paris", distance_km=10, zone_hint="en Ile-de-France", max_travel_h=1.5)
    result = recommend_races(camille, prefs, mode="live", cache=DiscoveryCache(tmp_path, fallbacks=()))
    assert result.races


def test_same_day_races_in_different_cities_are_kept(camille):
    q = _query(travel_mode="flight")
    cands = [
        CandidateRace(name=f"Semi {city}", race_date=date(2027, 4, 4), city=city, distance_km=21.1, status=S.ouvert, travel_h_est=1.0)
        for city in ("Lille", "Roubaix", "Lillé")
    ]
    names = [r.name for r in rank_races(camille, DiscoveryResult(query=q, candidates=cands), TODAY).races]
    assert names[:2] == ["Semi Lille", "Semi Roubaix"] or set(names) == {"Semi Lille", "Semi Roubaix"}


def test_undated_race_uses_window_start_for_preparation(beginner):
    q = _query(distance_km=42.195, distance_label="marathon", tolerance_km=2.5, date_from=date(2026, 12, 1))
    undated = CandidateRace(name="Marathon sans date", distance_km=42.195, status=S.ouvert)
    result = rank_races(beginner, DiscoveryResult(query=q, candidates=[undated]), TODAY)
    assert result.races == [] and "préparation" in result.excluded[0].why


def test_default_distance_is_feasible_at_window_start(camille):
    prefs = RacePreferences(date_from=date(2026, 12, 5), date_to=date(2027, 6, 30))
    query, _ = build_query(camille, prefs, TODAY)
    assert query.distance_km < 42


def test_auto_mode_ignores_stale_cache_but_replay_uses_it(camille):
    prefs = DEMO_PREFERENCES["milan"]

    class Live:
        def run(self, query):
            return DiscoveryResult(query=query, origin="live")

    class NoWrite(DiscoveryCache):
        def put(self, result):
            return self.path(result.query)

    cache = NoWrite()
    live = recommend_races(camille, prefs, finder=Live(), cache=cache, today=TODAY, max_cache_age=timedelta(0))
    assert not live.from_cache and live.races == []
    assert recommend_races(camille, prefs, mode="replay", cache=cache, today=TODAY).from_cache
