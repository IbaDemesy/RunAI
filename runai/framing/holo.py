"""Reformulation conversationnelle des questions de cadrage.

Le moteur reste maître des slots et de la confirmation : le phraser ne fait
que transformer la prochaine question en une réplique naturelle. Toute erreur
retombe sur une formulation locale, jamais sur un blocage du cadrage.
"""

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

import httpx

from runai.contracts.framing import FramingTurn
from runai.redaction import redact_secrets

H_MODELS_URL = "https://api.hcompany.ai/v1/chat/completions"
MAX_REPLY_CHARS = 420

SYSTEM_PROMPT = """Tu es RunAI, un assistant chaleureux qui aide un coureur à préparer sa course (inscription, hôtel, transport).
On te donne la conversation, ce qui est déjà compris et la prochaine question à poser.
Réponds en français en vouvoyant le coureur, en une ou deux phrases courtes, comme dans une vraie discussion :
- rebondis brièvement sur le dernier message du coureur ;
- termine par la prochaine question, reformulée naturellement, et ne pose que celle-là ;
- n'invente aucun nom de course, date, prix, horaire ou disponibilité qui ne figure pas dans le contexte ;
- ne demande jamais de paiement, de mot de passe ni de donnée médicale.
Réponds uniquement par la réplique, sans guillemets ni préambule."""


EXTRACT_PROMPT = """Tu extrais des informations de voyage d'un message de coureur, en français ou en anglais.
Réponds uniquement par un objet JSON avec, seulement si le message les donne clairement, ces clés :
- "city" : ville de la course (une seule ville ; si plusieurs sont citées avec une préférence, la préférée) ;
- "origin" : ville de départ du coureur ;
- "race" : nom officiel de l'événement s'il est cité ;
- "date_window" : mois et année visés, au format « décembre 2026 » (déduis l'année à partir de la date du jour : le prochain mois correspondant) ;
- "budget" : budget total en euros (nombre) ;
- "nights" : nombre de nuits (entier) ;
- "transport_mode" : "train", "flight", "car" ou "bus".
N'invente rien. Si rien n'est donné, réponds {}."""

EXTRACTABLE = {"city", "origin", "race", "date_window", "budget", "nights", "transport_mode"}
TRANSPORTS = {"train", "flight", "car", "bus"}


class Phraser(Protocol):
    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str: ...

    async def extract(self, text: str, known: Mapping[str, str]) -> dict[str, object]: ...


def clean_extraction(raw: object) -> dict[str, object]:
    """Garde seulement des valeurs plausibles et typées ; le moteur revalide ensuite."""
    if not isinstance(raw, dict):
        return {}
    values: dict[str, object] = {}
    for name in EXTRACTABLE & raw.keys():
        value = raw[name]
        if name in {"city", "origin", "race", "date_window"}:
            if isinstance(value, str) and 1 < len(value.strip()) <= 80 and not re.search(r"\d", value if name != "date_window" else "x"):
                values[name] = value.strip()
        elif name == "budget":
            if isinstance(value, int | float) and not isinstance(value, bool) and 0 < value < 100_000:
                values[name] = float(value)
        elif name == "nights":
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 30:
                values[name] = value
        elif name == "transport_mode" and value in TRANSPORTS:
            values[name] = value
    return values


def _user_turns(turns: Sequence[FramingTurn]) -> int:
    return sum(turn.role == "user" for turn in turns)


class TemplatePhraser:
    """Formulation locale, sans réseau : démo et repli de Holo."""

    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str:
        if _user_turns(turns) <= 1:
            opener = "Avec plaisir, on prépare ça ensemble."
        else:
            opener = "C'est noté."
        return f"{opener} {question}"

    async def extract(self, text: str, known: Mapping[str, str]) -> dict[str, object]:
        return {}


class HoloPhraser:
    """Modèle de chat de H (API Models, compatible OpenAI), avec la clé des agents."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        timeout_s: float = 8,
        fallback: Phraser | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self.model = model or os.getenv("RUNAI_FRAMING_MODEL", "holo4-35b-a3b")
        self._timeout_s = timeout_s
        self._fallback = fallback or TemplatePhraser()
        self._transport = transport

    async def _complete(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
                response = await client.post(
                    H_MODELS_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "reasoning_effort": "none",
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return ""
        return content if isinstance(content, str) else ""

    async def extract(self, text: str, known: Mapping[str, str]) -> dict[str, object]:
        content = await self._complete([
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": f"Date du jour : {date.today().isoformat()}\nMessage : {text}"},
        ], 200)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        try:
            return clean_extraction(json.loads(match[0])) if match else {}
        except ValueError:
            return {}

    def _messages(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> list[dict[str, str]]:
        history = "\n".join(
            ("Coureur : " if turn.role == "user" else "RunAI : ") + turn.text
            for turn in turns[-8:]
        )
        context = "\n".join(f"- {name} : {value}" for name, value in known.items()) or "- rien encore"
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Conversation :\n{history}\n\nDéjà compris :\n{context}\n\nProchaine question : {question}",
            },
        ]

    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str:
        content = await self._complete(self._messages(turns, question, known), 200)
        content = redact_secrets(content.strip().strip('"«» ').strip())
        if not content or len(content) > MAX_REPLY_CHARS or "?" not in content:
            return await self._fallback.phrase(turns, question, known)
        return content
