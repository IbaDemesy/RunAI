"""Cadrage assisté : un court échange avec le coureur avant de lancer les agents."""

import asyncio
import json
import os
import re
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from runai.app.tasks import extract_budget_per_night

MAX_QUESTIONS = 3
H_MODELS_URL = "https://api.hcompany.ai/v1/chat/completions"
TRAVEL_TIME_LABEL = "Horaire de départ préféré"
MEDICAL_LABEL = "Justificatif médical"

SYSTEM_PROMPT = f"""Tu es RunAI. Tu cadres en français le déplacement d'un coureur avant de lancer trois agents web (inscription à la course, hôtel, transport) qui s'arrêtent avant tout paiement.
Informations utiles :
- race : la course visée (son nom, ou des critères : distance, mois, région) ; seule information obligatoire ;
- departure_city : la ville de départ du coureur ;
- budget_per_night : le budget hôtel maximal par nuit, en euros (nombre) ;
- travel_time : l'horaire de départ préféré (matin, après-midi, soir) ;
- medical : le justificatif médical (licence, certificat médical, PPS, Runcard, ou « pas encore ») ;
- notes : toute autre contrainte utile (accompagnant, mobilité réduite, préférence d'hôtel…).
Règles :
- Ne redemande jamais une information déjà donnée, même indirectement.
- Pose une seule question courte à la fois, avec deux ou trois exemples de réponses.
- Pose au plus {MAX_QUESTIONS} questions au total. Si la course est floue (« une course en décembre »), commence par la préciser.
- Dès que la course est connue et que les questions importantes ont une réponse, ou si le coureur demande de lancer, mets ready à true et résume le cadrage en une phrase dans reply, en invitant à cliquer sur « Lancer les agents ».
- N'invente rien : mets null pour toute information inconnue.
Réponds uniquement par un objet JSON, sans texte autour :
{{"reply": "...", "ready": false, "scope": {{"race": "...", "departure_city": null, "budget_per_night": null, "travel_time": null, "medical": null, "notes": null}}}}"""
FORCE_CONCLUSION = "Le coureur a assez répondu : mets ready à true maintenant avec les informations connues."


