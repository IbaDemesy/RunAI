from datetime import date

import pytest

from runai.contracts.framing import SlotName
from runai.framing.interpret import extract_slots

TODAY = date(2026, 11, 8)


def slots(text):
    return {k.value: v for k, v in extract_slots(text, TODAY).items()}


@pytest.mark.parametrize(
    ("text", "city"),
    [
        ("I need 3 nights in Lisbon for the half marathon in March", "Lisbon"),
        ("I'm looking for a half marathon in Porto and a hotel", "Porto"),
        ("I live in Paris and want a marathon in Berlin", "Berlin"),
        ("Je vis à Paris et veux un marathon à Berlin", "Berlin"),
        ("Je cours le 10 km de Nantes le 5 octobre 2027", "Nantes"),
    ],
)
def test_f5_city_stops_at_sentence_boundary(text, city):
    assert slots(text)["city"] == city


def test_f5_my_first_is_not_a_city():
    assert "city" not in slots("My first 10K in October")


@pytest.mark.parametrize(
    ("text", "budget"),
    [
        ("budget $1,200", 1200.0),
        ("1,500 euros", 1500.0),
        ("1 200 euros", 1200.0),
        ("around 1.5k euros", 1500.0),
        ("my budget is 800", 800.0),
        ("budget of 800", 800.0),
        ("trois cents euros", 300.0),
    ],
)
def test_f6_f3_budget_amounts(text, budget):
    result = slots(text)
    assert result["budget"] == budget
    assert "distance_km" not in result


@pytest.mark.parametrize("text", ["sans plafond", "no limit", "pas de limite"])
def test_f3_budget_no_limit(text):
    assert extract_slots(text, TODAY) == {SlotName.budget: None}


@pytest.mark.parametrize(
    ("text", "nights"),
    [("deux nuits", 2), ("une nuit", 1), ("un week-end", 2), ("une semaine", 7), ("two nights", 2)],
)
def test_f3_nights_in_words(text, nights):
    assert slots(text)["nights"] == nights


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("TGV", "train"),
        ("Eurostar", "train"),
        ("Ryanair", "flight"),
        ("en avion", "flight"),
        ("covoiturage", "car"),
        ("BlaBlaCar", "car"),
        ("Flixbus", "bus"),
        ("I prefer the train, not the plane", "train"),
        ("pas en avion, en train", "train"),
        ("not by car, by train", "train"),
    ],
)
def test_f3_f9_transport_synonyms_and_negation(text, mode):
    assert slots(text)["transport_mode"] == mode


def test_f9_only_negated_mode_sets_nothing():
    assert "transport_mode" not in slots("not by car")
