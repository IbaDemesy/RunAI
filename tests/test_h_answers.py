import json

import pytest

from runai.h.answers import (
    AccommodationAnswer,
    RegistrationAnswer,
    StayAnswer,
    StepAnswer,
    TransportAnswer,
    answer_model,
    answer_overrides,
    answer_schema_for,
    apply_answer,
    parse_answer,
    stop_point_from,
)
from runai.h.runner import build_step_result
from runai.models import StepKind, StepResult, StepStatus, StopPoint


@pytest.mark.parametrize("kind,model", [
    (StepKind.search, StepAnswer),
    (StepKind.registration, RegistrationAnswer),
    (StepKind.accommodation, AccommodationAnswer),
    (StepKind.transport, TransportAnswer),
])
def test_schema_selection_and_optional_fields(kind, model):
    assert answer_schema_for(kind) is model
    assert model.model_json_schema()["required"] == ["stop_screen"]
    assert isinstance(parse_answer(kind, {"stop_screen": "payment"}), model)
    assert isinstance(parse_answer(kind, json.dumps({"stop_screen": "payment"})), model)


@pytest.mark.parametrize("raw", [None, [], 42, "garbage", "[]", {},
                                      {"stop_screen": "unknown"},
                                      {"stop_screen": "payment", "summary": "x" * 601},
                                      {"stop_screen": "payment", "options": [{}] * 4}])
def test_invalid_answers_return_none(raw):
    assert parse_answer(StepKind.accommodation, raw) is None


@pytest.mark.parametrize("kind", list(StepKind))
def test_legacy_helpers_preserve_canonical_schema(kind):
    schema = answer_schema_for(kind).model_json_schema()
    assert answer_model(kind) is answer_schema_for(kind)
    assert answer_overrides(kind) == {"agent.answer_format": schema}
    assert StayAnswer is AccommodationAnswer
    for definition in [schema, *schema.get("$defs", {}).values()]:
        for field in definition["properties"].values():
            for value in field.get("enum", []):
                assert len(value) <= 12
    if kind is StepKind.accommodation:
        assert schema["title"] == "AccommodationAnswer"
        assert {"total_price", "currency", "options"} <= schema["properties"].keys()


@pytest.mark.parametrize("kind,payload,expected", [
    (StepKind.registration,
     {"race_label": "River Run", "price_eur": 50, "fees_eur": 5},
     {"race": "River Run", "price": 50, "fees": 5, "currency": "EUR"}),
    (StepKind.accommodation,
     {"total_price_eur": 180, "price_per_night_eur": 90, "nights": 2},
     {"total_price": 180, "price_per_night": 90, "nights": 2, "currency": "EUR"}),
    (StepKind.transport,
     {"total_price_eur": 70, "outbound": "08:00", "inbound": "19:00"},
     {"total_price": 70, "outbound_departure": "08:00", "return_departure": "19:00", "currency": "EUR"}),
])
def test_legacy_input_aliases_dump_canonical_fields(kind, payload, expected):
    answer = parse_answer(kind, {"stop_screen": "payment", **payload})
    assert answer is not None
    for key, value in expected.items():
        assert answer.model_dump()[key] == value


@pytest.mark.parametrize("payload", [
    {"total_price": -1}, {"total_price": "180"}, {"total_price": True},
    {"total_price": float("nan")}, {"total_price": float("inf")},
    {"nights": 0}, {"nights": 2.5}, {"nights": True},
    {"price_per_night": -1}, {"distance_to_start_km": -1},
    {"summary": "x" * 401}, {"summary": 12},
    {"questions_for_user": ["one", "two", "three"]},
    {"options": [{"total_price": -2}]},
    {"options": [{"total_price": "50"}]}, {"unexpected": "ignored before"},
])
def test_strict_answers_reject_invalid_values(payload):
    raw = {"stop_screen": "payment", **payload}
    assert parse_answer(StepKind.accommodation, raw) is None
    assert parse_answer(StepKind.accommodation, json.dumps(raw)) is None


@pytest.mark.parametrize("url", [
    "https://booking.com/hotel", "https://www.booking.com/hotel",
    "https://name:password@all.accor.com/hotel", "javascript:alert(1)",
    "file:///etc/passwd", "/hotel", "https://[invalid",
])
def test_unsafe_links_are_removed_without_losing_typed_stop(url):
    answer = parse_answer(StepKind.accommodation, {
        "stop_screen": "payment", "final_url": url, "offer_url": url,
        "options": [{"name": "Stay", "url": url}],
    })
    assert answer is not None
    assert answer.final_url is None
    assert answer.offer_url is None
    assert answer.options[0].url is None
    result = apply_answer(StepResult(kind=StepKind.accommodation), answer)
    assert result.url is None