class ScopeError(Exception):
    pass


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class Scope(BaseModel):
    race: str = Field(min_length=3, max_length=300)
    departure_city: str | None = Field(default=None, max_length=100)
    budget_per_night: float | None = Field(default=None, gt=0, le=10000)
    travel_time: str | None = Field(default=None, max_length=100)
    medical: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=300)

    @field_validator(
        "race", "departure_city", "travel_time", "medical", "notes", mode="before"
    )
    @classmethod
    def _clean(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    def search_query(self) -> str:
        return self.model_copy(update={"medical": None}).query()

    def query(self) -> str:
        parts = [self.race.rstrip(".")]
        if self.departure_city:
            parts.append(f"Je pars de {self.departure_city}")
        if self.budget_per_night:
            parts.append(f"Budget hôtel max {self.budget_per_night:g} € par nuit")
        if self.travel_time:
            parts.append(f"{TRAVEL_TIME_LABEL} : {self.travel_time}")
        if self.medical:
            parts.append(f"{MEDICAL_LABEL} : {self.medical}")
        if self.notes:
            parts.append(f"Notes : {self.notes}")
        return ". ".join(parts) + "."


class ScopeTurn(BaseModel):
    reply: str
    ready: bool = False
    scope: Scope | None = None


class Scoper(Protocol):
    async def next_turn(self, messages: list[ChatMessage]) -> ScopeTurn: ...


def _user_turns(messages: list[ChatMessage]) -> int:
    return sum(message.role == "user" for message in messages)


def parse_turn(content: str) -> ScopeTurn:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return ScopeTurn(reply=content.strip() or "Pouvez-vous préciser votre course ?")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ScopeTurn(reply=content.strip())
    reply = str(data.get("reply") or "").strip()
    scope = None
    if isinstance(data.get("scope"), dict) and data["scope"].get("race"):
        try:
            scope = Scope.model_validate(data["scope"])
        except ValidationError:
            scope = None
    ready = bool(data.get("ready")) and scope is not None
    return ScopeTurn(
        reply=reply or "Pouvez-vous préciser votre course ?", ready=ready, scope=scope
    )


class HoloScoper:
    """Modèle de chat de H (API Models, compatible OpenAI), avec la même clé que les agents."""

    def __init__(
        self, api_key: str, *, model: str | None = None, timeout_s: float = 30
    ):
        self._api_key = api_key
        self.model = model or os.getenv("RUNAI_SCOPE_MODEL", "holo4-35b-a3b")
        self._timeout_s = timeout_s

    async def next_turn(self, messages: list[ChatMessage]) -> ScopeTurn:
        payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        payload_messages += [message.model_dump() for message in messages]
        if _user_turns(messages) > MAX_QUESTIONS and messages[-1].role == "user":
            payload_messages[-1] = {
                "role": "user",
                "content": f"{messages[-1].content}\n\n({FORCE_CONCLUSION})",
            }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    H_MODELS_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "messages": payload_messages,
                        "reasoning_effort": "none",
                        "max_tokens": 600,
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            raise ScopeError(f"Modèle de cadrage indisponible : {error}") from error
        return parse_turn(content)


_DEPARTURE = re.compile(
    r"\b(?:je pars d[e']|je partirai d[e']|départ d[e']|au départ d[e']|depuis)\s*(?P<city>[^,.;!?\n]{2,40})",
    re.IGNORECASE,
)
_TRAVEL_TIME = re.compile(r"\b(?:le )?(?:matin|après-midi|soir)\b", re.IGNORECASE)
_LAUNCH = re.compile(r"^\s*(?:go|lance|vas[- ]?y|c'est bon|ok)\b", re.IGNORECASE)
_FAKE_QUESTIONS = (
    ("departure_city", "D'où partez-vous ? Par exemple Paris, Lyon ou Bruxelles."),
    (
        "budget_per_night",
        "Quel budget maximum par nuit pour l'hôtel ? Par exemple 100 €, 150 € ou 200 €.",
    ),
    (
        "medical",
        "Avez-vous déjà un justificatif médical : licence, certificat médical ou PPS ? Ou pas encore ?",
    ),
)


class FakeScoper:
    """Cadrage simulé sans LLM : mêmes questions, aucun crédit consommé."""

    def __init__(self, delay: float = 0.6):
        self.delay = delay

    async def next_turn(self, messages: list[ChatMessage]) -> ScopeTurn:
        await asyncio.sleep(self.delay)
        users = [message.content for message in messages if message.role == "user"]
        if not users:
            return ScopeTurn(reply="Quelle course voulez-vous courir ?")
        race = users[0]
        values: dict[str, object] = {}
        for text in users:
            if match := _DEPARTURE.search(text):
                values["departure_city"] = match.group("city").strip()
                if text is users[0]:
                    race = text[: match.start()] + text[match.end() :]
                    race = re.sub(r"\s*([,;.])(\s*[,;.])+", r"\1", race).strip(" ,.;")
                break
        values["race"] = race if len(race) >= 3 else users[0]
        everything = " ".join(users)
        if match := _TRAVEL_TIME.search(everything):
            values["travel_time"] = match.group(0).lower()
        if (
            budget := extract_budget_per_night(everything, require_context=True)
        ) is not None:
            values["budget_per_night"] = budget
        for index, message in enumerate(messages[:-1]):
            answer = messages[index + 1]
            if message.role != "assistant" or answer.role != "user":
                continue
            for slot, question in _FAKE_QUESTIONS:
                if message.content == question and slot not in values:
                    if slot == "budget_per_night":
                        values[slot] = extract_budget_per_night(answer.content)
                    else:
                        values[slot] = answer.content
        scope = Scope.model_validate(values)
        asked = sum(message.role == "assistant" for message in messages)
        missing = [
            question for slot, question in _FAKE_QUESTIONS if values.get(slot) is None
        ]
        if missing and asked < MAX_QUESTIONS and not _LAUNCH.match(users[-1]):
            return ScopeTurn(reply=missing[0], scope=scope)
        return ScopeTurn(
            reply=f"Parfait : {scope.query()} Cliquez sur « Lancer les agents » quand c'est bon.",
            ready=True,
            scope=scope,
        )
