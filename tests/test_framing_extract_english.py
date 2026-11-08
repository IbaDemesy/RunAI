from datetime import date

import pytest

from runai.contracts.framing import SlotName
from runai.framing.interpret import extract_slots
from runai.search.candidates import location_hint


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("Milan marathon in April 2027", {"city": "Milan", "distance_km": 42.195, "date_window": "april 2027", "edition": "2027"}),
        ("Tokyo 10K from London", {"city": "Tokyo", "distance_km": 10, "origin": "London"}),
        ("Lisbon half", {"city": "Lisbon", "distance_km": 21.0975}),
        ("Lisbon half-marathon", {"city": "Lisbon", "distance_km": 21.0975}),
        ("Lisbon half marathon", {"city": "Lisbon", "distance_km": 21.0975}),
        ("Tokyo 10 k", {"city": "Tokyo", "distance_km": 10}),
        ("Tokyo 5K", {"city": "Tokyo", "distance_km": 5}),
        ("Tokyo 21K", {"city": "Tokyo", "distance_km": 21.0975}),
        ("ultra 50K", {"distance_km": 50}),
        ("Bristol trail", {"city": "Bristol"}),
        ("New York marathon", {"city": "New York"}),
        ("Tokyo 10K leaving from London", {"city": "Tokyo", "origin": "London"}),
        ("Tokyo 10K departing London", {"city": "Tokyo", "origin": "London"}),
        ("Tokyo 10K departing from London", {"city": "Tokyo", "origin": "London"}),
        ("Tokyo 10K from London in London", {"city": "Tokyo", "origin": "London"}),
        ("on 12 April 2027", {"race_date": "2027-04-12", "edition": "2027"}),
        ("April 12, 2027", {"race_date": "2027-04-12", "edition": "2027"}),
        ("in April", {"date_window": "april 2027"}),
        ("race in April 2027 in London", {"city": "London", "date_window": "april 2027"}),
        ("in January 2027", {"date_window": "january 2027", "edition": "2027"}),
        ("spring 2027", {"date_window": "spring 2027", "edition": "2027"}),
        ("summer 2027", {"date_window": "summer 2027", "edition": "2027"}),
        ("autumn 2027", {"date_window": "autumn 2027", "edition": "2027"}),
        ("fall 2027", {"date_window": "fall 2027", "edition": "2027"}),
        ("winter", {"date_window": "winter"}),
        ("no budget", {"budget": None}),
        ("budget £500", {"budget": 500}),
        ("budget $450.50", {"budget": 450.5}),
        ("500 £", {"budget": 500}),
        ("450 $", {"budget": 450}),
        ("un semi-marathon à Lisbonne édition 2027", {"city": "Lisbonne", "distance_km": 21.0975, "edition": "2027"}),
        ("une course à Tokyo en avril 2028 depuis Lyon", {"city": "Tokyo", "date_window": "avril 2028", "origin": "Lyon"}),
        ("le 12 avril 2027, 200 euros", {"race_date": "2027-04-12", "budget": 200}),
        ("pas de budget", {"budget": None}),
        ("", {}),
    ],
)
def test_bilingual_slot_extraction(prompt, expected):
    slots = extract_slots(prompt, today=date(2026, 11, 7))
    for name, value in expected.items():
        assert slots[SlotName(name)] == value
    if not expected:
        assert slots == {}


@pytest.mark.parametrize("prompt", ["in April 2027", "in Winter 2027", "on 31 April 2027", "April 31, 2027", "Un marathon en décembre", "A marathon in April", "Spring marathon"])
def test_dates_never_become_cities(prompt):
    assert SlotName.city not in extract_slots(prompt)


@pytest.mark.parametrize("prompt", ["on 31 April 2027", "April 31, 2027", "2027-02-30"])
def test_invalid_dates_are_not_extracted(prompt):
    assert SlotName.race_date not in extract_slots(prompt)


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("Milan marathon in April 2027", "Milan"),
        ("Tokyo 10K from London in London", "Tokyo"),
        ("Lisbon half", "Lisbon"),
        ("in April 2027", None),
        ("in Spring 2027", None),
        ("in April 2027 in Japan", "Japan"),
        ("un semi en Chine", "Chine"),
        ("", None),
        (None, None),
    ],
)
def test_bilingual_location_hint(prompt, expected):
    assert location_hint(prompt) == expected
