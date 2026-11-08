"""Conversational phrasing and extraction, with a local fallback on failure."""

import json
import os
import re
from calendar import month_name
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

import httpx

from runai.contracts.framing import FramingTurn
from runai.framing.interpret import normalize_date_window
from runai.redaction import redact_secrets
from runai.telemetry import timed

H_MODELS_URL = "https://api.hcompany.ai/v1/chat/completions"
MAX_REPLY_CHARS = 420
HISTORY_TURNS = 30

SYSTEM_PROMPT = """You are Holo, RunAI's friendly assistant helping a runner plan race registration, hotels and transport.
You receive optional conversation history, known context and a question to ask.
The question may be a framing question or an agent follow-up; no framing question or history is required.
Understand both French and English input, but always reply in English in one or two short sentences:
- briefly acknowledge the runner's last message when available;
- end with exactly one question: the given question, phrased naturally;
- when the given question already contains options, keep those options verbatim and never add new ones;
- never invent race names, dates, prices, times or availability absent from the context;
- never ask for payment, passwords or health data.
Return only the reply, without quotation marks or a preamble."""


EXTRACT_PROMPT = """Extract travel information from a runner's French or English message.
Return only a JSON object containing these keys only when clearly given:
- "city": race city (one city; use the preferred one if several are mentioned);
- "origin": runner's departure city;
- "race": official event name, only if stated (never a generic distance label such as "10K" or "half marathon");
- "distance_km": a number in kilometers (half marathon=21.0975, marathon=42.195, 10K=10), greater than 0 and at most 400;
- "race_date": ISO yyyy-mm-dd, only when a full date including year is given;
- "edition": edition year (yyyy), within three years of today;
- "date_window": English month name and year, e.g. "April 2027". If year is missing, infer it from today: a month already passed means next year, otherwise this year;
- "budget": total budget in euros (number);
- "nights": number of nights (integer);
- "transport_mode": "train", "flight", "car" or "bus".
Dates must be valid and years within three years of today. Never invent information. Return {} if nothing is given."""

EXTRACTABLE = {"city", "origin", "race", "date_window", "budget", "nights", "transport_mode",
               "distance_km", "race_date", "edition"}
TRANSPORTS = {"train", "flight", "car", "bus"}


class Phraser(Protocol):
    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str: ...

    async def extract(
        self, text: str, known: Mapping[str, str], turns: Sequence[FramingTurn] = ()
    ) -> dict[str, object]: ...


def clean_extraction(raw: object) -> dict[str, object]:
    """Keep plausible, typed values; the engine validates them again."""
    if not isinstance(raw, dict):
        return {}
    values: dict[str, object] = {}
    for name in EXTRACTABLE & raw.keys():
        value = raw[name]
        if name == "date_window":
            if not isinstance(value, str):
                continue
            match = re.fullmatch(r"([A-Za-z]+)(?: (\d{4}))?", normalize_date_window(value.strip()))
            if not match or match[1] not in month_name:
                continue
            today = date.today()
            month = list(month_name).index(match[1])
            year = int(match[2]) if match[2] else today.year + (month < today.month)
            if abs(year - today.year) <= 3:
                values[name] = f"{month_name[month]} {year}"
        elif name in {"city", "origin", "race"}:
            place = name in {"city", "origin"}
            if isinstance(value, str) and 1 < len(value.strip()) <= 80 and not (place and re.search(r"\d", value)):
                values[name] = value.strip()
        elif name == "race_date":
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    continue
                if abs(parsed.year - date.today().year) <= 3:
                    values[name] = value
        elif name == "edition":
            if isinstance(value, str) and re.fullmatch(r"\d{4}", value):
                value = int(value)
            if isinstance(value, int) and not isinstance(value, bool) and abs(value - date.today().year) <= 3:
                values[name] = str(value)
        elif name == "distance_km":
            if isinstance(value, int | float) and not isinstance(value, bool) and 0 < value <= 400:
                values[name] = float(value)
        elif name == "budget":
            if isinstance(value, int | float) and not isinstance(value, bool) and 0 < value < 100_000:
                values[name] = float(value)
        elif name == "nights":
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 30:
                values[name] = value
        elif name == "transport_mode" and isinstance(value, str) and value in TRANSPORTS:
            values[name] = value
    return values


