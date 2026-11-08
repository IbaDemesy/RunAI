"""Structured reports returned by H browser agents."""

import re
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from runai.app.providers import forbidden_reason
from runai.h.runner import build_step_result
from runai.models import StepKind, StepResult, StepStatus, StopPoint

_HTTP_URL = TypeAdapter(HttpUrl)


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        url = _HTTP_URL.validate_python(value)
        if url.username is not None or url.password is not None:
            return None
        return None if forbidden_reason(str(url)) else str(url)
    except (ValidationError, ValueError):
        return None


class _AnswerModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, populate_by_name=True)


class StepAnswer(_AnswerModel):
    stop_screen: Literal[
        "payment", "account", "health", "consent", "submission", "none", "blocked"
    ] = Field(description="Screen where the agent stopped before any commitment.")
    final_url: str | None = Field(default=None, description="Last visited page URL.")
    offer_url: str | None = Field(default=None, description="Official offer URL, if different from the final page.")
    summary: str = Field(default="", max_length=400, description="Brief factual report in English.")
    blocker: str | None = Field(default=None, description="none, captcha, login_wall, site_error, over_budget, not_found, or a brief blocking reason.")
    fields_filled: list[str] = Field(default_factory=list, description="Fields filled in.")
    questions_for_user: list[str] = Field(default_factory=list, max_length=2, description="At most two questions in English.")

    @field_validator("final_url", "offer_url")
    @classmethod
    def safe_links(cls, value: str | None) -> str | None:
        return _safe_url(value)

    @field_validator("currency", check_fields=False)
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="before")
    @classmethod
    def legacy_eur_currency(cls, value: Any) -> Any:
        total_field = "price" if "price" in cls.model_fields else "total_price"
        component_field = "fees" if total_field == "price" else "price_per_night"
        if (
            isinstance(value, dict)
            and "currency" in cls.model_fields
            and "currency" not in value
            and total_field not in value
            and value.get(component_field) is None
            and f"{total_field}_eur" in value
        ):
            return {**value, "currency": "EUR"}
        return value


class RegistrationAnswer(StepAnswer):
    race: str | None = Field(default=None, validation_alias=AliasChoices("race", "race_label"), description="Race name.")
    distance_km: float | None = Field(default=None, ge=0, description="Race distance in kilometers.")
    price: float | None = Field(default=None, ge=0, validation_alias=AliasChoices("price", "price_eur"), description="Displayed registration price excluding fees.")
    currency: str | None = Field(default=None, description="Displayed currency code.")
    fees: float | None = Field(default=None, ge=0, validation_alias=AliasChoices("fees", "fees_eur"), description="Fees not already included in price; never count them twice.")
    missing_fields: list[str] = Field(default_factory=list, description="Missing required fields.")


class AnswerOption(_AnswerModel):
    name: str | None = Field(default=None, description="Option name.")
    total_price: float | None = Field(default=None, ge=0, description="Displayed total price.")
    url: str | None = Field(default=None, description="Option page URL.")

    @field_validator("url")
    @classmethod
    def safe_link(cls, value: str | None) -> str | None:
        return _safe_url(value)


class AccommodationAnswer(StepAnswer):
    hotel_name: str | None = Field(default=None, description="Hotel name.")
    total_price: float | None = Field(default=None, ge=0, validation_alias=AliasChoices("total_price", "total_price_eur"), description="Exact total price for the entire stay.")
    currency: str | None = Field(default=None, description="Displayed currency code.")
    nights: int | None = Field(default=None, ge=1, description="Number of nights.")
    price_per_night: float | None = Field(default=None, ge=0, validation_alias=AliasChoices("price_per_night", "price_per_night_eur"), description="Price per night.")
    distance_to_start_km: float | None = Field(default=None, ge=0, description="Distance to race start in kilometers.")
    options: list[AnswerOption] = Field(default_factory=list, max_length=3, description="Up to three accommodation options.")


