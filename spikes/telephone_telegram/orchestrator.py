"""Contrat minimal entre les canaux (telephone, Telegram) et l'orchestrateur RunAI, avec un mock.

Le vrai backend (FastAPI de la PWA) exposera les memes operations ; ici tout est simule, aucune session H.
"""

import asyncio
import itertools
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

AGENTS = ("inscription", "hotel", "transport")
AGENT_LABELS = {
    "inscription": "Inscription",
    "hotel": "Hotel Accor",
    "transport": "Transport",
}

FAKE_RUNNER = {
    "first_name": "Camille",
    "last_name": "Martin",
    "email": "camille.martin@example.com",
    "birth_date": "1994-05-12",
}

MONTHS = [
    "janvier",
    "fevrier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
    "décembre",
]
DISTANCES = {
    "semi": "semi-marathon",
    "semi-marathon": "semi-marathon",
    "marathon": "marathon",
    "10 km": "10 km",
    "dix kilometres": "10 km",
    "dix kilomètres": "10 km",
    "trail": "trail",
}


@dataclass
class RaceRequest:
    raw_text: str
    distance: str | None = None
    month: str | None = None
    city: str | None = None

    @property
    def complete(self) -> bool:
        return self.distance is not None and (
            self.month is not None or self.city is not None
        )


def parse_request(text: str) -> RaceRequest:
    low = text.lower()
    req = RaceRequest(text)
    for key, value in sorted(DISTANCES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(key)}\b", low):
            req.distance = value
            break
    for month in MONTHS:
        if re.search(rf"\b{month}\b", low):
            req.month = month.replace("é", "e").replace("û", "u")
            break
    m = re.search(r"\b(?:de|à|a)\s+([A-Z][\w-]+)", text)
    if m and m.group(1).lower() not in MONTHS:
        req.city = m.group(1)
    return req


@dataclass
class AgentUpdate:
    mission_id: str
    agent: str
    status: str  # queued | running | awaiting_validation | ready | refused | failed
    detail: str
    step: int = 0
    screenshot_png: bytes | None = None


@dataclass
class Mission:
    id: str
    request: RaceRequest
    channel: str
    user_ref: str
    race: dict = field(default_factory=dict)
    statuses: dict = field(default_factory=lambda: {a: "queued" for a in AGENTS})
    decisions: dict = field(default_factory=dict)


class Orchestrator(Protocol):
    async def start_mission(
        self, text: str, channel: str, user_ref: str
    ) -> Mission: ...
    def updates(self, mission_id: str) -> AsyncIterator[AgentUpdate]: ...
    async def decide(
        self, mission_id: str, agent: str, approved: bool
    ) -> AgentUpdate: ...


# 1x1 PNG gris : remplace la capture d'ecran H (live_view / screenshot) dans le mock
PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63f8cfc0f01f0005000201a5f7ad9a0000000049454e44ae426082"
)


class MockOrchestrator:
    """Simule 3 agents H en parallele. `step_delay` court en test ; ~10 min en vrai (non simule)."""

    def __init__(self, step_delay: float = 0.5):
        self.step_delay = step_delay
        self.missions: dict[str, Mission] = {}
        self._ids = itertools.count(1)

    async def start_mission(self, text: str, channel: str, user_ref: str) -> Mission:
        req = parse_request(text)
        mission = Mission(f"m{next(self._ids):04d}", req, channel, user_ref)
        mission.race = {
            "name": f"Semi-marathon de Paris ({req.distance or 'distance a confirmer'})",
            "date": "2027-04-04",
            "start_time": "09:00",
            "city": req.city or "Paris",
            "start_lat": 48.8698,
            "start_lon": 2.3077,
            "source": "mock (Linkup non appele)",
        }
        self.missions[mission.id] = mission
        return mission

    async def updates(self, mission_id: str) -> AsyncIterator[AgentUpdate]:
        mission = self.missions[mission_id]
        script = [
            ("inscription", "running", "Ouverture de la page officielle"),
            ("hotel", "running", "Recherche Accor pres du depart"),
            ("transport", "running", "Recherche de trains/vols"),
            ("inscription", "running", "Formulaire rempli (donnees fictives)"),
            (
                "hotel",
                "awaiting_validation",
                "ibis Paris, 2 nuits, 185 EUR : page avant paiement",
            ),
            (
                "transport",
                "awaiting_validation",
                "Aller-retour 103 EUR : page passagers",
            ),
            (
                "inscription",
                "awaiting_validation",
                "Cases sante/reglement a cocher par toi, puis paiement",
            ),
        ]
        for step, (agent, status, detail) in enumerate(script, 1):
            await asyncio.sleep(self.step_delay)
            mission.statuses[agent] = status
            shot = PLACEHOLDER_PNG if status == "awaiting_validation" else None
            yield AgentUpdate(mission_id, agent, status, detail, step, shot)

    async def decide(self, mission_id: str, agent: str, approved: bool) -> AgentUpdate:
        mission = self.missions[mission_id]
        mission.decisions[agent] = approved
        status = "ready" if approved else "refused"
        mission.statuses[agent] = status
        detail = (
            "Lien de paiement pret : c'est toi qui paies"
            if approved
            else "Agent arrete, rien n'est soumis"
        )
        return AgentUpdate(mission_id, agent, status, detail)
