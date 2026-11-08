"""Local demo parsing must work without an LLM or partner credentials."""

from datetime import date

import pytest

from runai.framing.interpret import extract_slots


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Milan marathon in April 2027", {"city": "Milan", "distance_km": 42.195, "date_window": "april 2027", "edition": "2027"}),
        ("Tokyo 10K from London", {"city": "Tokyo", "distance_km": 10.0, "origin": "London"}),
        ("half marathon in Lisbon next March", {"city": "Lisbon", "distance_km": 21.0975, "date_window": "march 2027"}),
        ("10K Tokyo", {"city": "Tokyo", "distance_km": 10.0}),
        ("a 10k in Tokyo on 12 June 2028", {"city": "Tokyo", "distance_km": 10.0, "race_date": "2028-06-12", "edition": "2028"}),
        ("10 k", {"distance_km": 10.0}),
        ("ten k", {"distance_km": 10.0}),
        ("half", {"distance_km": 21.0975}),
        ("half marathon", {"distance_km": 21.0975}),
        ("HM", {"distance_km": 21.0975}),
        ("Boston Marathon", {"city": "Boston", "race": "Boston Marathon", "distance_km": 42.195}),
        ("New York marathon", {"city": "New York", "distance_km": 42.195}),
        ("boston marathon", {"distance_km": 42.195}),
        ("April marathon", {"distance_km": 42.195}),
        ("Monday marathon", {"distance_km": 42.195}),
        ("race in April 2027", {"date_window": "april 2027", "edition": "2027"}),
        ("race in next March", {"date_window": "march 2027"}),
        ("race in this May", {"date_window": "may 2027"}),
        ("in December", {"date_window": "december 2026"}),
        ("June 12, 2028", {"race_date": "2028-06-12", "edition": "2028"}),
        ("June 12 2028", {"race_date": "2028-06-12", "edition": "2028"}),
        ("12 June 2028", {"race_date": "2028-06-12", "edition": "2028"}),
        ("on 31 February 2028", {}),
        ("February 31, 2028", {}),
        ("budget €600", {"budget": 600.0}),
        ("EUR 600", {"budget": 600.0}),
        ("600 EUR budget", {"budget": 600.0}),
        ("€600.50", {"budget": 600.5}),
        ("$600", {"budget": 600.0}),
        ("no budget", {"budget": None}),
        ("two nights", {"nights": 2}),
        ("one night", {"nights": 1}),
        ("from Lyon to Milan", {"origin": "Lyon", "city": "Milan"}),
        ("from New York to São Paulo in April 2027", {"origin": "New York", "city": "São Paulo", "date_window": "april 2027", "edition": "2027"}),
        ("race in Tokyo or Nairobi", {}),
        ("not a marathon", {}),
        ("A marathon", {"distance_km": 42.195}),
        ("Half marathon", {"distance_km": 21.0975}),
        ("", {}),
        ("somewhere warm", {}),
        ("race in Monday", {}),
        ("Next marathon", {"distance_km": 42.195}),
        ("This marathon", {"distance_km": 42.195}),
    ],
)
def test_english_slots(text, expected):
    assert extract_slots(text, today=date(2026, 11, 7)) == expected


@pytest.mark.parametrize("month", [
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
])
def test_all_english_months(month):
    assert extract_slots(f"in {month} 2028") == {"date_window": f"{month.lower()} 2028", "edition": "2028"}


@pytest.mark.parametrize("number, word", list(enumerate(
    ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), 1,
)))
def test_all_night_number_words(number, word):
    assert extract_slots(f"{word} nights") == {"nights": number}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("une course", {}),
        ("pas de marathon", {}),
        ("Un marathon en décembre", {"distance_km": 42.195, "date_window": "décembre 2026"}),
        ("une course à Tokyo ou Nairobi", {}),
        ("marathon de Nairobi depuis São Paulo le 12 avril 2027, 1200 €, 3 nuits, train", {
            "city": "Nairobi", "origin": "São Paulo", "race_date": "2027-04-12",
            "distance_km": 42.195, "budget": 1200, "nights": 3, "transport_mode": "train",
        }),
        ("semi à Tokyo en avril 2028", {"city": "Tokyo", "distance_km": 21.0975, "date_window": "avril 2028"}),
        ("course le 31 février 2028", {}),
        ("le trail des Templiers à Millau", {"race": "trail des Templiers", "city": "Millau"}),
        ("Ecotrail Paris 45 km", {"race": "Ecotrail Paris", "distance_km": 45}),
        ("une course de 20 km à Lausanne", {"city": "Lausanne", "distance_km": 20}),
        ("course à Tokyo depuis 20 km de Lyon", {"city": "Tokyo", "distance_km": 20}),
        ("Marathon de Paris depuis Lyon en train, 2 nuits, 300 euros", {
            "race": "Marathon de Paris", "city": "Paris", "origin": "Lyon",
            "distance_km": 42.195, "nights": 2, "budget": 300, "transport_mode": "train",
        }),
        ("Marathon de New York depuis Paris", {"race": "Marathon de New York", "city": "New York", "origin": "Paris", "distance_km": 42.195}),
        ("semi-marathon de Bordeaux", {"city": "Bordeaux", "distance_km": 21.0975}),
        ("un 10 km à Nantes", {"city": "Nantes", "distance_km": 10}),
        ("course à Tokyo en mars", {"city": "Tokyo", "date_window": "mars 2027"}),
        ("course à Tokyo au mois de mai", {"city": "Tokyo", "date_window": "mai 2027"}),
        ("course à Tokyo en mars édition 2030", {"city": "Tokyo", "date_window": "mars 2030", "edition": "2030"}),
    ],
)
def test_french_regressions(text, expected):
    assert extract_slots(text, today=date(2026, 11, 7)) == expected
