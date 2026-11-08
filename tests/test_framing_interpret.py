from datetime import date

import pytest

from runai.framing.interpret import extract_slots


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Milan marathon in April 2027",
            {"city": "Milan", "race": "Milan marathon", "edition": "2027", "distance_km": 42.195, "date_window": "april 2027"},
        ),
        (
            "I want to run the Berlin Marathon in September 2027 from Paris",
            {
                "city": "Berlin",
                "race": "Berlin Marathon",
                "edition": "2027",
                "origin": "Paris",
                "distance_km": 42.195,
                "date_window": "september 2027",
            },
        ),
        (
            "A marathon in spring, from Lyon",
            {"origin": "Lyon", "distance_km": 42.195, "date_window": "march-may 2027"},
        ),
        (
            "Half marathon in Lisbon next October, …",
            {"city": "Lisbon", "distance_km": 21.0975, "date_window": "october 2027"},
        ),
        (
            "Tokyo 10K from London",
            {"city": "Tokyo", "race": "Tokyo 10K", "origin": "London", "distance_km": 10.0},
        ),
        ("Tokyo 10k", {"city": "Tokyo", "race": "Tokyo 10k", "distance_km": 10.0}),
        ("a 5K in Nairobi", {"city": "Nairobi", "distance_km": 5.0}),
        ("a half in Lisbon", {"city": "Lisbon", "distance_km": 21.0975}),
        ("half-marathon in Lisbon", {"city": "Lisbon", "distance_km": 21.0975}),
        ("ultra 50 miles", {"distance_km": 80.4672}),
        ("un ultra de 50 miles", {"distance_km": 80.4672}),
        ("un trail de 12,5 km à Annecy", {"city": "Annecy", "distance_km": 12.5}),
        ("marathon of New York", {"city": "New York", "distance_km": 42.195}),
        (
            "Marathon de New York depuis São Paulo",
            {
                "city": "New York",
                "origin": "São Paulo",
                "race": "Marathon de New York",
                "distance_km": 42.195,
            },
        ),
        ("not a marathon in Berlin", {"city": "Berlin"}),
        ("pas de marathon à Berlin", {"city": "Berlin"}),
        ("not a half-marathon, 10K in Berlin", {"city": "Berlin", "distance_km": 10.0}),
        (
            "not a marathon, a half in Berlin",
            {"city": "Berlin", "distance_km": 21.0975},
        ),
        (
            "no budget for a marathon in Berlin",
            {"city": "Berlin", "distance_km": 42.195, "budget": None},
        ),
        (
            "marathon in April 2027",
            {"distance_km": 42.195, "date_window": "april 2027", "edition": "2027"},
        ),
        (
            "in April 2027, race in Berlin",
            {"city": "Berlin", "date_window": "april 2027", "edition": "2027"},
        ),
        ("in next October", {"date_window": "october 2027"}),
        ("en avril 2027", {"date_window": "avril 2027"}),
        ("en février", {"date_window": "février 2027"}),
        ("in November", {"date_window": "november 2026"}),
        ("next November", {"date_window": "november 2027"}),
        ("in March edition 2030", {"date_window": "march 2030", "edition": "2030"}),
        ("on 12 April 2027", {"race_date": "2027-04-12", "edition": "2027"}),
        ("on April 12, 2027", {"race_date": "2027-04-12", "edition": "2027"}),
        ("on April 12th 2027", {"race_date": "2027-04-12", "edition": "2027"}),
        ("le 12 avril 2027", {"race_date": "2027-04-12"}),
        ("race on 2027-04-12", {"race_date": "2027-04-12"}),
        ("on February 31, 2027", {}),
        ("le 31 février 2028", {}),
        ("a race in summer 2027", {"date_window": "june-august 2027", "edition": "2027"}),
        ("a race in autumn", {"date_window": "september-november 2026"}),
        ("a race in fall 2027", {"date_window": "september-november 2027", "edition": "2027"}),
        ("a race in winter 2027", {"date_window": "december 2027-february 2028", "edition": "2027"}),
        ("une course au printemps", {"date_window": "mars-mai 2027"}),
        ("au printemps 2028", {"date_window": "mars-mai 2028"}),
        ("une course en été 2027", {"date_window": "juin-août 2027"}),
        ("une course en automne", {"date_window": "septembre-novembre 2026"}),
        ("une course en hiver", {"date_window": "décembre 2026-février 2027"}),
        ("au printemps", {}),
        (
            "600 EUR, 3 nights, by train",
            {"budget": 600.0, "nights": 3, "transport_mode": "train"},
        ),
        (
            "£400, 2 nights, flying",
            {"budget": 400.0, "nights": 2, "transport_mode": "flight"},
        ),
        ("400 £, by plane", {"budget": 400.0, "transport_mode": "flight"}),
        (
            "500 euros, 2 nuits, en voiture",
            {"budget": 500.0, "nights": 2, "transport_mode": "car"},
        ),
        ("EUR 650, by bus", {"budget": 650.0, "transport_mode": "bus"}),
        ("€550, by car", {"budget": 550.0, "transport_mode": "car"}),
        ("550 €, by train", {"budget": 550.0, "transport_mode": "train"}),
        (
            "Tokyo 5K from London by plane",
            {
                "city": "Tokyo",
                "race": "Tokyo 5K",
                "origin": "London",
                "distance_km": 5.0,
                "transport_mode": "flight",
            },
        ),
        (
            "race in New York next October from São Paulo",
            {"city": "New York", "origin": "São Paulo", "date_window": "october 2027"},
        ),
        ("a race in Berlin or Lisbon", {}),
        ("une course à Tokyo ou Nairobi", {}),
        ("notable marathon in Berlin", {"city": "Berlin", "distance_km": 42.195}),
        ("a race from Nottingham", {"origin": "Nottingham"}),
        ("a race in Winter Park", {"city": "Winter Park"}),
    ],
)
def test_extract_slots_bilingual_exact_values(text, expected):
    assert extract_slots(text, today=date(2026, 11, 7)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("en janvier 2028 à Tokyo", {"city": "Tokyo", "date_window": "janvier 2028"}),
        ("in February 2028 for a race", {"date_window": "february 2028", "edition": "2028"}),
        ("en mars 2028 avec un ami", {"date_window": "mars 2028"}),
        ("in April 2028 with friends", {"date_window": "april 2028", "edition": "2028"}),
        ("en mai 2028 pour une course", {"date_window": "mai 2028"}),
        ("in June 2028 at a race", {"date_window": "june 2028", "edition": "2028"}),
        ("en juillet 2028 à Lyon", {"city": "Lyon", "date_window": "juillet 2028"}),
        ("in August 2028 please", {"date_window": "august 2028", "edition": "2028"}),
        ("en septembre 2028 avec des amis", {"date_window": "septembre 2028"}),
        ("in October 2028 for a race", {"date_window": "october 2028", "edition": "2028"}),
        ("en novembre 2028 à Lyon", {"city": "Lyon", "date_window": "novembre 2028"}),
        ("in December 2028 for a race", {"date_window": "december 2028", "edition": "2028"}),
        (
            "au printemps 2028 à Tokyo",
            {"city": "Tokyo", "date_window": "mars-mai 2028"},
        ),
        (
            "a race in summer from London",
            {"origin": "London", "date_window": "june-august 2027"},
        ),
        ("not 10K, a half", {"distance_km": 21.0975}),
        ("pas de semi-marathon", {}),
        ("sans marathon", {}),
        (
            "a race in Berlin, 80,50 EUR, 1 night",
            {"city": "Berlin", "budget": 80.5, "nights": 1},
        ),
    ],
)
def test_date_and_negation_boundaries(text, expected):
    assert extract_slots(text, today=date(2026, 11, 7)) == expected


@pytest.mark.parametrize(
    ("text", "today", "expected"),
    [
        (
            "a race in winter",
            date(2027, 1, 7),
            {"date_window": "december 2026-february 2027"},
        ),
        (
            "une course en hiver",
            date(2027, 2, 7),
            {"date_window": "décembre 2026-février 2027"},
        ),
        (
            "a race in winter",
            date(2027, 3, 7),
            {"date_window": "december 2027-february 2028"},
        ),
        ("a race in spring", date(2027, 4, 7), {"date_window": "march-may 2027"}),
        ("a race in summer", date(2027, 9, 7), {"date_window": "june-august 2028"}),
        ("in April", date(2027, 4, 7), {"date_window": "april 2027"}),
        ("next April", date(2027, 4, 7), {"date_window": "april 2028"}),
    ],
)
def test_date_hints_roll_over_deterministically(text, today, expected):
    assert extract_slots(text, today=today) == expected
