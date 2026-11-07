"""Implémentations factices : la démo tourne de bout en bout sans aucune clé ni appel réseau."""

import asyncio
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date

from runai.app.ports import AskUser, EventSink
from runai.app.tasks import TripBrief
from runai.models import (
    Race,
    RunnerProfile,
    Source,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
    TraceEvent,
)
from runai.safety import STOP_INSTRUCTIONS

DEMO_RACES: dict[str, Race] = {
    "milan": Race(
        name="Milano Marathon (démo)",
        city="Milan",
        country="IT",
        race_date=date(2027, 4, 11),
        start_time="09:00",
        distance_km=42.195,
        registration_url="https://in.njuko.com/runai-demo-milan",
        bib_pickup="Village marathon, la veille (donnée factice)",
        start_location="Piazza Duomo (donnée factice)",
        sources=[
            Source(url="https://example.org/milano-marathon", title="Source factice")
        ],
    ),
    "lisbon": Race(
        name="Lisbon 10K (démo)",
        city="Lisbonne",
        country="PT",
        race_date=date(2027, 3, 14),
        start_time="10:30",
        distance_km=10,
        registration_url="https://example.org/lisbon-10k/inscription",
        bib_pickup="Expo course, la veille (donnée factice)",
        start_location="Praça do Comércio (donnée factice)",
        sources=[Source(url="https://example.org/lisbon-10k", title="Source factice")],
    ),
    "tokyo": Race(
        name="Tokyo 10K (démo)", city="Tokyo", country="JP",
        race_date=date(2028, 6, 12), distance_km=10,
        registration_url="https://in.njuko.com/runai-demo-tokyo",
        sources=[Source(url="https://example.org/tokyo-10k", title="Fixture démo, pas un événement réel")],
    ),
}

_LISBON_WORDS = ("lisbon", "lisbonne", "lisboa")


def _normalize(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    )


class FakeRaceSearch:
    def __init__(self, delay: float = 1.0):
        self.delay = delay

    async def find_race(self, query: str) -> Race:
        await asyncio.sleep(self.delay)
        for key, race in DEMO_RACES.items():
            aliases = _LISBON_WORDS if key == "lisbon" else (key, _normalize(race.city))
            if any(word in _normalize(query) for word in aliases):
                return race.model_copy(deep=True)
        raise ValueError("Pas de fixture démo pour cette ville")


@dataclass(frozen=True)
class _Script:
    actions: tuple[tuple[str, str], ...]
    summary: str
    stop_point: StopPoint
    price_eur: float | None


SCRIPTS: dict[StepKind, _Script] = {
    StepKind.registration: _Script(
        actions=(
            ("Ouverture de la page d'inscription", "https://example.org/inscription"),
            ("Choix de la distance", "https://example.org/inscription/distance"),
            (
                "Saisie du nom et du prénom (profil fictif)",
                "https://example.org/inscription/coureur",
            ),
            (
                "Saisie de l'e-mail et de la date de naissance",
                "https://example.org/inscription/coureur",
            ),
            (
                "Page « Règlement et certificat médical » atteinte",
                "https://example.org/inscription/reglement",
            ),
        ),
        summary="Formulaire pré-rempli ; arrêt avant la case « J'accepte le règlement ».",
        stop_point=StopPoint.consent,
        price_eur=75.0,
    ),
    StepKind.accommodation: _Script(
        actions=(
            ("Recherche d'hôtels près du départ", "https://example.org/hotels"),
            (
                "Filtre : annulation gratuite",
                "https://example.org/hotels?free_cancel=1",
            ),
            (
                "Sélection de l'hôtel le plus proche du départ",
                "https://example.org/hotels/42",
            ),
            (
                "Saisie des coordonnées du voyageur (profil fictif)",
                "https://example.org/hotels/42/guest",
            ),
            ("Page de paiement atteinte", "https://example.org/hotels/42/payment"),
        ),
        summary="Chambre sélectionnée pour la veille de la course ; arrêt avant le paiement.",
        stop_point=StopPoint.payment,
        price_eur=129.0,
    ),
    StepKind.transport: _Script(
        actions=(
            ("Recherche d'un aller-retour", "https://example.org/trains"),
            (
                "Choix de l'aller la veille de la course",
                "https://example.org/trains/outbound",
            ),
            ("Choix du retour après l'arrivée", "https://example.org/trains/return"),
            (
                "Saisie du passager (profil fictif)",
                "https://example.org/trains/passenger",
            ),
            ("Page de paiement atteinte", "https://example.org/trains/payment"),
        ),
        summary="Aller-retour sélectionné ; arrêt avant le paiement.",
        stop_point=StopPoint.payment,
        price_eur=89.0,
    ),
}

