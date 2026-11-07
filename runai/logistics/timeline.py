"""Timeline déterministe du week-end de course (aucun appel réseau), avec alertes d'incompatibilité."""

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
    """Événements datés du week-end (fuseau de la course) et alertes.

    Alertes `bloquant` : train arrivé après la fermeture du retrait, hôtel qui ne couvre pas la veille,
    retour avant l'arrivée estimée + 1h30… Tout horaire déduit d'une hypothèse a `assumption=True`.
    """
    tz = rules.tz
    race_day = rules.race_date or (race.race_date if race else None)
    if race_day is None:
        raise ValueError("date de course inconnue : impossible de construire la timeline")
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
                    message=f"Arrivée {arrive:%d/%m %H:%M} après le départ de la course ({start:%d/%m %H:%M}).",
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
                    message=f"L'hôtel ({hotel.check_in:%d/%m} → {hotel.check_out:%d/%m}) ne couvre pas la nuit du {eve:%d/%m}.",
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
                        f"Arrivée estimée {finish:%H:%M}, check-out à {hotel.check_out_until:%H:%M} : "
                        "demander un late check-out ou laisser les bagages à la réception."
                    ),
                )
            )

    corral_close = start - (rules.corrals_close_before_wave or DEFAULT_CORRAL_CLOSE)
    leave = corral_close - to_start - MARGIN_BEFORE_CORRAL
    add(start - WAKE_BEFORE_START, title="Réveil, petit-déjeuner", kind="prep", assumption=True)
    add(
        leave,
        leave + to_start,
        title="Trajet hôtel → zone de départ",
        kind="prep",
        detail=rules.bag_drop,
        assumption=True,
    )
    if rules.corrals_open:
        add(
            at(race_day, rules.corrals_open),
            title="Ouverture des sas",
            kind="race",
            detail=rules.start_waves,
            source_url=rules.source_url("corrals_open"),
        )
    add(
        corral_close,
        title="Fermeture du sas (1re vague)",
        kind="race",
        detail="Votre vague peut partir plus tard : heure exacte sur le dossard.",
        assumption=rules.corrals_close_before_wave is None,
        source_url=rules.source_url("corrals_close_before_wave"),
    )
    start_place = rules.start_location or (race.start_location if race else None)
    add(
        start,
        title=f"Départ {name}",
        kind="race",
        location=start_place or "Lieu de départ à confirmer",
        assumption=rules.start_time is None,
        source_url=rules.source_url("start_time"),
    )
    for gate in rules.time_gates:
        moment = start + gate.max_elapsed
        published = f" (heure publiée ≈ {gate.clock_time:%H:%M})" if gate.clock_time else ""
        add(
            moment,
            title=f"Barrière km {gate.km:g}".replace(".", ",") + " :"
            + f" {format_duration(gate.max_elapsed)} de course",
            kind="info",
            detail=f"Au plus tard {moment:%H:%M} pour la 1re vague{published}.",
            source_url=rules.source_url("time_gates"),
        )
    add(
        finish,
        title="Arrivée estimée",
        kind="race",
        detail=f"Temps visé {format_duration(expected)}"
        + (f", temps limite {format_duration(rules.time_limit)}" if rules.time_limit else ""),
        assumption=True,
    )
    if rules.time_limit and finish > start + rules.time_limit:
        alerts.append(
            Alert(
                level=AlertLevel.warning,
                code="finish_after_limit",
                message=f"Arrivée estimée {finish:%H:%M} après le temps limite ({format_duration(rules.time_limit)}).",
                source_url=rules.source_url("time_limit"),
            )
        )
    elif expected_assumed:
        alerts.append(
            Alert(
                level=AlertLevel.info,
                code="pace_assumed",
                message=f"Sans objectif, arrivée estimée à {format_duration(DEFAULT_PACE_PER_KM)}/km.",
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
                        f"Retour à {leaves:%d/%m %H:%M} : moins de {format_duration(AFTER_FINISH)} après "
                        f"l'arrivée estimée ({finish:%H:%M}). Prendre un trajet plus tard."
                    ),
                )
            )

    if not rules.start_time:
        alerts.append(Alert(level=AlertLevel.warning, code="start_time_unknown", message="Heure de départ à confirmer."))
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
        or (window.day == race_day and rules.bib_pickup_race_day and at(window.day, window.opens) + MIN_PICKUP_SLOT <= latest)
    ]
    detail = "Pièce d'identité + e-mail de confirmation ; documents d'inscription téléversés avant le retrait."
    if not windows:
        add(
            at(race_day - timedelta(days=1), time(10, 0)),
            title="Retrait du dossard (créneau à confirmer)",
            kind="bib_pickup",
            location=location,
            detail=detail,
            assumption=True,
        )
        alerts.append(
            Alert(
                level=AlertLevel.warning,
                code="bib_pickup_unknown",
                message="Jours et horaires de retrait du dossard non trouvés : à confirmer.",
            )
        )
        return
    if arrive is None:
        window = windows[-1]
        begin = at(window.day, window.opens)
        add(begin, begin + PICKUP_DURATION, title="Retrait du dossard", kind="bib_pickup", location=location,
            detail=detail, assumption=True, source_url=source)
        return
    ready = arrive + (timedelta(minutes=hotel.minutes_to_bib_pickup) if hotel else STATION_TO_PICKUP)
    for window in windows:
        opens, closes = at(window.day, window.opens), at(window.day, window.closes)
        if window.day == race_day:
            closes = min(closes, latest)
        begin = max(opens, ready)
        if begin + MIN_PICKUP_SLOT <= closes:
            add(begin, min(begin + PICKUP_DURATION, closes), title="Retrait du dossard", kind="bib_pickup",
                location=location, detail=f"Ouvert {window.opens:%H:%M}-{window.closes:%H:%M}. {detail}",
                source_url=source)
            return
    last = windows[-1]
    message = (
        f"Arrivée {arrive:%a %d/%m %H:%M} : trop tard pour le retrait du dossard "
        f"(dernier créneau le {last.day:%d/%m} jusqu'à {last.closes:%H:%M}). Prendre un trajet plus tôt"
    )
    if rules.bib_pickup_proxy_allowed:
        message += " ou faire retirer le dossard par un tiers (délégation signée prévue par le règlement)"
    if rules.bib_pickup_race_day is False:
        message += " ; pas de retrait le matin de la course"
    alerts.append(Alert(level=AlertLevel.blocking, code="bib_pickup_missed", message=message + ".", source_url=source))
