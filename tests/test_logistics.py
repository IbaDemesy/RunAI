import json
import os
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from runai.logistics import (
    RULES_SCHEMA,
    AlertLevel,
    HotelStay,
    LicenseKind,
    Light,
    PickupWindow,
    RaceRules,
    RecentResult,
    Requirement,
    RequirementKind,
    RunnerGoal,
    RunnerSituation,
    TransportLeg,
    build_timeline,
    eligibility,
    extract_rules,
    find_fixture,
    parse_duration,
    parse_duration_range,
    parse_rules_response,
    to_ics,
)
from runai.models import Race, RunnerProfile

TODAY = date(2026, 11, 7)
MILAN = Race(name="Wizz Air Milano Marathon 2027", city="Milano", country="IT", race_date=date(2027, 4, 4))
MARATHON = 42.195
HALF = 21.0975

LINKUP_HALF = {
    "race_name": "Semi-marathon de Test 2027",
    "race_date": "2027-03-14",
    "distance_km": 21.1,
    "country_code": "fr",
    "start_time": "9h30",
    "start_location": "Place du Test",
    "bib_pickup_windows": [
        {"date": "2027-03-13", "opens": "10:00", "closes": "18:00"},
        {"date": "2027-03-12", "opens": "14:00", "closes": "19h"},
        {"date": "bad", "opens": "10:00", "closes": "18:00"},
    ],
    "bib_pickup_race_day": "false",
    "bib_pickup_source_url": "https://semi-test.example.org/infos",
    "time_limit": "2h30",
    "time_gates": [{"km": 10, "max_elapsed": "1:15"}],
    "time_limit_source_url": "https://semi-test.example.org/reglement.pdf",
    "license_accepted": True,
    "foreign_license_accepted": True,
    "medical_certificate_required": True,
    "medical_certificate_details": "PPS ou certificat médical de moins d'un an",
    "documents_source_url": "https://semi-test.example.org/reglement.pdf",
    "race_date_source_url": "not a url",
}


class FakeLinkup:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return SimpleNamespace(data=self.data, sources=[])


@pytest.fixture
def milan() -> RaceRules:
    return extract_rules(MILAN, cache_dir=False)


@pytest.fixture
def half() -> RaceRules:
    return parse_rules_response("Semi de Test", SimpleNamespace(data=LINKUP_HALF))


def test_milan_fixture_is_sourced_and_used_without_network(milan):
    assert milan.origin == "fixture"
    assert milan.start_time == time(8, 15) and milan.time_limit == timedelta(hours=6, minutes=30)
    assert [gate.km for gate in milan.time_gates] == [21.1, 27.8]
    assert [w.day.day for w in milan.bib_pickup_windows] == [1, 2, 3]
    assert milan.bib_pickup_race_day is False
    assert "start_location" in milan.missing_fields
    for field in ("start_time", "time_limit", "time_gates", "bib_pickup_windows", "entry_paths"):
        assert milan.source_url(field), field
    abroad = next(p for p in milan.entry_paths if p.id == "runcard_foreign_resident_abroad")
    certificate = next(r for r in abroad.requirements if r.kind is RequirementKind.medical_certificate)
    assert "post-exercise" in certificate.detail and "Elettrocardiogramma" in certificate.source.excerpt


def test_fixture_matching_respects_year_and_aliases():
    assert find_fixture("Marathon de Milan", 2027)
    assert find_fixture("Milano Marathon 2026") is None
    assert find_fixture("Milano Marathon Relay 2027") is None
    assert find_fixture("Wizz Air Milano Marathon", 2026) is None
    assert find_fixture("Marathon de Paris 2027") is None


def test_extract_rules_calls_linkup_once_then_uses_cache(tmp_path):
    client = FakeLinkup(LINKUP_HALF)
    race = Race(name="Semi de Test 2027", city="Test", country="FR", race_date=date(2027, 3, 14))
    first = extract_rules(race, client=client, cache_dir=tmp_path)
    second = extract_rules(race, client=client, cache_dir=tmp_path)
    assert len(client.calls) == 1 and first.origin == "linkup" and second.origin == "cache"
    call = client.calls[0]
    assert call["output_type"] == "structured" and call["depth"] == "standard"
    assert json.loads(call["structured_output_schema"]) == RULES_SCHEMA
    assert "finishers.com" in call["exclude_domains"]
    extract_rules(race, client=client, cache_dir=tmp_path, refresh=True)
    assert len(client.calls) == 2


def test_cache_is_per_edition(tmp_path):
    client = FakeLinkup(LINKUP_HALF)
    for year in (2027, 2028):
        extract_rules(Race(name="Semi de Test", city="Test", country="FR", race_date=date(year, 3, 14)),
                      client=client, cache_dir=tmp_path)
    assert len(client.calls) == 2