@pytest.mark.parametrize("screen,expected", [
    ("payment", StopPoint.payment), ("account", StopPoint.account_creation),
    ("health", StopPoint.health_declaration), ("consent", StopPoint.consent),
    ("submission", StopPoint.submission), ("none", None), ("blocked", None),
])
def test_stop_point_mapping(screen, expected):
    answer = StepAnswer(stop_screen=screen)
    assert stop_point_from(answer) is expected


def test_apply_answer_sets_canonical_price_options_and_typed_stop():
    answer = AccommodationAnswer(
        stop_screen="account", hotel_name="River Hotel", total_price=180,
        currency=" eur ", summary="Stopped at account creation.",
        offer_url="https://all.accor.com/hotel",
        options=[{"name": "River Hotel", "total_price": 180}],
    )
    result = apply_answer(StepResult(
        kind=StepKind.accommodation, status=StepStatus.completed,
        stop_point=StopPoint.payment,
    ), answer)
    assert result.price_eur == 180
    assert result.stop_point is StopPoint.account_creation
    assert result.status is StepStatus.stopped_before_commitment
    assert str(result.url) == "https://all.accor.com/hotel"
    assert result.summary == answer.summary
    assert result.data["answer_typed"]["hotel_name"] == "River Hotel"
    assert result.data["options"][0]["total_price"] == 180


@pytest.mark.parametrize("kind,payload,total", [
    (StepKind.registration, {"price": 50, "fees": 5}, 55),
    (StepKind.accommodation, {"total_price": 180}, 180),
    (StepKind.transport, {"total_price": 70}, 70),
])
@pytest.mark.parametrize("currency", ["EUR", "USD", None])
def test_only_explicit_eur_prices_reach_price_eur(kind, payload, total, currency):
    answer = parse_answer(kind, {"stop_screen": "payment", "currency": currency, **payload})
    result = apply_answer(StepResult(kind=kind, price_eur=999), answer)
    assert result.price_eur == (total if currency == "EUR" else None)


@pytest.mark.parametrize("blocker,error", [
    ("captcha", "captcha/anti-bot"), ("login_wall", "captcha/anti-bot"),
    ("over_budget", "OVER BUDGET"), ("site_error", "provider site failed"),
    ("not_found", "No matching offer"), ("Login required", "Blocked by the site"),
])
def test_blockers_cannot_be_promoted_to_success(blocker, error):
    result = apply_answer(StepResult(kind=StepKind.transport), TransportAnswer(
        stop_screen="payment", blocker=blocker,
    ))
    assert result.status is StepStatus.failed
    assert result.stop_point is None
    assert error in result.error


@pytest.mark.parametrize("metadata", [
    {"h_status": "failed"}, {"h_status": "timed_out"},
    {"h_status": "interrupted"}, {"outcome": "blocked"},
    {"outcome": "infeasible"}, {"error_code": "answer_validation"},
    {"off_platform": True}, {"payment_processor": True},
])
@pytest.mark.parametrize("status", [StepStatus.failed, StepStatus.completed])
def test_typed_answers_preserve_operational_and_trust_failures(metadata, status):
    result = apply_answer(StepResult(
        kind=StepKind.transport, status=status, error="Original operational failure",
        data=metadata,
    ), TransportAnswer(stop_screen="payment", summary="Stopped safely."))
    assert result.status is StepStatus.failed
    assert result.stop_point is None
    assert result.error == "Original operational failure"
    assert result.data["answer_typed"]["stop_screen"] == "payment"


def test_typed_answers_only_override_failures_inferred_from_raw_text():
    answer = TransportAnswer(
        stop_screen="consent", blocker="none",
        summary="No BLOCAGE CAPTCHA/ANTI-BOT; consent screen reached.",
    )
    result = build_step_result(StepKind.transport, "completed", answer=answer.model_dump())
    assert result.status is StepStatus.failed
    result = apply_answer(result, answer)
    assert result.status is StepStatus.stopped_before_commitment
    assert result.stop_point is StopPoint.consent
    assert result.error is None


def test_unknown_failed_result_stays_failed_without_h_terminal_failure_metadata():
    result = apply_answer(StepResult(
        kind=StepKind.transport, status=StepStatus.failed,
        error="Provider policy refusal", data={"h_status": "completed"},
    ), TransportAnswer(stop_screen="payment"))
    assert result.status is StepStatus.failed
    assert result.error == "Provider policy refusal"
