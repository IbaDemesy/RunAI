from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from runai.contracts import load_fixture
from runai.contracts.common import Automation, DataMode, Provenance, ProvenanceKind
from runai.contracts.framing import FramingSummary
from runai.contracts.journey import (
    ChapterId,
    Coords,
    GeometryStatus,
    JourneyPlan,
    Money,
)
from runai.journey import (
    HotelChoice,
    JourneyInputs,
    Place,
    RaceDetails,
    TransportChoice,
    build_journey_plan,
    public_origin,
)
from runai.logistics.models import PickupWindow, RaceRules
from runai.models import Race

AT = datetime(2026, 11, 7, 12, tzinfo=ZoneInfo("UTC"))
FIX = Provenance(kind=ProvenanceKind.fixture, label="test", collected_at=AT)
LINKUP = Provenance(kind=ProvenanceKind.linkup, url="https://example.org/src", collected_at=AT)


def money(amount, prov=FIX, currency="EUR"):
    return Money(amount=amount, currency=currency, collected_at=AT, provenance=prov)


def summary(city, country, day, origin, mode, nights=2, budget=600.0, distance=42.195, revision=4):
    return FramingSummary(
        revision=revision,
        race=Race(name=f"Course de {city}", city=city, country=country, race_date=day, distance_km=distance),
        origin_public=origin,
        date_range=(day - timedelta(days=1), day - timedelta(days=1) + timedelta(days=nights)),
        nights=nights,
        budget_eur=budget,
        transport_mode=mode,
        lines=[],
    )


def place(label, lat, lon, tz, prov=FIX):
    return Place(label=label, coords=Coords(lat=lat, lon=lon), timezone=tz, provenance=prov)


def at(tz, *args):
    return datetime(*args, tzinfo=ZoneInfo(tz))


def train_inputs(arrive_hour=11, prov=FIX):
    ams = "Europe/Amsterdam"
    out_hub, in_hub = place("Lille Europe", 50.639, 3.0756, "Europe/Paris", prov), place("Amsterdam C", 52.3791, 4.9003, ams, prov)
    return JourneyInputs(
        home=Place(label="Lille", coords=Coords(lat=50.629234, lon=3.057312), timezone="Europe/Paris"),
        outbound=TransportChoice(mode="train", from_hub=out_hub, to_hub=in_hub,
                                 depart=at("Europe/Paris", 2027, 10, 16, 9), arrive=at(ams, 2027, 10, 16, arrive_hour, 40),
                                 cost=money(89, prov), manual_url="https://example.org/train"),
        return_trip=TransportChoice(mode="train", from_hub=in_hub, to_hub=out_hub,
                                    depart=at(ams, 2027, 10, 18, 10), arrive=at("Europe/Paris", 2027, 10, 18, 12, 40),
                                    cost=money(79, prov)),
        hotel=HotelChoice(place=place("Hôtel", 52.36, 4.88, ams, prov), check_in=date(2027, 10, 16),
                          check_out=date(2027, 10, 18), cost=money(240, prov), minutes_to_start=35),
        race=RaceDetails(start=place("Stade", 52.3433, 4.8536, ams, prov), bib_pickup=place("Expo", 52.343, 4.854, ams, prov),
                         start_time=at(ams, 2027, 10, 17, 9, 30), registration_cost=money(95, prov),
                         finish=place("Stade", 52.3433, 4.8536, ams, prov)),
    )


def train_plan(**kw):
    return build_journey_plan(summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train"), train_inputs(**kw),
                              mission_id="m-train", mode=DataMode.demo)


