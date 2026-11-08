"""Door-to-door planner: FramingSummary and step results to JourneyPlan v1.

Unknown coordinates and times remain None. Links without sourced geometry are
`illustrative` (straight lines between known points) or `unavailable`. Timing checks
reuse `logistics.build_timeline`; its alerts become plan warnings and limitations."""

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, HttpUrl, field_validator

from runai.contracts.common import (
    Automation,
    Confidence,
    DataMode,
    Limitation,
    Provenance,
    ProvenanceKind,
)
from runai.contracts.framing import FramingSummary
from runai.contracts.journey import (
    Budget,
    Chapter,
    ChapterId,
    Coords,
    CostCategory,
    CostLine,
    GeometryStatus,
    JourneyPlan,
    JourneySegment,
    JourneyStop,
    Money,
    SegmentMode,
    StopKind,
)
from runai.logistics.models import (
    AlertLevel,
    HotelStay,
    RaceRules,
    Timeline,
    TransportLeg,
)
from runai.logistics.timeline import build_timeline

PARTIAL_BUDGET_WARNING = "Partial budget: unpriced items excluded from the total."
COVERED_MODES = {"train": SegmentMode.train, "flight": SegmentMode.flight}
MODE_ALIASES = {"avion": "flight", "plane": "flight", "vol": "flight", "air": "flight", "rail": "train"}
HUB_KIND = {SegmentMode.train: StopKind.station, SegmentMode.flight: StopKind.airport}
HUB_LABEL = {SegmentMode.train: ("Station", "Train"), SegmentMode.flight: ("Airport", "Flight")}
CHAPTER_LABELS = {
    ChapterId.home: "Home",
    ChapterId.arrival_hotel: "Arrival and hotel",
    ChapterId.bib_pickup: "Bib pick-up",
    ChapterId.race: "Start and race",
    ChapterId.return_trip: "Return",
}
HOTEL_FAR_MIN = 60
DEFAULT_TRANSFER = timedelta(minutes=45)
PUBLIC_COORD_DECIMALS = 2
_STREET_NUMBER = re.compile(r"^\s*\d{1,5}\s*(bis|ter|[a-z])?\b[\s,]+\D{2,}", re.IGNORECASE)
_POSTCODE = re.compile(r"\b\d{5}\b|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
_STREET_WORD = re.compile(r"\b(rue|avenue|ave|boulevard|street|road|lane|strasse|straße|calle|rua)\b", re.IGNORECASE)


class Place(BaseModel):
    """Place provided by a step or a human. Home must be public (city or neighborhood)."""

    label: str
    coords: Coords | None = None
    timezone: str | None = None
    provenance: Provenance | None = None
    confidence: Confidence = Confidence.unknown

    @field_validator("timezone")
    @classmethod
    def _iana(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.utcoffset() is None:
        raise ValueError("time without timezone: provide a datetime with an offset")
    return value


class TransportChoice(BaseModel):
    mode: str
    from_hub: Place | None = None
    to_hub: Place | None = None
    depart: datetime | None = None
    arrive: datetime | None = None
    cost: Money | None = None
    automation: Automation = Automation.manual
    manual_url: HttpUrl | None = None
    geometry: list[tuple[float, float]] | None = None
    geometry_verified: bool = False
    provenance: Provenance | None = None
    reference: str | None = None

    @field_validator("depart", "arrive")
    @classmethod
    def _times(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class HotelChoice(BaseModel):
    place: Place
    check_in: date
    check_out: date
    check_in_from: time | None = time(15, 0)
    check_out_until: time | None = time(11, 0)
    cost: Money | None = None
    minutes_to_start: int | None = None
    minutes_to_bib_pickup: int | None = None
    automation: Automation = Automation.manual
    manual_url: HttpUrl | None = None


class RaceDetails(BaseModel):
    start: Place | None = None
    finish: Place | None = None
    bib_pickup: Place | None = None
    start_time: datetime | None = None
    bib_pickup_closes: datetime | None = None
    bib_pickup_time: datetime | None = None
    track: list[tuple[float, float]] | None = None
    track_provenance: Provenance | None = None
    registration_cost: Money | None = None
    registration_url: HttpUrl | None = None
    rules: RaceRules | None = None

    @field_validator("start_time", "bib_pickup_closes", "bib_pickup_time")
    @classmethod
    def _times(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class JourneyInputs(BaseModel):
    home: Place
    outbound: TransportChoice | None = None
    return_trip: TransportChoice | None = None
    hotel: HotelChoice | None = None
    race: RaceDetails = Field(default_factory=RaceDetails)
    local_cost: Money | None = None


def public_origin(text: str) -> str:
    """City or neighborhood only: remove street numbers and postcodes from an address."""
    street_word = re.compile(
        r"\b(?:rue|avenue|ave|av|boulevard|bd|street|st|road|rd|lane|drive|"
        r"strasse|straße|calle|rua|place|chemin|impasse|cours|résidence|residence|"
        r"via|viale|quai|route|platz|allee|allée|str|avenida|paseo|camino|estrada)\b"
        r"|\b\w*(?:platz|allee|straße|strasse|str\.)",
        re.IGNORECASE,
    )
    parts = re.split(r"[,;\n]|\b\d{5}\b", text)
    cleaned = []
    for part in parts:
        value = " ".join(_POSTCODE.sub(" ", part).split())
        if not value or _STREET_NUMBER.match(value) or street_word.search(value):
            continue
        if re.search(r"\d", value) and not re.fullmatch(
            r"[^\d]+\s(?:\d{1,2}(?:e|er|ème|th|st|nd|rd)?|T\d{1,2})", value,
            re.IGNORECASE,
        ):
            continue
        cleaned.append(value)
    return cleaned[-1] if cleaned else "Origin not specified"


def normalize_mode(mode: str | None) -> str | None:
    if not mode:
        return None
    value = mode.strip().lower()
    return MODE_ALIASES.get(value, value)


def race_timezone(summary: FramingSummary, inputs: JourneyInputs) -> str | None:
    rules = inputs.race.rules
    if inputs.race.start and inputs.race.start.timezone:
        return inputs.race.start.timezone
    if rules and "timezone" in rules.field_sources:
        return rules.timezone
    for place in (inputs.hotel.place if inputs.hotel else None, inputs.outbound.to_hub if inputs.outbound else None):
        if place and place.timezone:
            return place.timezone
    return None


def journey_timeline(summary: FramingSummary, inputs: JourneyInputs) -> Timeline | None:
    """Trip logistics timeline; None if the race date or timezone is unknown."""
    tz = race_timezone(summary, inputs)
    race = summary.race
    rules = inputs.race.rules
    race_date = (rules.race_date if rules else None) or race.race_date
    if tz is None or race_date is None:
        return None
    start_local = inputs.race.start_time.astimezone(ZoneInfo(tz)) if inputs.race.start_time else None
    if rules is None:
        rules = RaceRules(
            race_name=race.name,
            race_date=race_date,
            distance_km=race.distance_km,
            timezone=tz,
            start_time=start_local.time().replace(tzinfo=None) if start_local else None,
            start_location=inputs.race.start.label if inputs.race.start else None,
        )
    else:
        update = {"timezone": tz}
        if start_local and rules.start_time is None:
            update["start_time"] = start_local.time().replace(tzinfo=None)
        rules = rules.model_copy(update=update)
    hotel = None
    if inputs.hotel:
        h = inputs.hotel
        hotel = HotelStay(
            name=h.place.label,
            check_in=h.check_in,
            check_out=h.check_out,
            check_in_from=h.check_in_from,
            check_out_until=h.check_out_until,
            **{k: v for k, v in {"minutes_to_start": h.minutes_to_start,
                                 "minutes_to_bib_pickup": h.minutes_to_bib_pickup}.items() if v is not None},
        )
    return build_timeline(
        race,
        rules,
        arrival=_leg(inputs.outbound),
        hotel=hotel,
        departure=_leg(inputs.return_trip),
    )


def _leg(choice: TransportChoice | None) -> TransportLeg | None:
    if not choice or choice.depart is None or choice.arrive is None:
        return None
    mode = normalize_mode(choice.mode)
    return TransportLeg(
        mode=mode if mode in {"train", "flight", "bus", "car"} else "other",
        origin=choice.from_hub.label if choice.from_hub else "Start",
        destination=choice.to_hub.label if choice.to_hub else "Arrival",
        depart=choice.depart,
        arrive=choice.arrive,
        reference=choice.reference,
    )


class _Builder:
    def __init__(self, tz: str):
        self.tz = tz
        self.stops: dict[str, JourneyStop] = {}
        self.segments: dict[str, JourneySegment] = {}
        self.limitations: list[Limitation] = []
        self.warnings: list[str] = []

    def stop(self, sid: str, kind: StopKind, place: Place | None, label: str, when: datetime | None = None,
             tz: str | None = None) -> str:
        zone = (place.timezone if place else None) or tz
        self.stops[sid] = JourneyStop(
            id=sid,
            kind=kind,
            label=place.label if place else label,
            coords=place.coords if place else None,
            local_time=when.astimezone(ZoneInfo(zone)) if when and zone else when,
            timezone=zone,
            provenance=place.provenance if place else None,
            confidence=place.confidence if place else Confidence.unknown,
        )
        return sid

    def segment(self, sid: str, a: str, b: str, mode: SegmentMode, *, choice: TransportChoice | None = None,
                geometry: list[tuple[float, float]] | None = None, provenance: Provenance | None = None,
                verified: bool = False, duration_min: int | None = None, cost: Money | None = None,
                limitation: Limitation | None = None) -> str:
        if choice is not None:
            geometry, provenance, verified = choice.geometry, choice.provenance, choice.geometry_verified
        if StopKind.home in (self.stops[a].kind, self.stops[b].kind):
            geometry, provenance, verified = None, None, False
        status, line = _geometry(geometry, provenance, verified, self.stops[a].coords, self.stops[b].coords)
        if mode is SegmentMode.race and status is GeometryStatus.illustrative:
            status, line = GeometryStatus.unavailable, None
        depart = choice.depart if choice else None
        arrive = choice.arrive if choice else None
        if depart and arrive:
            duration_min = int((arrive.astimezone(UTC) - depart.astimezone(UTC)).total_seconds() // 60)
        self.segments[sid] = JourneySegment(
            id=sid,
            from_stop_id=a,
            to_stop_id=b,
            mode=mode,
            departure=depart,
            arrival=arrive,
            timezone=self.stops[a].timezone if depart else None,
            geometry=line,
            geometry_status=status,
            duration_min=duration_min,
            cost=cost,
            automation=choice.automation if choice else Automation.not_covered,
            manual_url=str(choice.manual_url) if choice and choice.manual_url else None,
            provenance=provenance,
            limitation=limitation,
        )
        if limitation:
            self.limitations.append(limitation)
        return sid


def _geometry(geometry, provenance, verified, a: Coords | None, b: Coords | None):
    if geometry and len(geometry) >= 2:
        if provenance is None:
            return GeometryStatus.illustrative, geometry
        trusted = provenance.kind in {ProvenanceKind.official_api, ProvenanceKind.human, ProvenanceKind.linkup}
        return (GeometryStatus.verified if verified and trusted and provenance.url else GeometryStatus.approximate), geometry
    if a and b:
        return GeometryStatus.illustrative, [(a.lon, a.lat), (b.lon, b.lat)]
    return GeometryStatus.unavailable, None


def _public_home(home: Place, label: str) -> Place:
    coords = None
    if home.coords:
        coords = Coords(lat=round(home.coords.lat, PUBLIC_COORD_DECIMALS), lon=round(home.coords.lon, PUBLIC_COORD_DECIMALS))
    confidence = home.confidence if home.confidence is not Confidence.verified else Confidence.estimated
    provenance = home.provenance.model_copy(update={"label": "Public origin", "url": None}) if home.provenance else None
    return home.model_copy(update={"label": label, "coords": coords, "confidence": confidence, "provenance": provenance})


def _same_currency(money: Money | None, currency: str) -> Money | None:
    return money if money and money.currency == currency else None


def _line(lid: str, category: CostCategory, label: str, money: Money | None, currency: str,
          missing_note: str) -> CostLine:
    usable = _same_currency(money, currency)
    note = None
    if money and usable is None:
        note = f"Amount in {money.currency} not converted"
    elif usable is None:
        note = missing_note
    return CostLine(id=lid, category=category, label=label, money=usable, note=note)


def _transport_cost(legs: list[TransportChoice | None], currency: str) -> Money | None:
    costs = [_same_currency(leg.cost, currency) if leg else None for leg in legs]
    if not legs or any(c is None for c in costs):
        return None
    return Money(
        amount=round(sum(c.amount for c in costs), 2),
        currency=currency,
        collected_at=max(c.collected_at for c in costs),
        confidence=Confidence.estimated,
        provenance=Provenance(kind=ProvenanceKind.derived, label="Sum of legs",
                              collected_at=max(c.collected_at for c in costs)),
    )


def _transport_lines(legs: list[TransportChoice | None], currency: str, covered: bool) -> list[CostLine]:
    total = _transport_cost(legs, currency)
    if total or not any(leg and _same_currency(leg.cost, currency) for leg in legs):
        return [_line("c-transport", CostCategory.transport, "Transport", total, currency,
                      "Leg price unknown" if covered else "Not covered")]
    return [_line(f"c-transport-{name}", CostCategory.transport, f"Transport {label}", leg.cost if leg else None,
                  currency, "Leg price unknown")
            for name, label, leg in zip(("out", "back"), ("outbound", "return"), legs, strict=True)]


def _chapter(cid: ChapterId, label: str, stops: list[str | None], segments: list[str | None],
             b: _Builder) -> Chapter:
    stop_ids = [s for s in stops if s]
    seg_ids = [s for s in segments if s]
    located = [b.stops[s].coords is not None for s in stop_ids]
    drawn = [b.segments[s].geometry_status is not GeometryStatus.unavailable for s in seg_ids]
    flags = located + drawn
    if not flags or not any(flags):
        status = "unavailable"
    elif all(flags):
        status = "available"
    else:
        status = "partial"
    return Chapter(id=cid, label=label, stop_ids=stop_ids, segment_ids=seg_ids, status=status)


def _provenances(plan: JourneyPlan) -> list[Provenance]:
    seen: list[Provenance] = []
    items = [s.provenance for s in plan.stops] + [s.provenance for s in plan.segments]
    items += [s.cost.provenance for s in plan.segments if s.cost]
    items += [line.money.provenance for line in plan.budget.lines if line.money]
    for prov in items:
        if prov and prov.kind is not ProvenanceKind.derived and prov not in seen:
            seen.append(prov)
    return seen


def _check_mode(mode: DataMode, sources: list[Provenance]) -> None:
    kinds = {p.kind for p in sources}
    if mode is DataMode.live and kinds & {ProvenanceKind.fixture, ProvenanceKind.replay}:
        raise ValueError("live plan contains fixture/replay data")
    if mode is DataMode.replay and ProvenanceKind.fixture in kinds:
        raise ValueError("replay plan contains fixture data")


def build_journey_plan(
    summary: FramingSummary,
    inputs: JourneyInputs,
    *,
    mission_id: str,
    mode: DataMode,
    previous: JourneyPlan | None = None,
    currency: str = "EUR",
) -> JourneyPlan:
    """Build JourneyPlan; increment previous.revision only if a choice changed."""
    if mode is not DataMode.demo and inputs.race.rules and inputs.race.rules.origin == "fixture":
        raise ValueError(f"{mode.value} plan contains fixture rules")
    tz = race_timezone(summary, inputs)
    b = _Builder(tz or "UTC")
    if tz is None:
        b.limitations.append(Limitation(code="race_timezone_unknown",
                                        message="Race timezone unknown: times shown without local conversion."))
    origin = public_origin(summary.origin_public)
    home = b.stop("home", StopKind.home, _public_home(inputs.home, origin), origin)
    mode_name = normalize_mode(inputs.outbound.mode if inputs.outbound else summary.transport_mode)
    main_mode = COVERED_MODES.get(mode_name or "")
    race_in = inputs.race

    hotel_place = inputs.hotel.place if inputs.hotel else None
    hotel = b.stop("hotel", StopKind.hotel, hotel_place, "Hotel not selected", tz=tz)
    if hotel_place is None:
        b.warnings.append("Hotel not selected.")
    elif inputs.hotel.minutes_to_start and inputs.hotel.minutes_to_start > HOTEL_FAR_MIN:
        b.warnings.append(f"Hotel {inputs.hotel.minutes_to_start} min from the start: check your morning journey.")

    hub_out = hub_in = out_seg = back_seg = arrival_seg = home_seg = None
    return_stops: list[str | None] = []
    return_segments: list[str | None] = []
    hub_label = "Transport"
    if main_mode:
        hub_label, main_label = HUB_LABEL[main_mode]
        kind = HUB_KIND[main_mode]
        out = inputs.outbound
        hub_out = b.stop("hub-out", kind, out.from_hub if out else None, f"Departure {hub_label} to select",
                         out.depart if out else None, tz=inputs.home.timezone)
        hub_in = b.stop("hub-in", kind, out.to_hub if out else None, f"Arrival {hub_label} to select",
                        out.arrive if out else None, tz=tz)
        home_seg = b.segment("s-home-hub", home, hub_out, SegmentMode.local)
        limitation = None
        if out is None or out.automation is not Automation.automated:
            url = out.manual_url if out else None
            limitation = Limitation(
                code="transport_manual" if out else "transport_not_covered",
                message=(f"{main_label} not automated: check and book yourself via the official link."
                         if out else f"{main_label} not found: search and book yourself."),
                step="transport",
                manual_url=url,
            )
        out_seg = b.segment("s-main-out", hub_out, hub_in, main_mode, choice=out, cost=out.cost if out else None,
                            limitation=limitation)
        arrival_seg = b.segment("s-hub-hotel", hub_in, hotel, SegmentMode.local)
    else:
        label = summary.transport_mode or "unknown"
        out = inputs.outbound
        url = out.manual_url if out else None
        home_seg = b.segment(
            "s-home-hotel", home, hotel, SegmentMode.local, choice=out,
            limitation=Limitation(
                code="transport_not_covered",
                message=f"Transport '{label}' not covered: arrange your journey yourself.",
                step="transport",
                manual_url=url,
            ),
        )
        b.segments[home_seg].automation = Automation.manual if url else Automation.not_covered

    back = inputs.return_trip
    back_mode = COVERED_MODES.get(normalize_mode(back.mode)) if back else main_mode
    if back_mode:
        kind = HUB_KIND[back_mode]
        back_from = b.stop("hub-back-from", kind, back.from_hub if back else None,
                           "Return departure to select", back.depart if back else None, tz=tz)
        back_to = b.stop("hub-back-to", kind, back.to_hub if back else None,
                         "Return arrival to select", back.arrive if back else None, tz=inputs.home.timezone)
        back_limitation = None
        if back is None or back.automation is not Automation.automated:
            back_limitation = Limitation(code="return_not_found" if back is None else "transport_manual",
                                         message="Return not found." if back is None else "Return not automated: check the official link.",
                                         step="transport", manual_url=back.manual_url if back else None)
        back_seg = b.segment("s-main-back", back_from, back_to, back_mode, choice=back,
                             cost=back.cost if back else None, limitation=back_limitation)
        return_segments = [b.segment("s-hotel-return-hub", hotel, back_from, SegmentMode.local), back_seg,
                           b.segment("s-return-hub-home", back_to, home, SegmentMode.local)]
        return_stops = [back_from, back_to, home]
    else:
        back_seg = b.segment("s-main-back", hotel, home, SegmentMode.local, choice=back,
                             cost=back.cost if back else None, limitation=Limitation(
                                 code="transport_not_covered", step="transport",
                                 message=f"Return transport '{back.mode if back else 'unknown'}' not covered: arrange it yourself.",
                                 manual_url=back.manual_url if back else None))
        b.segments[back_seg].automation = Automation.manual if back and back.manual_url else Automation.not_covered
        return_segments, return_stops = [back_seg], [home]

    timeline = journey_timeline(summary, inputs)
    bib_when = race_in.bib_pickup_time
    if race_in.bib_pickup_closes:
        b.warnings.append(f"Bib pick-up closes: {race_in.bib_pickup_closes.isoformat()} (not an appointment).")
    start_when = race_in.start_time
    if timeline:
        for event in timeline.events:
            if event.kind == "race" and event.title.startswith("Start") and not event.assumption and start_when is None:
                start_when = event.start

    bib = None
    bib_seg = None
    if race_in.bib_pickup or bib_when or race_in.bib_pickup_closes:
        bib = b.stop("bib", StopKind.bib_pickup, race_in.bib_pickup, "Bib pick-up", bib_when, tz=tz)
        bib_seg = b.segment("s-hotel-bib", hotel, bib, SegmentMode.local,
                            duration_min=inputs.hotel.minutes_to_bib_pickup if inputs.hotel else None)
        if bib_when is None:
            b.warnings.append("Choose your bib pick-up time; closing time is not an appointment.")
    else:
        b.warnings.append("Bib pick-up unknown.")
    start = b.stop("start", StopKind.race_start, race_in.start, "Start to confirm", start_when, tz=tz)
    start_seg = b.segment("s-hotel-start", hotel, start, SegmentMode.local,
                          duration_min=inputs.hotel.minutes_to_start if inputs.hotel else None)
    finish = race_seg = None
    if race_in.finish or race_in.track:
        finish = b.stop("finish", StopKind.race_finish, race_in.finish, "Finish to confirm", tz=tz)
        track_limitation = None
        if not race_in.track:
            track_limitation = Limitation(code="race_track_unavailable",
                                          message="Official route not provided: no race flyover.")
        race_seg = b.segment("s-race", start, finish, SegmentMode.race, geometry=race_in.track,
                             provenance=race_in.track_provenance, verified=race_in.track_provenance is not None,
                             limitation=track_limitation)

    _consistency(b, inputs, timeline, tz)

    chapters = [
        _chapter(ChapterId.home, CHAPTER_LABELS[ChapterId.home], [home], [home_seg], b),
        _chapter(ChapterId.departure_hub, hub_label, [hub_out], [], b),
        _chapter(ChapterId.main_transport, HUB_LABEL[main_mode][1] if main_mode else "Transport",
                 [hub_in], [out_seg], b),
        _chapter(ChapterId.arrival_hotel, CHAPTER_LABELS[ChapterId.arrival_hotel], [hotel], [arrival_seg], b),
        _chapter(ChapterId.bib_pickup, CHAPTER_LABELS[ChapterId.bib_pickup], [bib], [bib_seg], b),
        _chapter(ChapterId.race, CHAPTER_LABELS[ChapterId.race], [start, finish], [start_seg, race_seg], b),
        _chapter(ChapterId.return_trip, CHAPTER_LABELS[ChapterId.return_trip], return_stops, return_segments, b),
    ]

    nights = (inputs.hotel.check_out - inputs.hotel.check_in).days if inputs.hotel else summary.nights
    if inputs.hotel and nights != summary.nights:
        b.warnings.append(f"Selected hotel dates cover {nights} nights; you requested {summary.nights} nights.")
    if inputs.hotel and summary.race.race_date and not (
        inputs.hotel.check_in <= summary.race.race_date - timedelta(days=1)
        and inputs.hotel.check_out >= summary.race.race_date
    ):
        b.warnings.append("Selected hotel dates do not cover the night before the race.")
    legs = [inputs.outbound, inputs.return_trip]
    budget = Budget(
        currency=currency,
        cap=summary.budget_eur if currency == "EUR" else None,
        lines=[
            _line("c-reg", CostCategory.registration, "Registration", race_in.registration_cost, currency, "Fare unknown"),
            _line("c-hotel", CostCategory.accommodation, f"Hotel {nights} night{'s' if nights != 1 else ''}",
                  inputs.hotel.cost if inputs.hotel else None, currency, "Price unknown"),
            *_transport_lines(legs, currency, main_mode is not None),
            _line("c-local", CostCategory.local, "Local transport", inputs.local_cost, currency, "Not estimated"),
        ],
    )
    if not budget.complete:
        b.warnings.append(PARTIAL_BUDGET_WARNING)
    if mode is DataMode.demo:
        b.warnings.insert(0, "Demo data: fictional race, hotel and times.")
    elif mode is DataMode.replay:
        b.warnings.insert(0, "Replay of a recorded trace: not live data.")

    limitations = list(summary.limitations)
    for item in b.limitations:
        if item not in limitations:
            limitations.append(item)
    plan = JourneyPlan(
        mission_id=mission_id,
        race_name=summary.race.name,
        revision=0,
        framing_revision=summary.revision,
        mode=mode,
        origin_public=origin,
        date_range=summary.date_range,
        timezone=tz or "UTC",
        currency=currency,
        stops=list(b.stops.values()),
        segments=list(b.segments.values()),
        chapters=chapters,
        budget=budget,
        warnings=list(dict.fromkeys(b.warnings)),
        limitations=limitations,
    )
    plan.sources = _provenances(plan)
    _check_mode(mode, plan.sources)
    return _revise(plan, previous)


def _consistency(b: _Builder, inputs: JourneyInputs, timeline: Timeline | None, tz: str | None) -> None:
    for name, choice in (("outbound", inputs.outbound), ("return", inputs.return_trip)):
        if choice and choice.depart and choice.arrive and choice.arrive.astimezone(UTC) <= choice.depart.astimezone(UTC):
            b.limitations.append(Limitation(code="transport_times_inverted", step="transport",
                                            message=f"Leg {name}: arrival before departure, check the times."))
    out, race = inputs.outbound, inputs.race
    if out and out.arrive and race.bib_pickup_closes:
        transfer = timedelta(minutes=inputs.hotel.minutes_to_bib_pickup) if inputs.hotel and \
            inputs.hotel.minutes_to_bib_pickup else DEFAULT_TRANSFER
        if out.arrive + transfer > race.bib_pickup_closes:
            b.limitations.append(Limitation(code="bib_pickup_unreachable", step="transport",
                                            message="Arrival too late to collect your bib before closing."))
    if timeline is None:
        if out and out.arrive and race.start_time and out.arrive >= race.start_time:
            b.limitations.append(Limitation(code="arrival_after_start", step="transport",
                                            message="Arrival after the race start."))
        b.warnings.append("Race date or timezone unknown: timing consistency not checked.")
        return
    for alert in timeline.alerts:
        if not (race.start_time or (race.rules and race.rules.start_time)) and alert.code in {
            "arrival_after_start", "return_too_early",
        }:
            continue
        if alert.level is AlertLevel.blocking:
            b.limitations.append(Limitation(code=alert.code, message=alert.message))
        elif alert.level is AlertLevel.warning:
            b.warnings.append(alert.message)


def _revise(plan: JourneyPlan, previous: JourneyPlan | None) -> JourneyPlan:
    if previous is None:
        return plan
    unchanged = plan.model_dump(exclude={"revision"}) == previous.model_dump(exclude={"revision"})
    return plan.model_copy(update={"revision": previous.revision if unchanged else previous.revision + 1})
