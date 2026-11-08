"""Example recap: Wizz Air Milano Marathon 2027, fictional profile and bookings."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from runai.models import (
    Race,
    RunnerProfile,
    Source,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
)

from .build import default_timeline, recap_from_mission
from .models import KeyFact, Recap, RecapSource, TimelineItem

MILAN = ZoneInfo("Europe/Rome")
NJUKO_URL = "https://in.njuko.com/wizz-air-milano-marathon-20271776152378557"


def _t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2027, 4, day, hour, minute, tzinfo=MILAN)


DEMO_RACE = Race(
    name="Wizz Air Milano Marathon 2027",
    city="Milan",
    country="IT",
    race_date=date(2027, 4, 4),
    start_time="08:00",
    distance_km=42.195,
    registration_url=NJUKO_URL,
    bib_pickup="Marathon village, Sat. 3 April (example times)",
    start_location="Corso Venezia (example)",
    sources=[Source(url=NJUKO_URL, title="Njuko registration page")],
)

DEMO_STEPS = [
    StepResult(kind=StepKind.search, status=StepStatus.completed, summary="Course found by Linkup."),
    StepResult(
        kind=StepKind.registration, status=StepStatus.stopped_before_commitment,
        stop_point=StopPoint.health_declaration, url=NJUKO_URL, price_eur=114.0,
        summary="Njuko form pre-filled with the fictional profile, stopped at the license / medical certificate step.",
        h_session_id="demo-registration",
    ),
    StepResult(
        kind=StepKind.accommodation, status=StepStatus.stopped_before_commitment,
        stop_point=StopPoint.payment, url="https://example.org/hotel-milano/paiement", price_eur=238.0,
        summary="Example hotel 900 m from the start, 2 nights (3 to 5 April), 1 adult.",
        h_session_id="demo-accommodation",
    ),
    StepResult(
        kind=StepKind.transport, status=StepStatus.stopped_before_commitment,
        stop_point=StopPoint.payment, url="https://example.org/train-paris-milano/paiement", price_eur=139.8,
        summary="Direct train Paris Gare de Lyon ⇄ Milano Centrale, outbound Sat. 3 April, return Mon. 5 April.",
        h_session_id="demo-transport",
    ),
]


def _timeline() -> list[TimelineItem]:
    race_items = [t for t in default_timeline(DEMO_RACE) if t.tag == "course"]
    return race_items + [
        TimelineItem(start=_t(3, 6, 28), end=_t(3, 13, 35), title="Train Paris Gare de Lyon → Milano Centrale",
                     detail="direct, arrival 13:35", location="Gare de Lyon, Paris", tag="a_payer"),
        TimelineItem(start=_t(3, 15, 0), end=_t(3, 15, 30), title="Hotel check-in",
                     detail="900 m from the start", location="Example hotel, Milan", tag="a_payer"),
        TimelineItem(start=_t(3, 16, 0), end=_t(3, 17, 0), title="Bib pick-up at the village",
                     detail="ID + medical documents", location="Marathon village (example)",
                     tag="info", alarm_minutes=120),
        TimelineItem(start=_t(3, 19, 30), title="Dinner, prepare your kit", detail="bib, pins, gels",
                     tag="conseil", in_calendar=False),
        TimelineItem(start=_t(4, 5, 15), title="Suggested wake-up time", detail="breakfast 2 h 30 before the start",
                     tag="conseil", in_calendar=False),
        TimelineItem(start=_t(5, 9, 10), end=_t(5, 16, 20), title="Train Milano Centrale → Paris Gare de Lyon",
                     detail="direct, arrival 16:20", location="Milano Centrale", tag="a_payer"),
    ]


def demo_recap() -> Recap:
    return recap_from_mission(
        DEMO_RACE,
        RunnerProfile(),
        DEMO_STEPS,
        recap_id="demo-milan",
        voice_request="I want to run the Milan marathon in April, leaving from Paris, goal 3 h 45.",
        goal="3 h 45",
        options={
            StepKind.registration: ["Competitive category (FFA license or RUNCARD)"],
            StepKind.accommodation: ["Breakfast included", "Free cancellation until 1 April"],
            StepKind.transport: ["Second class, window seats", "Exchangeable tickets"],
        },
        timeline=_timeline(),
        key_facts=[
            KeyFact(label="Start", value="Sun. 4 April 2027 · 08:00", detail="Corso Venezia (example)", source=1),
            KeyFact(label="Distance", value="42.195 km", detail="marathon, city course", source=1),
            KeyFact(label="Registration", value="114 € on Njuko", detail="price valid until 31 Dec. 2026, read on 7 Nov. 2026", source=1),
            KeyFact(label="Competitive status", value="World Athletics license (FFA) or RUNCARD",
                    detail="otherwise non-competitive category; Italian medical certificate for RUNCARD (2026 rules)",
                    source=2),
            KeyFact(label="Bib pick-up", value="Sat. 3 April", detail="marathon village (example)", source=1),
            KeyFact(label="Goal", value="3 h 45", detail="average pace 5:20 /km"),
        ],
        checklist=[
            "Attach your FFA license, or obtain the RUNCARD and Italian medical certificate, or choose the non-competitive category.",
            "Bring ID to collect your bib.",
            "Import week-end.ics into your calendar.",
        ],
        extra_sources=[RecapSource(label="Official Milano Marathon website (2026 rules)", url="https://www.milanomarathon.it/",
                                   found_by="Linkup", used_for="rules for foreign runners")],
        notice="Demo example: runner profile, hotel, trains, times and agent links are fictional. "
               "Nothing has been paid or submitted.",
        generated_at=datetime(2026, 11, 7, 15, 42, tzinfo=UTC),
    )
