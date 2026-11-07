"""Implémentations factices : la démo tourne de bout en bout sans aucune clé ni appel réseau."""

import asyncio
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date

from runai.app.ports import EventSink
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

DEMO_RACES: dict[str, Race] = {
    "milan": Race(
        name="Milano Marathon (démo)",
        city="Milan",
        country="IT",
        race_date=date(2027, 4, 11),
        start_time="09:00",
        distance_km=42.195,
        registration_url="https://example.org/milano-marathon/inscription",
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
        key = (
            "lisbon"
            if any(word in _normalize(query) for word in _LISBON_WORDS)
            else "milan"
        )
        return DEMO_RACES[key].model_copy(deep=True)


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


class FakeAgentRun:
    def __init__(self, kind: StepKind, task: str, on_event: EventSink, delay: float):
        self.kind = kind
        self.task = task
        self.session_id = f"fake-{kind.value}-{uuid.uuid4().hex[:8]}"
        self.live_view_url = f"/demo/live?session={self.session_id}"
        self._on_event = on_event
        self._delay = delay
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._messages: list[str] = []
        self._task = asyncio.create_task(self._run())

    async def pause(self) -> None:
        self._resumed.clear()

    async def resume(self) -> None:
        self._resumed.set()

    async def send_message(self, text: str) -> None:
        self._messages.append(text)
        self._emit("message_ack", f"Consigne reçue : « {text} »")

    async def wait(self) -> StepResult:
        return await self._task

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
        for message, url in script.actions:
            await asyncio.sleep(self._delay)
            await self._resumed.wait()
            self._emit("action", message, url)
        await asyncio.sleep(self._delay)
        await self._resumed.wait()
        summary = script.summary
        if self._messages:
            summary += f" Consignes appliquées : {' ; '.join(self._messages)}."
        return StepResult(
            kind=self.kind,
            status=StepStatus.stopped_before_commitment,
            summary=summary,
            stop_point=script.stop_point,
            url=script.actions[-1][1],
            price_eur=script.price_eur,
            data={"simulated": True},
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
    ) -> FakeAgentRun:
        run = FakeAgentRun(kind, task, on_event, self.delay)
        self.runs.append(run)
        return run


class FakeTranscriber:
    TEXT = "Je veux courir le marathon de Milan, je pars de Paris."

    def __init__(self, delay: float = 0.5):
        self.delay = delay

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        await asyncio.sleep(self.delay)
        return self.TEXT
