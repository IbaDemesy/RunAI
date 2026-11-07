from models import BibPickup, RaceLogistics
from timeline import build_timeline, to_ics


def _race(**kw):
    base = {"name": "Test 10K", "date": "2027-04-04", "start_time": "09:30", "distance_km": 10, "city": "Milan",
                "bib_pickup": BibPickup(days=["2027-04-02", "2027-04-03"], hours="10h-19h")}
    base.update(kw)
    return RaceLogistics(**base)


def test_order_and_key_steps():
    steps = build_timeline(_race())
    assert steps == sorted(steps, key=lambda s: s.when)
    labels = [s.label for s in steps]
    assert labels.index("Retrait du dossard") < labels.index("Départ Test 10K")
    pickup = next(s for s in steps if s.label == "Retrait du dossard")
    assert pickup.when.date().isoformat() == "2027-04-03" and not pickup.assumption
    start = next(s for s in steps if s.label == "Départ Test 10K")
    assert start.when.isoformat() == "2027-04-04T09:30:00" and not start.assumption


def test_missing_data_is_flagged():
    steps = build_timeline(_race(start_time=None, bib_pickup=BibPickup()))
    assert next(s for s in steps if s.label == "Départ Test 10K").assumption
    assert next(s for s in steps if s.label == "Retrait du dossard").assumption


def test_ics():
    ics = to_ics(build_timeline(_race()), "Test 10K")
    steps = build_timeline(_race())
    assert ics.count("BEGIN:VEVENT") == len(steps) and ics.startswith("BEGIN:VCALENDAR")