def flight_plan():
    lis, par = "Europe/Lisbon", "Europe/Paris"
    out_hub, in_hub = place("ORY", 48.7262, 2.3652, par), place("LIS", 38.7742, -9.1342, lis)
    inputs = JourneyInputs(
        home=Place(label="Paris 11e", coords=Coords(lat=48.859, lon=2.38), timezone=par),
        outbound=TransportChoice(mode="avion", from_hub=out_hub, to_hub=in_hub, automation=Automation.automated,
                                 depart=at(par, 2027, 3, 20, 8, 10), arrive=at(lis, 2027, 3, 20, 9, 55), cost=money(142)),
        return_trip=TransportChoice(mode="flight", from_hub=in_hub, to_hub=out_hub, automation=Automation.automated,
                                    depart=at(lis, 2027, 3, 22, 15), arrive=at(par, 2027, 3, 22, 18, 30), cost=money(128)),
        hotel=HotelChoice(place=place("Hôtel", 38.7223, -9.1393, lis), check_in=date(2027, 3, 20),
                          check_out=date(2027, 3, 22), cost=money(210)),
        race=RaceDetails(start=place("Belém", 38.697, -9.206, lis), bib_pickup=place("Expo", 38.768, -9.094, lis), finish=place("Praça", 38.7075, -9.1365, lis),
                         start_time=at(lis, 2027, 3, 21, 8, 30), registration_cost=money(60)),
    )
    s = summary("Lisboa", "PT", date(2027, 3, 21), "12 rue de la Roquette, 75011 Paris", "flight", budget=None)
    return build_journey_plan(s, inputs, mission_id="m-flight", mode=DataMode.demo)


def incomplete_plan():
    chi = "America/Chicago"
    inputs = JourneyInputs(
        home=Place(label="Lyon", coords=Coords(lat=45.764, lon=4.8357), timezone="Europe/Paris"),
        race=RaceDetails(start=place("Grant Park", 41.8756, -87.62, chi), start_time=at(chi, 2027, 10, 10, 7, 30),
                         registration_cost=money(250)),
    )
    s = summary("Chicago", "US", date(2027, 10, 10), "Lyon", "flight", nights=4, budget=2000.0)
    return build_journey_plan(s, inputs, mission_id="m-inc", mode=DataMode.demo)


def kinds(plan):
    return [s.kind.value for s in plan.stops]


def chapter_stop_kinds(plan):
    by_id = {s.id: s.kind.value for s in plan.stops}
    return {c.id: sorted(by_id[s] for s in c.stop_ids) for c in plan.chapters}


@pytest.mark.parametrize(("build", "fixture"), [(train_plan, "journey_train.json"), (flight_plan, "journey_flight.json")])
def test_reproduces_fixture_structure(build, fixture):
    plan, ref = build(), JourneyPlan.model_validate(load_fixture(fixture))
    JourneyPlan.model_validate(plan.model_dump(mode="json"))
    assert [c.id for c in plan.chapters] == list(ChapterId)
    assert sorted(kinds(plan)) == sorted(kinds(ref))
    assert chapter_stop_kinds(plan) == chapter_stop_kinds(ref)
    assert {s.mode for s in plan.segments} - {s.mode for s in ref.segments} == set()
    assert plan.timezone == ref.timezone
    assert plan.budget.complete is False  # transports locaux non estimés
    ref_known = sum(line.money.amount for line in ref.budget.lines if line.money)
    assert plan.budget.known_total == ref_known


def test_incomplete_structure_unknown_stays_none():
    plan, ref = incomplete_plan(), JourneyPlan.model_validate(load_fixture("journey_incomplete.json"))
    assert plan.timezone == "America/Chicago" == ref.timezone
    assert set(kinds(ref)) <= set(kinds(plan)) | {"race_finish"}
    stops = {s.id: s for s in plan.stops}
    assert stops["hub-out"].coords is None and stops["hub-in"].coords is None and stops["hotel"].coords is None
    assert stops["hub-out"].kind.value == "airport" and stops["hub-in"].local_time is None
    main = next(s for s in plan.segments if s.id == "s-main-out")
    assert main.geometry_status is GeometryStatus.unavailable and main.departure is None
    assert {c.id: c.status for c in plan.chapters}[ChapterId.main_transport] == "unavailable"
    assert plan.budget.known_total == 250 and plan.budget.over_cap is None
    assert {"c-hotel", "c-transport"} <= set(plan.budget.missing_line_ids)
    assert "transport_not_covered" in {lim.code for lim in plan.limitations}
    assert "Retrait des dossards inconnu." in plan.warnings