QUESTIONS: dict[StepKind, list[tuple[str, list[str]]]] = {
    StepKind.registration: [
        (
            "Quel sas souhaitez-vous examiner (démo) ?",
            ["Découverte", "Performance"],
        ),
        (
            "Quel temps visez-vous ? (pour le sas de départ)",
            ["moins de 3h30", "3h30–4h", "plus de 4h"],
        ),
    ],
    StepKind.accommodation: [],
    StepKind.transport: [
        ("Préférence horaire pour le trajet confirmé (démo) ?", ["matin", "après-midi"]),
    ],
}


class FakeAgentRun:
    def __init__(
        self,
        kind: StepKind,
        task: str,
        on_event: EventSink,
        ask_user: AskUser,
        delay: float,
        query: str = "",
        race: Race | None = None,
        brief: TripBrief | None = None,
    ):
        self.kind = kind
        self.task = task
        self.query = query
        self.race = race
        self.brief = brief
        self.session_id = f"fake-{kind.value}-{uuid.uuid4().hex[:8]}"
        self.live_view_url = f"/demo/live?session={self.session_id}"
        self._on_event = on_event
        self._ask_user = ask_user
        self._delay = delay
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._messages: list[str] = []
        self.received: list[str] = []
        self._task = asyncio.create_task(self._run())

    async def pause(self) -> None:
        self._resumed.clear()

    async def resume(self) -> None:
        self._resumed.set()

    async def send_message(self, text: str) -> None:
        self.received.append(text)
        instruction = text.removesuffix(STOP_INSTRUCTIONS).strip()
        self._messages.append(instruction)
        self._emit("message_ack", f"Consigne reçue : « {instruction} »")

    async def wait(self) -> StepResult:
        return await self._task

    async def cancel(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    def _emit(self, type_: str, message: str, url: str | None = None) -> None:
        data = {"step": self.kind.value, "session_id": self.session_id}
        if url:
            data["url"] = url
        self._on_event(
            TraceEvent(
                source=f"agent:{self.kind.value}",
                type=type_,
                message=message,
                data=data,
            )
        )

    async def _run(self) -> StepResult:
        script = SCRIPTS[self.kind]
        questions = QUESTIONS[self.kind]
        answers = [
            await self._ask_user(question, options)
            for question, options in questions
        ]
        for message, url in script.actions:
            await asyncio.sleep(self._delay)
            await self._resumed.wait()
            self._emit("action", f"Démo — {self.race.name if self.race else 'course de fixture'} : {message}", url)
        await asyncio.sleep(self._delay)
        await self._resumed.wait()
        context = f"{self.brief.city} · {self.brief.race_date} · {self.brief.nights} nuits" if self.brief else "fixture"
        summary = f"Démo — {context} : {script.summary}"
        summary += f" Réponses utilisateur : {' ; '.join(answers)}."
        if self._messages:
            summary += f" Consignes appliquées : {' ; '.join(self._messages)}."
        return StepResult(
            kind=self.kind,
            status=StepStatus.stopped_before_commitment,
            summary=summary,
            stop_point=script.stop_point,
            url=script.actions[-1][1],
            price_eur=script.price_eur,
            data={"simulated": True, "provenance": {"mode": "demo", "kind": "fixture"}},
        )


class FakeBrowserAgents:
    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.runs: list[FakeAgentRun] = []

    async def start(
        self,
        kind: StepKind,
        task: str,
        race: Race,
        profile: RunnerProfile,
        on_event: EventSink,
        ask_user: AskUser,
        mission_id: str | None = None,
        query: str = "",
        start_url: str | None = None,
        brief: TripBrief | None = None,
    ) -> FakeAgentRun:
        run = FakeAgentRun(kind, task, on_event, ask_user, self.delay, query=query, race=race, brief=brief)
        self.runs.append(run)
        return run


class FakeTranscriber:
    TEXT = "Je veux courir le marathon de Milan, je pars de Paris."

    def __init__(self, delay: float = 0.5):
        self.delay = delay

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        await asyncio.sleep(self.delay)
        return self.TEXT
# test
