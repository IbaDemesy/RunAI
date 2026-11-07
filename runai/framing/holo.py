"""Reformulation conversationnelle des questions de cadrage.

Le moteur reste maître des slots et de la confirmation : le phraser ne fait
que transformer la prochaine question en une réplique naturelle. Toute erreur
retombe sur une formulation locale, jamais sur un blocage du cadrage.
"""

import os
from collections.abc import Mapping, Sequence
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


class Phraser(Protocol):
    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str: ...


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
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
                response = await client.post(
                    H_MODELS_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "messages": self._messages(turns, question, known),
                        "reasoning_effort": "none",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            content = ""
        if not isinstance(content, str):
            content = ""
        content = redact_secrets(content.strip().strip('"«» ').strip())
        if not content or len(content) > MAX_REPLY_CHARS or "?" not in content:
            return await self._fallback.phrase(turns, question, known)
        return content