def _user_turns(turns: Sequence[FramingTurn]) -> int:
    return sum(turn.role == "user" for turn in turns)


def _mask_address(text: str) -> str:
    text = re.sub(
        r"\b(?:\d+[a-z]?(?:\s*(?:bis|ter))?\s+)?"
        r"(?:rue|avenue|av\.|boulevard|bd\.|chemin|route|impasse|allée|allee|place)\s+"
        r"[^,;\n\d]+",
        "[redacted address]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b\d+[a-z]?\s+[^,;\n\d]+?\s+"
        r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|drive|way)\b",
        "[redacted address]",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\b\d{5}(?:-\d{4})?\b", "[redacted postcode]", text)


def _history(turns: Sequence[FramingTurn]) -> str:
    return "\n".join(
        ("Runner: " if turn.role == "user" else "Holo: ") + turn.text
        for turn in list(turns)[-HISTORY_TURNS:]
    ) or "(start of conversation)"


class TemplatePhraser:
    """Local, network-free wording for demos and fallback."""

    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str:
        if _user_turns(turns) <= 1:
            opener = "Let's plan this together."
        else:
            opener = "Got it."
        return f"{opener} {question}"

    async def extract(
        self, text: str, known: Mapping[str, str], turns: Sequence[FramingTurn] = ()
    ) -> dict[str, object]:
        return {}


class HoloPhraser:
    """H chat model (OpenAI-compatible Models API), using the agents key."""

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

    async def _complete(self, messages: list[dict[str, str]], max_tokens: int, operation: str = "chat.phrase") -> str:
        messages = [
            {**message, "content": _mask_address(message["content"])}
            if message["role"] != "system" else message
            for message in messages
        ]
        try:
            async with (
                timed("holo", operation, model=self.model, max_tokens=max_tokens) as call,
                httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client,
            ):
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
                data = response.json()
                usage = data.get("usage") if isinstance(data, dict) else None
                if isinstance(usage, dict):
                    call.meta.update({key: value for key, value in usage.items()
                                      if key in {"prompt_tokens", "completion_tokens"}})
                content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return ""
        return content if isinstance(content, str) else ""

    async def extract(
        self, text: str, known: Mapping[str, str], turns: Sequence[FramingTurn] = ()
    ) -> dict[str, object]:
        context = "\n".join(f"- {name}: {value}" for name, value in known.items()) or "- nothing yet"
        content = await self._complete([
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": (
                f"Today: {date.today().isoformat()}\n"
                f"Recent conversation:\n{_history(turns)}\n\nKnown context:\n{context}\n\n"
                f"New message to analyze: {text}"
            )},
        ], 200, operation="chat.extract")
        match = re.search(r"\{.*\}", content, re.DOTALL)
        try:
            return clean_extraction(json.loads(match[0])) if match else {}
        except ValueError:
            return {}

    def _messages(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> list[dict[str, str]]:
        history = _history(turns)
        context = "\n".join(f"- {name}: {value}" for name, value in known.items()) or "- nothing yet"
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Conversation:\n{history}\n\nKnown context:\n{context}\n\nQuestion to ask: {question}",
            },
        ]

    async def phrase(
        self, turns: Sequence[FramingTurn], question: str, known: Mapping[str, str]
    ) -> str:
        content = await self._complete(self._messages(turns, question, known), 200, operation="chat.phrase")
        content = redact_secrets(content.strip().strip('"«» ').strip())
        if not content or len(content) > MAX_REPLY_CHARS or content.count("?") != 1 or not content.endswith("?"):
            return await self._fallback.phrase(turns, question, known)
        return content
