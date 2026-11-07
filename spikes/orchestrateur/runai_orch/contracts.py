"""Contrats Pydantic : reponses typees des agents H (answer_format) et schemas de l'API."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MissionKind(str, Enum):
    inscription = "inscription"
    hotel = "hotel"
    transport = "transport"


class MissionState(str, Enum):
    queued = "queued"
    running = "running"
    waiting_human = "waiting_human"
    ready_to_pay = "ready_to_pay"
    failed = "failed"
    cancelled = "cancelled"


# --------------------------------------------------------------- answer_format
# Chaque modele est envoye a H via overrides["agent.answer_format"] = Model.model_json_schema().
# Regle commune : ready_for_payment ne vaut true que si la page juste avant paiement est affichee,
# payment_submitted doit toujours rester false (filtre serveur dans orchestrator.check_answer).


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ready_for_payment: bool = Field(description="true seulement si la page juste avant le paiement est affichee a l'ecran")
    payment_submitted: bool = Field(description="doit rester false : l'agent ne paie jamais")
    blocked: bool = Field(description="captcha, mur anti-bot, compte ou vrai email exige")
    current_url: str | None = None
    total_price_eur: float | None = Field(default=None, description="total affiche, en euros")
    missing_fields: list[str] = Field(default_factory=list, description="champs que l'agent n'a pas pu remplir, jamais inventes")
    human_checkboxes: list[str] = Field(default_factory=list, description="cases sante/reglement/RGPD laissees a l'humain")
    note: str = Field(default="", description="une phrase courte")


class InscriptionAnswer(_Answer):
    platform: str | None = Field(default=None, description="Njuko, Klikego, autre")
    race_name: str | None = None
    distance_km: float | None = None
    race_date: date | None = None
    filled_fields: list[str] = Field(default_factory=list)


class HotelAnswer(_Answer):
    hotel_name: str | None = None
    address: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    free_cancellation: bool | None = None
    distance_to_start_km: float | None = None


class TransportAnswer(_Answer):
    mode: Literal["train", "plane", "bus", "other"] | None = None
    carrier: str | None = None
    outbound_departure: str | None = Field(default=None, description="date et heure ISO 8601")
    return_departure: str | None = None
    passengers: int | None = None


ANSWER_MODELS: dict[MissionKind, type[_Answer]] = {
    MissionKind.inscription: InscriptionAnswer,
    MissionKind.hotel: HotelAnswer,
    MissionKind.transport: TransportAnswer,
}


def answer_format(kind: MissionKind) -> dict[str, Any]:
    return ANSWER_MODELS[kind].model_json_schema()


# --------------------------------------------------------------- API


class Runner(BaseModel):
    first_name: str = "Camille"
    last_name: str = "Martin"
    email: str = "camille.martin@example.com"
    birth_date: date = date(1994, 5, 12)


class TripRequest(BaseModel):
    race_name: str = Field(examples=["10 km du Maine Libre"])
    race_url: str | None = None
    race_date: date
    city: str
    distance_km: float | None = None
    origin_city: str = "Paris"
    max_budget_eur: float | None = None
    runner: Runner = Field(default_factory=Runner)
    kinds: list[MissionKind] = Field(default_factory=lambda: list(MissionKind))


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class MissionOut(BaseModel):
    id: str
    trip_id: str
    kind: MissionKind
    state: MissionState
    waiting_reason: str | None = None
    session_id: str | None = None
    live_view_url: str | None = None
    queue_position: int | None = None
    steps: int = 0
    answer: dict[str, Any] | None = None
    error: str | None = None
    created_at: float
    updated_at: float


class TripOut(BaseModel):
    trip_id: str
    missions: list[MissionOut]


class MissionEvent(BaseModel):
    """Un evenement SSE. seq est croissant par mission (sert de Last-Event-ID)."""

    seq: int
    mission_id: str
    ts: float
    type: Literal["state", "step", "screenshot", "live_view", "message", "answer", "error"]
    state: MissionState
    data: dict[str, Any] = Field(default_factory=dict)


class SlotsOut(BaseModel):
    local_limit: int
    local_in_use: int
    queued: list[str]
    h_quota: dict[str, Any] | None = None