def test_parse_rules_response_keeps_sources_per_field_and_drops_bad_values(half):
    assert half.country_code == "FR" and half.timezone == "Europe/Paris"
    assert half.start_time == time(9, 30)
    assert [(w.day.day, w.closes) for w in half.bib_pickup_windows] == [(12, time(19, 0)), (13, time(18, 0))]
    assert half.source_url("bib_pickup_windows") == "https://semi-test.example.org/infos"
    assert half.source_url("time_limit") == "https://semi-test.example.org/reglement.pdf"
    assert half.source_url("race_date") is None
    assert any(note.startswith("race_date") for note in half.notes)
    assert [p.id for p in half.entry_paths] == ["license", "no_license"]
    assert half.entry_paths[1].requirements[0].label.startswith("PPS")
    assert half.missing_fields == []


def test_parse_rules_response_lists_missing_critical_fields():
    rules = parse_rules_response("Course X", SimpleNamespace(data={"race_name": "Course X"}))
    assert rules.missing_fields == ["race_date", "start_time", "bib_pickup_windows", "time_limit", "entry_paths"]


def test_durations():
    assert parse_duration("3h15'") == timedelta(hours=3, minutes=15)
    assert parse_duration("6h30”") == timedelta(hours=6, minutes=30)
    assert parse_duration("2:10:30") == timedelta(hours=2, minutes=10, seconds=30)
    assert parse_duration("130 min") == timedelta(minutes=130)
    assert parse_duration_range("2h10-2h15") == (timedelta(hours=2, minutes=10), timedelta(hours=2, minutes=15))
    assert parse_duration_range("2h10-15") == (timedelta(hours=2, minutes=10), timedelta(hours=2, minutes=15))
    with pytest.raises(ValueError):
        parse_duration("vite")


def test_half_goal_well_inside_limit_is_green(half):
    verdict = eligibility(
        half,
        RunnerProfile(),
        RunnerSituation(license=LicenseKind.foreign_federation),
        RunnerGoal.parse("2h10-2h15", HALF),
        today=TODAY,
    )
    assert verdict.light is Light.green
    assert verdict.entry_path_id == "license"
    assert {r.code for r in verdict.reasons} >= {"documents", "goal", "goal_gate_10"}


def test_milan_french_runner_without_licence_is_orange_with_human_todo(milan):
    verdict = eligibility(milan, RunnerProfile(), RunnerSituation(), RunnerGoal.parse("3h45-3h55", MARATHON), today=TODAY)
    assert verdict.light is Light.orange
    assert verdict.entry_path_id == "runcard_foreign_resident_abroad"
    assert verdict.alternative_path_id == "sport_tourism"
    certificate = next(r for r in verdict.reasons if r.code == "medical_certificate")
    assert "resting AND post-exercise ECG" in certificate.message
    assert certificate.source_url.startswith("https://indd.adobe.com/")
    assert [todo.kind for todo in verdict.human_todo] == [RequirementKind.runcard, RequirementKind.medical_certificate]
    assert all(not hasattr(todo, "done") for todo in verdict.human_todo)
    assert all(r.level is Light.green for r in verdict.reasons if r.code.startswith("goal"))


def test_milan_with_ffa_licence_and_realistic_goal_is_green(milan):
    situation = RunnerSituation(license=LicenseKind.foreign_federation, license_federation="FFA")
    verdict = eligibility(milan, RunnerProfile(), situation, RunnerGoal.parse("3h45", MARATHON), today=TODAY)
    assert verdict.light is Light.green and verdict.entry_path_id == "foreign_federation_license"


def test_milan_unrealistic_marathon_goals(milan):
    situation = RunnerSituation(has_valid_medical_certificate=True)
    tight = eligibility(milan, RunnerProfile(), situation, RunnerGoal.parse("6h00-6h15", MARATHON), today=TODAY)
    assert tight.light is Light.orange
    too_slow = eligibility(milan, RunnerProfile(), situation, RunnerGoal.parse("6h45", MARATHON), today=TODAY)
    assert too_slow.light is Light.red
    gate = next(r for r in too_slow.reasons if r.code == "goal_gate_21.1")
    assert gate.level is Light.red and "3h15" in gate.message


def test_recent_result_prediction_flags_ambitious_or_impossible_goal(milan):
    situation = RunnerSituation(has_valid_medical_certificate=True)
    recent = RecentResult(distance_km=HALF, time=timedelta(hours=3, minutes=10))
    verdict = eligibility(
        milan, RunnerProfile(), situation, RunnerGoal.parse("5h00", MARATHON, recent_result=recent), today=TODAY
    )
    codes = {r.code: r.level for r in verdict.reasons}
    assert codes["prediction"] is Light.orange or codes["prediction"] is Light.red
    assert codes["ambitious_goal"] is Light.orange


