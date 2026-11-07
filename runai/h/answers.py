"""Structured reports returned by H browser agents."""

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from runai.models import StepKind


class StepAnswer(BaseModel):
    stop_screen: Literal[
        "payment", "account", "health", "consent", "submission", "none", "blocked"
    ] = Field(description="Screen where the agent stopped before any commitment.")
    final_url: str | None = Field(default=None, description="Last visited page URL.")
    summary: str = Field(default="", max_length=600, description="Brief factual report.")
    blocker: str | None = Field(default=None, description="Reason progress was blocked.")
    fields_filled: list[str] = Field(default_factory=list, description="Fields filled in.")


class RegistrationAnswer(StepAnswer):
    race: str | None = Field(default=None, description="Race name.")
    distance_km: float | None = Field(default=None, description="Race distance in kilometers.")
    price: float | None = Field(default=None, description="Displayed registration price excluding fees")
    currency: str | None = Field(default=None, description="Displayed currency code.")
    fees: float | None = Field(default=None, description="Displayed fees not already included in price")
    missing_fields: list[str] = Field(default_factory=list, description="Missing required fields.")


class AnswerOption(BaseModel):
    name: str | None = Field(default=None, description="Option name.")
    total_price: float | None = Field(default=None, description="Displayed total price.")
    url: str | None = Field(default=None, description="Option page URL.")


class AccommodationAnswer(StepAnswer):
    hotel_name: str | None = Field(default=None, description="Hotel name.")
    total_price: float | None = Field(default=None, description="Total price for the stay.")
    currency: str | None = Field(default=None, description="Displayed currency code.")
    nights: int | None = Field(default=None, description="Number of nights.")
    price_per_night: float | None = Field(default=None, description="Price per night.")
    distance_to_start_km: float | None = Field(default=None, description="Distance to race start in kilometers.")
    options: list[AnswerOption] = Field(default_factory=list, max_length=3, description="Up to three accommodation options.")


class TransportAnswer(StepAnswer):
    mode: str | None = Field(default=None, description="Mode of transport.")
    operator: str | None = Field(default=None, description="Transport operator.")
    outbound_departure: str | None = Field(default=None, description="Outbound departure time.")
    outbound_arrival: str | None = Field(default=None, description="Outbound arrival time.")
    return_departure: str | None = Field(default=None, description="Return departure time.")
    return_arrival: str | None = Field(default=None, description="Return arrival time.")
    total_price: float | None = Field(default=None, description="Total transport price.")
    currency: str | None = Field(default=None, description="Displayed currency code.")
    options: list[AnswerOption] = Field(default_factory=list, max_length=3, description="Up to three transport options.")


def answer_schema_for(kind: StepKind) -> type[StepAnswer]:
    return {
        StepKind.registration: RegistrationAnswer,
        StepKind.accommodation: AccommodationAnswer,
        StepKind.transport: TransportAnswer,
    }.get(kind, StepAnswer)


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