class TransportAnswer(StepAnswer):
    mode: str | None = Field(default=None, description="Mode of transport.")
    operator: str | None = Field(default=None, description="Transport operator.")
    outbound_departure: str | None = Field(default=None, validation_alias=AliasChoices("outbound_departure", "outbound"), description="Outbound departure time.")
    outbound_arrival: str | None = Field(default=None, description="Outbound arrival time.")
    return_departure: str | None = Field(default=None, validation_alias=AliasChoices("return_departure", "inbound"), description="Return departure time.")
    return_arrival: str | None = Field(default=None, description="Return arrival time.")
    total_price: float | None = Field(default=None, ge=0, validation_alias=AliasChoices("total_price", "total_price_eur"), description="Total transport price.")
    currency: str | None = Field(default=None, description="Displayed currency code.")
    options: list[AnswerOption] = Field(default_factory=list, max_length=3, description="Up to three transport options.")


StayAnswer = AccommodationAnswer


def answer_schema_for(kind: StepKind) -> type[StepAnswer]:
    return {
        StepKind.registration: RegistrationAnswer,
        StepKind.accommodation: AccommodationAnswer,
        StepKind.transport: TransportAnswer,
    }.get(kind, StepAnswer)


answer_model = answer_schema_for


def answer_overrides(kind: StepKind) -> dict[str, Any]:
    return {"agent.answer_format": answer_schema_for(kind).model_json_schema()}


def parse_answer(kind: StepKind, raw: Any) -> StepAnswer | None:
    schema = answer_schema_for(kind)
    try:
        if isinstance(raw, str):
            return schema.model_validate_json(raw)
        if isinstance(raw, dict):
            return schema.model_validate(raw)
    except ValidationError:
        pass
    return None


def stop_point_from(answer: StepAnswer) -> StopPoint | None:
    return {
        "payment": StopPoint.payment,
        "account": StopPoint.account_creation,
        "health": StopPoint.health_declaration,
        "consent": StopPoint.consent,
        "submission": StopPoint.submission,
    }.get(answer.stop_screen)


def _has_operational_failure(result: StepResult) -> bool:
    return (
        result.data.get("h_status") in ("failed", "timed_out", "interrupted")
        or result.data.get("outcome") in ("blocked", "infeasible")
        or any(result.data.get(key) for key in ("off_platform", "payment_processor", "error_code"))
    )


def _is_regex_failure(result: StepResult) -> bool:
    if result.data.get("h_status") not in ("completed", "idle"):
        return False
    inferred = build_step_result(
        result.kind, result.data["h_status"], answer=result.data.get("answer"),
    )
    return inferred.status is StepStatus.failed and inferred.error == result.error


def apply_answer(result: StepResult, answer: StepAnswer) -> StepResult:
    typed = answer.model_dump()
    result.data["answer_typed"] = typed
    result.data["options"] = typed.get("options", [])
    if result.url and not _safe_url(str(result.url)):
        result.url = None
    if _has_operational_failure(result) or (
        result.status is StepStatus.failed and not _is_regex_failure(result)
    ):
        result.status = StepStatus.failed
        result.stop_point = None
        return result

    if url := answer.final_url or answer.offer_url:
        result.url = _HTTP_URL.validate_python(url)
    result.summary = answer.summary
    result.price_eur = None
    if typed.get("currency") == "EUR":
        result.price_eur = typed.get("total_price", typed.get("price"))
        if isinstance(answer, RegistrationAnswer) and result.price_eur is not None:
            result.price_eur += answer.fees or 0
    else:
        result.data["price_currency"] = typed.get("currency")

    result.stop_point = stop_point_from(answer)
    blocker = (answer.blocker or "").strip().lower()
    if answer.stop_screen == "blocked" or blocker not in ("", "none"):
        result.status = StepStatus.failed
        result.stop_point = None
        if blocker in ("over_budget", "out_of_budget"):
            result.error = "OVER BUDGET: the displayed price exceeds the agreed budget."
        elif blocker == "site_error":
            result.error = "The provider site failed; no verified offer is available."
        elif blocker == "not_found":
            result.error = "No matching offer was found on the provider site."
        else:
            result.error = "Blocked by the site"
            if answer.blocker:
                result.error += f": {answer.blocker}"
                if blocker == "login_wall" or re.search(r"captcha|anti[-_ ]?bot", blocker):
                    result.error += " (captcha/anti-bot)"
    else:
        result.status = StepStatus.stopped_before_commitment if result.stop_point else StepStatus.completed
        result.error = None
    return result