def test_iana_timezones_on_stops():
    plan = flight_plan()
    for stop in plan.stops:
        if stop.local_time:
            assert stop.local_time.utcoffset() == stop.local_time.astimezone(ZoneInfo(stop.timezone)).utcoffset()
    stops = {s.id: s for s in plan.stops}
    assert stops["hub-out"].local_time.utcoffset() == timedelta(hours=1)
    assert stops["hub-in"].local_time.utcoffset() == timedelta(0)
    assert stops["start"].local_time == at("Europe/Lisbon", 2027, 3, 21, 8, 30)
    with pytest.raises(ValidationError):
        Place(label="x", timezone="Europe/Atlantis")
    with pytest.raises(ValidationError):
        TransportChoice(mode="train", depart=datetime(2027, 1, 1, 9))


def test_flight_duration_across_timezones():
    seg = next(s for s in flight_plan().segments if s.id == "s-main-out")
    assert seg.duration_min == 165 and seg.timezone == "Europe/Paris"
    assert seg.geometry_status is GeometryStatus.illustrative and seg.automation is Automation.automated


def test_arrival_after_start_and_bib_missed_are_flagged():
    inputs = train_inputs()
    ams = "Europe/Amsterdam"
    late = inputs.outbound.model_copy(update={"arrive": at(ams, 2027, 10, 17, 10)})
    rules = RaceRules(race_name="Course", race_date=date(2027, 10, 17), timezone=ams, origin="fixture",
                      bib_pickup_windows=[PickupWindow(day=date(2027, 10, 16), opens=datetime(2000, 1, 1, 10).time(),
                                                       closes=datetime(2000, 1, 1, 18).time())],
                      bib_pickup_race_day=False)
    race = inputs.race.model_copy(update={"rules": rules})
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs.model_copy(update={"outbound": late, "race": race}), mission_id="m", mode=DataMode.demo)
    codes = {lim.code for lim in plan.limitations}
    assert {"arrival_after_start", "bib_pickup_missed"} <= codes
    ok = build_journey_plan(s, inputs.model_copy(update={"race": race}), mission_id="m", mode=DataMode.demo)
    assert not {"arrival_after_start", "bib_pickup_missed"} & {lim.code for lim in ok.limitations}
    bib = next(st for st in ok.stops if st.id == "bib")
    assert bib.local_time.date() == date(2027, 10, 16)


def test_bib_closing_time_without_rules():
    inputs = train_inputs(arrive_hour=17)
    race = inputs.race.model_copy(update={"bib_pickup_closes": at("Europe/Amsterdam", 2027, 10, 16, 18)})
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs.model_copy(update={"race": race}), mission_id="m", mode=DataMode.demo)
    assert "bib_pickup_unreachable" in {lim.code for lim in plan.limitations}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("12 rue de la Roquette, 75011 Paris", "Paris"), ("Paris 11e", "Paris 11e"),
     ("221B Baker Street, London NW1 6XE", "London"), ("Lyon", "Lyon"), ("1600 Pennsylvania Ave, Washington", "Washington")],
)
def test_public_origin_never_keeps_street_address(raw, expected):
    assert public_origin(raw) == expected


def test_exact_address_absent_from_plan():
    plan = flight_plan()
    dumped = plan.model_dump_json()
    assert plan.origin_public == "Paris" and "Roquette" not in dumped and "75011" not in dumped
    home = next(s for s in plan.stops if s.id == "home")
    assert home.label == "Paris" and home.coords == Coords(lat=48.86, lon=2.38)


