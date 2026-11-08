import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from runai.contracts.common import DataMode, Provenance
from runai.contracts.framing import FramingSummary
from runai.contracts.journey import Budget, CostLine, JourneyPlan, Money
from runai.journey import (
    HotelChoice,
    JourneyInputs,
    Place,
    RaceDetails,
    TransportChoice,
    build_journey_plan,
)
from runai.models import Race

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/journey"
AT = datetime(2028, 1, 1, tzinfo=UTC)
PROVENANCE = Provenance(kind="fixture", collected_at=AT, label="E1 deterministic")
DESTINATIONS = {
    "berlin_train": ("Berlin", "DE", "Europe/Berlin", "train", 52.52, 13.405),
    "tokyo_flight": ("Tokyo", "JP", "Asia/Tokyo", "flight", 35.68, 139.76),
    "nairobi_incomplete": ("Nairobi", "KE", "Africa/Nairobi", "bus", -1.28, 36.82),
}


def money(amount=50, currency="EUR"):
    return Money(
        amount=amount, currency=currency, collected_at=AT, provenance=PROVENANCE
    )


def scenario(name):
    city, country, tz, mode, lat, lon = DESTINATIONS[name]
    day = date(2028, 6, 12)
    summary = FramingSummary(
        revision=3,
        race=Race(
            name=f"Course {city}",
            city=city,
            country=country,
            race_date=day,
            distance_km=10,
        ),
        origin_public="Lyon",
        date_range=(day - timedelta(days=1), day + timedelta(days=1)),
        nights=2,
        budget_eur=2000,
        transport_mode=mode,
        lines=[],
    )
    home = Place(
        label="Lyon",
        coords={"lat": 45.76, "lon": 4.84},
        timezone="Europe/Paris",
        provenance=PROVENANCE,
    )
    destination = Place(
        label=city, coords={"lat": lat, "lon": lon}, timezone=tz, provenance=PROVENANCE
    )
    start = datetime(2028, 6, 12, 9, tzinfo=ZoneInfo(tz))
    inputs = JourneyInputs(
        home=home,
        race=RaceDetails(
            start=destination, start_time=start, registration_cost=money()
        ),
    )
    if mode != "bus":
        inputs.outbound = TransportChoice(
            mode=mode,
            from_hub=home,
            to_hub=destination,
            depart=start - timedelta(days=1, hours=8),
            arrive=start - timedelta(days=1),
            cost=money(100),
        )
        inputs.return_trip = TransportChoice(
            mode=mode,
            from_hub=destination,
            to_hub=home,
            depart=start + timedelta(days=1),
            arrive=start + timedelta(days=1, hours=8),
            cost=money(110),
        )
        inputs.hotel = HotelChoice(
            place=destination,
            check_in=day - timedelta(days=1),
            check_out=day + timedelta(days=1),
            cost=money(200),
        )
    return summary, inputs


def generate(name, *, inputs=None):
    summary, original = scenario(name)
    return build_journey_plan(
        summary, inputs or original, mission_id=f"e1-{name}", mode=DataMode.demo
    )


@pytest.mark.parametrize("name", DESTINATIONS)
def test_planner_reproduces_shared_json(name):
    expected = json.loads((FIXTURES / f"journey_{name}.json").read_text())
    assert generate(name).model_dump(mode="json") == expected


ALL_FIXTURES = sorted(FIXTURES.glob("journey_*.json")) + sorted(
    (ROOT / "runai/contracts/fixtures").glob("journey_*.json")
)


@pytest.mark.parametrize(
    "path", ALL_FIXTURES, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_shared_fixture_budget_and_references(path):
    plan = JourneyPlan.model_validate_json(path.read_text())
    assert plan.budget.known_total == round(
        sum(line.money.amount for line in plan.budget.lines if line.money), 2
    )
    if not plan.budget.complete:
        assert plan.budget.over_cap is None
    assert all(
        line.money.currency == plan.currency for line in plan.budget.lines if line.money
    )


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("late_arrival", "arrival_after_start"),
        ("early_return", "return_too_early"),
        ("inverted", "transport_times_inverted"),
    ],
)
def test_planner_detects_inconsistent_times(case, code):
    _, inputs = scenario("berlin_train")
    start = inputs.race.start_time
    if case == "late_arrival":
        inputs.outbound.arrive = start + timedelta(hours=1)
    elif case == "early_return":
        inputs.return_trip.depart = start - timedelta(hours=1)
    else:
        inputs.outbound.arrive = inputs.outbound.depart - timedelta(hours=1)
    plan = generate("berlin_train", inputs=inputs)
    if case == "early_return":
        assert code not in {item.code for item in plan.limitations}
        assert any("assumed 6:00/km pace" in warning for warning in plan.warnings)
    else:
        assert code in {item.code for item in plan.limitations}


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Place(label="x", timezone="Europe/Atlantis"),
        lambda: TransportChoice(mode="train", depart=datetime(2028, 6, 11)),
        lambda: RaceDetails(start_time=datetime(2028, 6, 12)),
    ],
)
def test_planner_rejects_invalid_timezone_or_naive_datetime(factory):
    with pytest.raises(ValidationError):
        factory()


def test_foreign_currency_is_not_added_and_missing_price_is_incomplete():
    _, inputs = scenario("tokyo_flight")
    inputs.race.registration_cost = money(9000, "JPY")
    plan = generate("tokyo_flight", inputs=inputs)
    line = next(line for line in plan.budget.lines if line.id == "c-reg")
    assert line.money is None and "JPY" in line.note
    assert plan.budget.known_total == 410 and not plan.budget.complete
    assert plan.budget.over_cap is None
    with pytest.raises(ValidationError):
        Budget(
            lines=[
                CostLine(
                    id="foreign",
                    category="registration",
                    label="Race",
                    money=money(10, "USD"),
                )
            ]
        )
    with pytest.raises(ValidationError):
        money(-1)
    budget = Budget(
        cap=100,
        lines=[CostLine(id="unknown", category="registration", label="Unknown")],
    )
    assert not budget.complete and budget.known_total == 0 and budget.over_cap is None


def test_incomplete_budget_already_above_cap_is_over_cap():
    budget = Budget(
        cap=10,
        lines=[
            CostLine(
                id="known", category="registration", label="Known", money=money(50)
            ),
            CostLine(id="missing", category="local", label="Unknown"),
        ],
    )
    assert budget.complete is False
    assert budget.over_cap is True
