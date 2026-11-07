"""Timeline déterministe du week-end de course, à partir d'une RaceLogistics. Aucun appel réseau."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

from models import RaceLogistics

DEFAULT_START = time(9, 0)
DEFAULT_PICKUP = (time(10, 0), time(19, 0))
HOTEL_CHECKIN = time(15, 0)
HOTEL_CHECKOUT = time(12, 0)
PACE_MIN_PER_KM = 6.0
ACCESS_MIN = 30
START_MARGIN_MIN = 45


@dataclass
class Step:
    when: datetime
    label: str
    detail: str = ""
    assumption: bool = False

    def as_dict(self) -> dict:
        d = asdict(self)
        d["when"] = self.when.isoformat(timespec="minutes")
        return d


def _parse_time(s: str | None) -> time | None:
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*[h:]\s*(\d{2})?", s)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2) or 0)
    return time(h, mn) if 0 <= h < 24 and 0 <= mn < 60 else None


def _parse_window(s: str | None) -> tuple[time, time] | None:
    if not s:
        return None
    hits = re.findall(r"(\d{1,2})\s*[h:]\s*(\d{2})?", s)
    if len(hits) < 2:
        return None
    (h1, m1), (h2, m2) = hits[0], hits[1]
    try:
        return time(int(h1), int(m1 or 0)), time(int(h2), int(m2 or 0))
    except ValueError:
        return None


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def build_timeline(race: RaceLogistics, travel_hours: float = 3.0, home: str = "Paris") -> list[Step]:
    race_day = _parse_date(race.date)
    if race_day is None:
        raise ValueError("date de course inconnue : impossible de construire la timeline")
    steps: list[Step] = []
    at = datetime.combine
    travel = timedelta(hours=travel_hours)

    start_t = _parse_time(race.start_time)
    start = at(race_day, start_t or DEFAULT_START)

    pickup_days = sorted(d for d in (_parse_date(x) for x in race.bib_pickup.days) if d)
    before = [d for d in pickup_days if d < race_day]
    window = _parse_window(race.bib_pickup.hours)
    pickup_day = before[-1] if before else race_day - timedelta(days=1)
    open_t, close_t = window or DEFAULT_PICKUP
    pickup_assumed = not before or window is None

    arrival = at(pickup_day, max(open_t, time(12, 0)))
    if arrival + timedelta(hours=1) > at(pickup_day, close_t):
        arrival = at(pickup_day, open_t)
    steps.append(Step(arrival - travel, f"Départ de {home}", f"trajet estimé {travel_hours:g} h", True))
    steps.append(Step(arrival, f"Arrivée à {race.city or 'la ville de la course'}", "calée sur l'ouverture du retrait", True))
    pickup = arrival + timedelta(hours=1)
    steps.append(Step(pickup, "Retrait du dossard",
                      f"{race.bib_pickup.location or 'lieu à confirmer'} ({race.bib_pickup.hours or 'horaires à confirmer'}) ; "
                      "apporter pièce d'identité + PPS/certificat/licence", pickup_assumed))
    checkin = max(at(pickup_day, HOTEL_CHECKIN), pickup + timedelta(hours=1))
    steps.append(Step(checkin, "Check-in hôtel", "hôtel choisi selon l'accès au départ", True))

    wake = start - timedelta(hours=2, minutes=30)
    leave = start - timedelta(minutes=ACCESS_MIN + START_MARGIN_MIN)
    steps.append(Step(wake, "Réveil, petit-déjeuner", "", start_t is None))
    steps.append(Step(leave, "Départ de l'hôtel vers la ligne", race.start_access or "accès au départ à confirmer", True))
    steps.append(Step(start - timedelta(minutes=START_MARGIN_MIN), "Arrivée en zone de départ / consigne",
                      race.start_location or "", start_t is None))
    steps.append(Step(start, f"Départ {race.name}", race.start_location or "", start_t is None))

    duration = timedelta(minutes=(race.distance_km or 10) * PACE_MIN_PER_KM)
    finish = start + duration
    steps.append(Step(finish, "Arrivée estimée", f"allure {PACE_MIN_PER_KM:g} min/km ; temps limite {race.time_limit or 'inconnu'}", True))
    checkout = max(at(race_day, HOTEL_CHECKOUT), finish + timedelta(hours=1, minutes=30))
    steps.append(Step(checkout, "Check-out hôtel", "demander un late check-out si après 12h" if checkout.time() > HOTEL_CHECKOUT else "", True))
    back = checkout + timedelta(hours=1)
    steps.append(Step(back, f"Retour vers {home}", "", True))
    steps.append(Step(back + travel, f"Arrivée à {home}", "", True))
    return sorted(steps, key=lambda s: s.when)


def to_ics(steps: list[Step], race_name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RunAI//spike logistique//FR"]
    for i, s in enumerate(steps):
        t = s.when.strftime("%Y%m%dT%H%M%S")
        end = (s.when + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%S")
        summary = s.label + (" (estimé)" if s.assumption else "")
        lines += ["BEGIN:VEVENT", f"UID:runai-{i}-{t}@runai", f"DTSTAMP:{stamp}", f"DTSTART:{t}", f"DTEND:{end}",
                  f"SUMMARY:{summary}", f"DESCRIPTION:{race_name} - {s.detail}".replace("\n", " "), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