def test_unsourced_link_is_illustrative_and_sourced_is_verified():
    inputs = train_inputs()
    track = [(4.8536, 52.3433), (4.9, 52.37), (4.8536, 52.3433)]
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    out = inputs.outbound.model_copy(update={"geometry": [(3.07, 50.6), (4.9, 52.4)], "provenance": None})
    plan = build_journey_plan(s, inputs.model_copy(update={"outbound": out}), mission_id="m", mode=DataMode.demo)
    segs = {seg.id: seg for seg in plan.segments}
    assert segs["s-main-out"].geometry_status is GeometryStatus.illustrative
    assert segs["s-race"].geometry_status is GeometryStatus.unavailable
    assert "race_track_unavailable" in {lim.code for lim in plan.limitations}
    race = inputs.race.model_copy(update={"track": track, "track_provenance": FIX})
    plan2 = build_journey_plan(s, inputs.model_copy(update={"race": race}), mission_id="m", mode=DataMode.demo)
    assert {seg.id: seg for seg in plan2.segments}["s-race"].geometry_status is GeometryStatus.verified


def test_uncovered_transport_is_explicit_limitation_not_refusal():
    tyo = "Asia/Tokyo"
    inputs = JourneyInputs(
        home=Place(label="Osaka", coords=Coords(lat=34.69, lon=135.5), timezone=tyo),
        outbound=TransportChoice(mode="bus", manual_url="https://example.org/bus"),
        hotel=HotelChoice(place=place("Hôtel", 35.68, 139.76, tyo), check_in=date(2027, 4, 17), check_out=date(2027, 4, 18)),
        race=RaceDetails(start=place("Shinjuku", 35.69, 139.69, tyo), start_time=at(tyo, 2027, 4, 18, 9)),
    )
    s = summary("Tokyo", "JP", date(2027, 4, 18), "Osaka", "bus", nights=1)
    plan = build_journey_plan(s, inputs, mission_id="m-tyo", mode=DataMode.demo)
    lim = next(lim for lim in plan.limitations if lim.code == "transport_not_covered")
    assert str(lim.manual_url) == "https://example.org/bus"
    seg = next(seg for seg in plan.segments if seg.id == "s-home-hotel")
    assert seg.automation is Automation.manual and seg.mode.value == "local"
    chapters = {c.id: c.status for c in plan.chapters}
    assert chapters[ChapterId.departure_hub] == "unavailable" and chapters[ChapterId.race] in {"available", "partial"}
    assert plan.timezone == tyo


def test_revision_bumps_only_on_change():
    first = train_plan()
    assert first.revision == 0
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    same = build_journey_plan(s, train_inputs(), mission_id="m-train", mode=DataMode.demo, previous=first)
    assert same.revision == 0
    changed = build_journey_plan(s, train_inputs(arrive_hour=12), mission_id="m-train", mode=DataMode.demo, previous=same)
    assert changed.revision == 1
    again = build_journey_plan(s, train_inputs(), mission_id="m-train", mode=DataMode.demo, previous=changed)
    assert again.revision == 2


def test_budget_over_cap_and_currency():
    plan = train_plan()
    assert plan.budget.cap == 600 and plan.budget.known_total == 503 and plan.budget.over_cap is None
    inputs = train_inputs()
    hotel = inputs.hotel.model_copy(update={"cost": money(900, currency="USD")})
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train", budget=200.0)
    plan2 = build_journey_plan(s, inputs.model_copy(update={"hotel": hotel}), mission_id="m", mode=DataMode.demo)
    line = next(line for line in plan2.budget.lines if line.id == "c-hotel")
    assert line.money is None and "USD" in line.note
    assert plan2.budget.over_cap is True


def test_live_plan_rejects_fixture_data_and_keeps_sources():
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    with pytest.raises(ValueError, match="live"):
        build_journey_plan(s, train_inputs(), mission_id="m", mode=DataMode.live)
    live = build_journey_plan(s, train_inputs(prov=LINKUP), mission_id="m", mode=DataMode.live)
    assert live.sources == [LINKUP]
    assert not any("démonstration" in w for w in live.warnings)
