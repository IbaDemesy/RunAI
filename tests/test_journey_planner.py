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
    assert set(kinds(plan)) == set(kinds(ref))
    actual_chapters, fixture_chapters = chapter_stop_kinds(plan), chapter_stop_kinds(ref)
    for cid in ChapterId:
        if cid is ChapterId.return_trip:
            assert set(fixture_chapters[cid]) <= set(actual_chapters[cid])
            assert "home" in actual_chapters[cid]
        else:
            assert actual_chapters[cid] == fixture_chapters[cid]
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
    assert "Bib pick-up unknown." in plan.warnings


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
    assert bib.local_time is None  # Published opening windows are not a chosen visit appointment.


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


@pytest.mark.parametrize(("raw", "expected"), [
    ("Place Bellecour 69002 Lyon", "Lyon"),
    ("Chemin des Vignes, Lyon", "Lyon"),
    ("Résidence Les Pins bat B, Lyon", "Lyon"),
    ("Via Roma, Milano", "Milano"),
    ("Place de la Bastille, Paris", "Paris"),
    ("Avenida Paulista, Sao Paulo", "Sao Paulo"),
    ("Karl-Marx-Allee, Berlin", "Berlin"),
    ("Main St, Springfield", "Springfield"),
    ("12 rue Victor Hugo 69002 Lyon", "Lyon"),
    ("12 rue de la Roquette 75011 Paris", "Paris"),
    ("Paris 15", "Paris 15"), ("Lyon 3", "Lyon 3"),
    ("Roissy CDG T2", "Roissy CDG T2"),
    ("Saint-Etienne 42", "Saint-Etienne 42"),
    ("Part-Dieu, Lyon", "Lyon"),
    ("Cours Lafayette, Lyon", "Lyon"),
    ("Quai de la Fosse, Nantes", "Nantes"),
    ("Route des Vins, Colmar", "Colmar"),
    ("Viale Europa, Roma", "Roma"),
    ("Alexanderplatz, Berlin", "Berlin"),
    ("Hauptstr., Berlin", "Berlin"),
    ("10 Main Rd, Springfield", "Springfield"),
    ("Av. Paulista, Sao Paulo", "Sao Paulo"),
    ("Impasse des Pins, Lyon", "Lyon"),
])
def test_public_origin_international_streets_and_city_labels(raw, expected):
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
    assert not any("Demo data" in w for w in live.warnings)


@pytest.mark.parametrize("raw", ["12 rue de la Roquette",
                                "Rue de la Roquette", "東京都新宿区西新宿2-8-1"])
def test_unseparated_private_address_is_not_public(raw):
    assert public_origin(raw) == "Origin not specified"


def test_return_is_door_to_door_with_its_own_stops_and_times():
    inputs = train_inputs()
    plan = train_plan()
    segments = {s.id: s for s in plan.segments}
    stops = {s.id: s for s in plan.stops}
    back = segments["s-main-back"]
    assert stops[back.from_stop_id].local_time == inputs.return_trip.depart
    assert stops[back.to_stop_id].local_time == inputs.return_trip.arrive
    assert any(s.from_stop_id == "hotel" and s.to_stop_id == back.from_stop_id for s in plan.segments)
    assert any(s.from_stop_id == back.to_stop_id and s.to_stop_id == "home" for s in plan.segments)
    chapter = next(c for c in plan.chapters if c.id is ChapterId.return_trip)
    assert len(chapter.segment_ids) == 3


@pytest.mark.parametrize("return_mode,expected", [("flight", "flight"), ("bus", "local")])
def test_return_mode_is_not_copied_from_outbound(return_mode, expected):
    inputs = train_inputs()
    inputs.return_trip.mode = return_mode
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    back = next(seg for seg in plan.segments if seg.id == "s-main-back")
    assert back.mode.value == expected
    if return_mode == "bus":
        assert back.limitation.code == "transport_not_covered"
        assert back.automation is not Automation.automated


def test_bib_deadline_is_not_a_visit_appointment():
    inputs = train_inputs()
    inputs.race.bib_pickup_closes = at("Europe/Amsterdam", 2027, 10, 16, 18)
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    assert next(stop for stop in plan.stops if stop.id == "bib").local_time is None
    assert any("2027-10-16T18:00:00+02:00" in warning for warning in plan.warnings)


def test_partial_transport_preserves_the_known_leg_in_total():
    inputs = train_inputs()
    inputs.return_trip.cost = None
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    assert plan.budget.known_total == 95 + 240 + 89
    assert not plan.budget.complete and plan.budget.over_cap is None


def test_duration_is_elapsed_time_across_dst_change():
    inputs = train_inputs()
    inputs.outbound.depart = at("Europe/Paris", 2027, 10, 31, 1, 30)
    inputs.outbound.arrive = at("Europe/Paris", 2027, 10, 31, 3, 30)
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    assert next(seg for seg in plan.segments if seg.id == "s-main-out").duration_min == 180


def test_live_rejects_fixture_rules_even_without_fixture_places():
    inputs = train_inputs(prov=LINKUP)
    inputs.race.rules = RaceRules(race_name="Fixture", origin="fixture", start_time=datetime(2000, 1, 1, 9).time())
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    with pytest.raises(ValueError, match="fixture"):
        build_journey_plan(s, inputs, mission_id="m", mode=DataMode.live)


def test_private_home_details_are_not_reexposed_by_sources_or_geometry():
    inputs = train_inputs()
    inputs.home.provenance = Provenance(kind="human", label="12 rue privée", url="https://maps.example/?q=12-rue-privee", collected_at=AT)
    inputs.outbound.mode = "bus"
    inputs.outbound.geometry = [(3.057312, 50.629234), (4.88, 52.36)]
    inputs.outbound.geometry_verified = True
    inputs.outbound.provenance = LINKUP
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "bus")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    dumped = plan.model_dump_json()
    assert "privée" not in dumped and "privee" not in dumped and "3.057312" not in dumped
    assert next(seg for seg in plan.segments if seg.id == "s-home-hotel").geometry_status is GeometryStatus.illustrative


def test_unknown_start_does_not_invent_a_blocking_nine_oclock_departure():
    inputs = train_inputs()
    inputs.race.start_time = None
    inputs.outbound.arrive = at("Europe/Amsterdam", 2027, 10, 17, 10)
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "train")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    assert next(stop for stop in plan.stops if stop.id == "start").local_time is None
    assert "arrival_after_start" not in {lim.code for lim in plan.limitations}
    assert "Start time to confirm." in plan.warnings


def test_unsupported_outbound_cannot_claim_automation():
    inputs = train_inputs()
    inputs.outbound.mode = "bus"
    inputs.outbound.automation = Automation.automated
    s = summary("Amsterdam", "NL", date(2027, 10, 17), "Lille", "bus")
    plan = build_journey_plan(s, inputs, mission_id="m", mode=DataMode.demo)
    segment = next(seg for seg in plan.segments if seg.id == "s-home-hotel")
    assert segment.automation is Automation.manual
    assert segment.limitation.code == "transport_not_covered"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Paris, France", "Paris"), ("12 rue de la Paix, 75002 Paris, France", "Paris")],
)
def test_public_origin_keeps_city_before_country(raw, expected):
    assert public_origin(raw) == expected