def test_sport_tourism_and_blocking_rules(milan):
    tourist = eligibility(milan, RunnerProfile(), RunnerSituation(wants_competitive=False), today=TODAY)
    assert tourist.entry_path_id == "sport_tourism" and tourist.light is Light.green
    assert [t.kind for t in tourist.human_todo] == [RequirementKind.waiver, RequirementKind.insurance_fee]
    late = eligibility(milan, RunnerProfile(), RunnerSituation(wants_competitive=False), today=date(2027, 4, 1))
    assert late.light is Light.red and late.reasons[0].code == "registration_closed"
    young = eligibility(milan, RunnerProfile(birth_date=date(2008, 6, 1)), RunnerSituation(wants_competitive=False), today=TODAY)
    assert young.light is Light.red


def test_unknown_rules_are_orange_never_green():
    rules = RaceRules(race_name="Course X", race_date=date(2027, 5, 1))
    verdict = eligibility(rules, goal=RunnerGoal.parse("1h00", 10), today=TODAY)
    assert verdict.light is Light.orange
    assert {r.code for r in verdict.reasons} == {"entry_rules_unknown", "time_limit_unknown"}
    assert verdict.human_todo[0].kind is RequirementKind.other


def test_foreign_licence_needs_explicit_acceptance():
    data = {key: value for key, value in LINKUP_HALF.items() if key != "foreign_license_accepted"}
    rules = parse_rules_response("Semi de Test", SimpleNamespace(data=data))
    assert rules.entry_paths[0].licenses == [LicenseKind.host_federation]
    assert rules.entry_paths[1].id == "foreign_license_unconfirmed"
    foreign = RunnerSituation(license=LicenseKind.foreign_federation)
    verdict = eligibility(rules, RunnerProfile(), foreign, today=TODAY)
    assert verdict.light is Light.orange and verdict.entry_path_id == "foreign_license_unconfirmed"
    assert "entry_path_unconfirmed" in {r.code for r in verdict.reasons}
    certificate = Requirement(kind=RequirementKind.medical_certificate, label="Certificat médical")
    unconfirmed = rules.entry_paths[1]
    with_certificate = unconfirmed.model_copy(update={"requirements": [*unconfirmed.requirements, certificate]})
    rules_cert = rules.model_copy(update={"entry_paths": [rules.entry_paths[0], with_certificate]})
    codes = {r.code for r in eligibility(rules_cert, RunnerProfile(), foreign, today=TODAY).reasons}
    assert {"entry_path_unconfirmed", "medical_certificate"} <= codes
    refused = parse_rules_response("Semi de Test", SimpleNamespace(data={**data, "foreign_license_accepted": False}))
    assert [p.id for p in refused.entry_paths] == ["license", "no_license"]


def test_incomplete_rules_without_goal_are_not_green(half):
    rules = half.model_copy(update={"time_limit": None, "missing_fields": ["time_limit"]})
    verdict = eligibility(rules, RunnerProfile(), RunnerSituation(license=LicenseKind.host_federation), today=TODAY)
    assert verdict.light is Light.orange
    assert "rules_incomplete" in {r.code for r in verdict.reasons}


def test_gate_checked_without_time_limit(half):
    rules = half.model_copy(update={"time_limit": None})
    situation = RunnerSituation(license=LicenseKind.host_federation)
    verdict = eligibility(rules, RunnerProfile(), situation, RunnerGoal.parse("2h45", HALF), today=TODAY)
    assert verdict.light is Light.red
    assert {"time_limit_unknown", "goal_gate_10"} <= {r.code for r in verdict.reasons}


def _train(day, depart, arrive, origin="Paris Gare de Lyon", destination="Milano Centrale"):
    return TransportLeg(
        origin=origin,
        destination=destination,
        depart=datetime.combine(day, depart),
        arrive=datetime.combine(day, arrive),
    )


