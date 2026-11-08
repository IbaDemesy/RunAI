"""Deterministic race weekend timeline (no network calls), with incompatibility alerts."""

from datetime import date, datetime, time, timedelta

from runai.logistics.durations import format_duration
from runai.logistics.models import (
    Alert,
    AlertLevel,
    HotelStay,
    RaceRules,
    RunnerGoal,
    Timeline,
    TimelineEvent,
    TransportLeg,
)
from runai.models import Race

DEFAULT_START = time(9, 0)
DEFAULT_PACE_PER_KM = timedelta(minutes=6)
DEFAULT_CORRAL_CLOSE = timedelta(minutes=15)
STATION_TO_PICKUP = timedelta(minutes=45)
DEFAULT_TO_START = timedelta(minutes=30)
PICKUP_DURATION = timedelta(minutes=45)
MIN_PICKUP_SLOT = timedelta(minutes=30)
WAKE_BEFORE_START = timedelta(hours=2, minutes=30)
MARGIN_BEFORE_CORRAL = timedelta(minutes=15)
AFTER_FINISH = timedelta(minutes=90)
SHORT = timedelta(minutes=15)


def build_timeline(
    race: Race | None,
    rules: RaceRules,
    arrival: TransportLeg | None = None,
    hotel: HotelStay | None = None,
    departure: TransportLeg | None = None,
    goal: RunnerGoal | None = None,
) -> Timeline:
    """Dated weekend events (race timezone) and alerts.

    Blocking alerts include arrival after bib pick-up closes, a hotel not covering
    the previous night, and return before estimated finish plus 90 minutes.
    All times inferred from assumptions carry `assumption=True`."""
    tz = rules.tz
    race_day = rules.race_date or (race.race_date if race else None)
    if race_day is None:
        raise ValueError("race date unknown: cannot build the timeline")
    name = rules.race_name or (race.name if race else "Course")
    events: list[TimelineEvent] = []
    alerts: list[Alert] = []

    def at(day: date, moment: time) -> datetime:
        return datetime.combine(day, moment, tzinfo=tz)

    def local(moment: datetime) -> datetime:
        return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)

    def add(start: datetime, end: datetime | None = None, **fields) -> None:
        events.append(TimelineEvent(start=start, end=end or start + SHORT, **fields))

    start = at(race_day, rules.start_time or DEFAULT_START)
    distance = rules.distance_km or (race.distance_km if race else None) or 10
    expected, expected_assumed = _expected_time(goal, distance)
    finish = start + expected

    arrive = None
    if arrival:
        arrive = local(arrival.arrive)
        add(
            local(arrival.depart),
            arrive,
            title=f"{arrival.mode.capitalize()} {arrival.origin} → {arrival.destination}",
            kind="transport",
            detail=arrival.reference,
        )
        if arrive >= start:
            alerts.append(
                Alert(
                    level=AlertLevel.blocking,
                    code="arrival_after_start",
                    message=f"Arrival {arrive:%d/%m %H:%M} after the race start ({start:%d/%m %H:%M}).",
                )
            )

    latest_pickup = start - (rules.corrals_close_before_wave or DEFAULT_CORRAL_CLOSE)
    _add_bib_pickup(rules, race_day, arrive, hotel, at, add, alerts, latest_pickup)

    to_start = timedelta(minutes=hotel.minutes_to_start) if hotel else DEFAULT_TO_START
    if hotel:
        check_in = at(hotel.check_in, hotel.check_in_from)
        if arrive and arrive.date() == hotel.check_in:
            check_in = max(check_in, arrive)
        add(check_in, title=f"Check-in {hotel.name}", kind="hotel")
        eve = race_day - timedelta(days=1)
        if not (hotel.check_in <= eve and hotel.check_out >= race_day):
            alerts.append(
                Alert(
                    level=AlertLevel.blocking,
                    code="hotel_nights",
                    message=f"The hotel ({hotel.check_in:%d/%m} → {hotel.check_out:%d/%m}) does not cover the night of {eve:%d/%m}.",
                )
            )
        check_out = at(hotel.check_out, hotel.check_out_until)
        add(check_out, title=f"Check-out {hotel.name}", kind="hotel")
        if hotel.check_out == race_day and finish + AFTER_FINISH > check_out:
            alerts.append(
                Alert(
                    level=AlertLevel.warning,
                    code="late_checkout",
                    message=(
                        f"Estimated finish {finish:%H:%M}, check-out at {hotel.check_out_until:%H:%M}: "
                        "ask for late check-out or leave your luggage at reception."
                    ),
                )
            )

    corral_close = start - (rules.corrals_close_before_wave or DEFAULT_CORRAL_CLOSE)
    leave = corral_close - to_start - MARGIN_BEFORE_CORRAL
    add(start - WAKE_BEFORE_START, title="Wake up, breakfast", kind="prep", assumption=True)
    add(
        leave,
        leave + to_start,
        title="Hotel → start area journey",
        kind="prep",
        detail=rules.bag_drop,
        assumption=True,
    )
    if rules.corrals_open:
        add(
            at(race_day, rules.corrals_open),
            title="Corrals open",
            kind="race",
            detail=rules.start_waves,
            source_url=rules.source_url("corrals_open"),
        )
    add(
        corral_close,
        title="Corral closes (first wave)",
        kind="race",
        detail="Your wave may start later: check your bib for the exact time.",
        assumption=rules.corrals_close_before_wave is None,
        source_url=rules.source_url("corrals_close_before_wave"),
    )
    start_place = rules.start_location or (race.start_location if race else None)
    add(
        start,
        title=f"Start {name}",
        kind="race",
        location=start_place or "Start location to confirm",
        assumption=rules.start_time is None,
        source_url=rules.source_url("start_time"),
    )
    for gate in rules.time_gates:
        moment = start + gate.max_elapsed
        published = f" (published time ≈ {gate.clock_time:%H:%M})" if gate.clock_time else ""
        add(
            moment,
            title=f"Cut-off km {gate.km:g}:"
            + f" {format_duration(gate.max_elapsed)} elapsed race time",
            kind="info",
            detail=f"No later than {moment:%H:%M} for the first wave{published}.",
            source_url=rules.source_url("time_gates"),
        )
    add(
        finish,
        title="Estimated finish",
        kind="race",
        detail=f"Target time {format_duration(expected)}"
        + (f", time limit {format_duration(rules.time_limit)}" if rules.time_limit else ""),
        assumption=True,
    )
    if rules.time_limit and finish > start + rules.time_limit:
        alerts.append(
            Alert(
                level=AlertLevel.warning,
                code="finish_after_limit",
                message=f"Estimated finish {finish:%H:%M} after the time limit ({format_duration(rules.time_limit)}).",
                source_url=rules.source_url("time_limit"),
            )
        )
    elif expected_assumed:
        alerts.append(
            Alert(
                level=AlertLevel.info,
                code="pace_assumed",
                message=f"Without a goal, finish estimated at {format_duration(DEFAULT_PACE_PER_KM)}/km.",
            )
        )

    if departure:
        leaves = local(departure.depart)
        add(
            leaves,
            local(departure.arrive),
            title=f"{departure.mode.capitalize()} {departure.origin} → {departure.destination}",
            kind="transport",
            detail=departure.reference,
        )
        if leaves < finish + AFTER_FINISH:
            alerts.append(
                Alert(
                    level=AlertLevel.blocking,
                    code="return_too_early",
                    message=(
                        f"Return at {leaves:%d/%m %H:%M}: less than {format_duration(AFTER_FINISH)} after "
                        f"the estimated finish ({finish:%H:%M}). Take a later service."
                    ),
                )
            )

    if not rules.start_time:
        alerts.append(Alert(level=AlertLevel.warning, code="start_time_unknown", message="Start time to confirm."))
    events.sort(key=lambda event: event.start)
    return Timeline(race_name=name, timezone=rules.timezone, events=events, alerts=alerts)