def test_milan_timeline_is_dated_in_race_timezone(milan):
    timeline = build_timeline(
        MILAN,
        milan,
        arrival=_train(date(2027, 4, 3), time(6, 30), time(13, 40)),
        hotel=HotelStay(name="Hôtel fictif", check_in=date(2027, 4, 3), check_out=date(2027, 4, 5)),
        departure=_train(date(2027, 4, 5), time(10, 0), time(17, 0), "Milano Centrale", "Paris Gare de Lyon"),
        goal=RunnerGoal.parse("3h45-3h55", MARATHON),
    )
    assert timeline.ok and not timeline.alerts
    assert timeline.events == sorted(timeline.events, key=lambda e: e.start)
    by_title = {event.title: event for event in timeline.events}
    pickup = by_title["Bib pick-up"]
    assert pickup.start.isoformat() == "2027-04-03T14:10:00+02:00" and not pickup.assumption
    start = by_title["Start Wizz Air Milano Marathon 2027"]
    assert start.start.isoformat() == "2027-04-04T08:15:00+02:00" and start.source_url
    assert by_title["Corral closes (first wave)"].start.time() == time(7, 55)
    assert by_title["Estimated finish"].start.time() == time(12, 10)
    assert "Cut-off km 21.1: 3h15 elapsed race time" in by_title
    assert start.in_timezone("UTC").start.isoformat() == "2027-04-04T06:15:00+00:00"


def test_train_after_bib_pickup_closes_is_blocking(milan):
    timeline = build_timeline(MILAN, milan, arrival=_train(date(2027, 4, 3), time(13, 30), time(20, 40)))
    alert = next(a for a in timeline.alerts if a.code == "bib_pickup_missed")
    assert alert.level is AlertLevel.blocking and not timeline.ok
    assert "19:00" in alert.message and "someone else" in alert.message and "race morning" in alert.message
    assert not any(e.kind == "bib_pickup" for e in timeline.events)


def test_tight_arrival_moves_pickup_and_hotel_alerts(milan):
    timeline = build_timeline(
        MILAN,
        milan,
        arrival=_train(date(2027, 4, 3), time(12, 0), time(18, 20)),
        hotel=HotelStay(name="H", check_in=date(2027, 4, 4), check_out=date(2027, 4, 4)),
        departure=_train(date(2027, 4, 4), time(13, 0), time(20, 0), "Milano Centrale", "Paris"),
        goal=RunnerGoal.parse("4h", MARATHON),
    )
    codes = {a.code: a.level for a in timeline.alerts}
    assert codes == {
        "bib_pickup_missed": AlertLevel.blocking,
        "hotel_nights": AlertLevel.blocking,
        "late_checkout": AlertLevel.warning,
        "return_too_early": AlertLevel.blocking,
    }


def test_race_day_pickup_must_end_before_corrals_close(half):
    race_day = date(2027, 3, 14)
    window = PickupWindow(day=race_day, opens=time(7, 0), closes=time(12, 0))
    rules = half.model_copy(update={"bib_pickup_race_day": True, "bib_pickup_windows": [window]})
    late = build_timeline(None, rules, arrival=_train(race_day, time(6, 0), time(8, 30), destination="Test"))
    assert "bib_pickup_missed" in {a.code for a in late.alerts} and not late.ok
    early = build_timeline(None, rules, arrival=_train(race_day, time(5, 0), time(7, 0), destination="Test"))
    assert "bib_pickup_missed" not in {a.code for a in early.alerts}
    too_late = PickupWindow(day=race_day, opens=time(9, 0), closes=time(12, 0))
    impossible = build_timeline(None, rules.model_copy(update={"bib_pickup_windows": [too_late]}))
    assert "bib_pickup_missed" in {a.code for a in impossible.alerts} and not impossible.ok


def test_timeline_without_logistics_flags_assumptions(half):
    timeline = build_timeline(None, half.model_copy(update={"start_time": None, "bib_pickup_windows": []}))
    codes = {a.code for a in timeline.alerts}
    assert {"bib_pickup_unknown", "start_time_unknown", "pace_assumed"} <= codes
    assert all(e.assumption for e in timeline.events if e.kind in ("bib_pickup", "prep"))
    with pytest.raises(ValueError):
        build_timeline(None, RaceRules(race_name="Sans date"))


def test_ics_export(milan):
    timeline = build_timeline(MILAN, milan, goal=RunnerGoal.parse("3h50", MARATHON))
    ics = to_ics(timeline, now=datetime(2026, 11, 7, 12, 0))
    lines = ics.split("\r\n")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == len(timeline.events)
    assert "DTSTART:20270404T061500Z" in lines
    assert all(len(line.encode()) <= 75 for line in lines)
    assert "SUMMARY:Bib pick-up (estimated)" in lines
    assert ics == to_ics(timeline, now=datetime(2026, 11, 7, 12, 0))


@pytest.mark.skipif(not os.getenv("RUNAI_NETWORK_TESTS"), reason="réseau : RUNAI_NETWORK_TESTS=1 et LINKUP_API_KEY")
def test_linkup_extraction_live(tmp_path):
    rules = extract_rules(MILAN, refresh=True, cache_dir=tmp_path)
    assert rules.origin == "linkup" and rules.race_date == date(2027, 4, 4)