def _expected_time(goal: RunnerGoal | None, distance: float) -> tuple[timedelta, bool]:
    if goal and abs(goal.distance_km - distance) / distance <= 0.02:
        target = goal.target_high or goal.target_low
        if target:
            return target, False
    return DEFAULT_PACE_PER_KM * distance, True


def _add_bib_pickup(rules, race_day, arrive, hotel, at, add, alerts, latest) -> None:
    source = rules.source_url("bib_pickup_windows")
    location = rules.bib_pickup_location
    windows = [
        window
        for window in rules.bib_pickup_windows
        if window.day < race_day
        or (window.day == race_day and rules.bib_pickup_race_day)
    ]
    detail = "ID + confirmation email; registration documents uploaded before pick-up."
    if not windows:
        add(
            at(race_day - timedelta(days=1), time(10, 0)),
            title="Bib pick-up (time slot to confirm)",
            kind="bib_pickup",
            location=location,
            detail=detail,
            assumption=True,
        )
        alerts.append(
            Alert(
                level=AlertLevel.warning,
                code="bib_pickup_unknown",
                message="Bib pick-up days and times not found: to confirm.",
            )
        )
        return
    ready = arrive + (timedelta(minutes=hotel.minutes_to_bib_pickup) if hotel else STATION_TO_PICKUP) if arrive else None
    for window in windows if arrive else reversed(windows):
        opens, closes = at(window.day, window.opens), at(window.day, window.closes)
        if window.day == race_day:
            closes = min(closes, latest)
        begin = max(opens, ready) if ready else opens
        if begin + MIN_PICKUP_SLOT <= closes:
            add(begin, min(begin + PICKUP_DURATION, closes), title="Bib pick-up", kind="bib_pickup",
                location=location, detail=f"Open {window.opens:%H:%M}-{window.closes:%H:%M}. {detail}",
                assumption=arrive is None, source_url=source)
            return
    last = windows[-1]
    when = f"Arrival {arrive:%a %d/%m %H:%M}: too late" if arrive else "No possible time slot"
    message = (
        f"{when} for bib pick-up before corrals close "
        f"(last slot on {last.day:%d/%m} until {last.closes:%H:%M}). Take an earlier service"
    )
    if rules.bib_pickup_proxy_allowed:
        message += " or have someone else collect your bib (signed authorization allowed by the rules)"
    if rules.bib_pickup_race_day is False:
        message += "; no pick-up on race morning"
    alerts.append(Alert(level=AlertLevel.blocking, code="bib_pickup_missed", message=message + ".", source_url=source))
