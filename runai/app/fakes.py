"""Recorded demo implementations requiring no credentials or network calls."""

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
        name="Milano Marathon (demo)",
        city="Milan",
        country="IT",
        race_date=date(2027, 4, 11),
        start_time="09:00",
        distance_km=42.195,
        registration_url="https://in.njuko.com/runai-demo-milan",
        bib_pickup="Expo village, the day before (demo data)",
        start_location="Piazza Duomo (demo data)",
        sources=[
            Source(url="https://www.milanomarathon.it", title="Demo source")
        ],
    ),
    "lisbon": Race(
        name="Lisbon 10K (demo)",
        city="Lisbon",
        country="PT",
        race_date=date(2027, 3, 14),
        start_time="10:30",
        distance_km=10,
        registration_url="https://demo.runai.local/lisbon-10k/registration",
        bib_pickup="Race expo, the day before (demo data)",
        start_location="Commerce Square (demo data)",
        sources=[Source(url="https://demo.runai.local/lisbon-10k", title="Demo source")],
    ),
    "tokyo": Race(
        name="Tokyo 10K (demo)", city="Tokyo", country="JP",
        race_date=date(2028, 6, 12), distance_km=10,
        registration_url="https://in.njuko.com/runai-demo-tokyo",
        sources=[Source(url="https://demo.runai.local/tokyo-10k", title="Recorded demo, not a real event")],
    ),
    "valencia": Race(
        name="Valencia Half Marathon (demo)", city="Valencia", country="ES",
        race_date=date(2027, 10, 24), distance_km=21.0975,
        registration_url="https://demo.runai.local/valencia-half/registration",
        sources=[Source(url="https://demo.runai.local/valencia-half", title="Demo source")],
    ),
    "chamonix": Race(
        name="Chamonix Trail 23K (demo)", city="Chamonix", country="FR",
        race_date=date(2027, 7, 18), distance_km=23,
        registration_url="https://demo.runai.local/chamonix-trail/registration",
        sources=[Source(url="https://demo.runai.local/chamonix-trail", title="Demo source")],
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
        raise ValueError("No demo fixture for this city")


@dataclass(frozen=True)
class _Script:
    actions: tuple[tuple[str, str], ...]
    summary: str
    stop_point: StopPoint
    price_eur: float | None


SCRIPTS: dict[StepKind, _Script] = {
    StepKind.registration: _Script(
        actions=(
            ("Open the registration page", ""),
            ("Select the distance", "/distance"),
            (
                "Enter the runner name (demo profile)",
                "/runner",
            ),
            (
                "Enter email and date of birth",
                "/runner",
            ),
            (
                "Reach the rules and medical certificate page",
                "/rules",
            ),
        ),
        summary="Registration form pre-filled — stopped before accepting the rules",
        stop_point=StopPoint.consent,
        price_eur=75.0,
    ),
    StepKind.accommodation: _Script(
        actions=(
            ("Search hotels near the start", "https://demo.runai.local/hotels"),
            (
                "Filter for free cancellation",
                "https://demo.runai.local/hotels?free_cancel=1",
            ),
            (
                "Select the hotel nearest the start",
                "https://demo.runai.local/hotels/42",
            ),
            (
                "Enter guest details (demo profile)",
                "https://demo.runai.local/hotels/42/guest",
            ),
            ("Reach the payment page", "https://demo.runai.local/hotels/42/payment"),
        ),
        summary="Room selected for the night before the race — stopped before payment",
        stop_point=StopPoint.payment,
        price_eur=129.0,
    ),
    StepKind.transport: _Script(
        actions=(
            ("Search for a round trip", "https://demo.runai.local/trains"),
            (
                "Select outbound travel the day before the race",
                "https://demo.runai.local/trains/outbound",
            ),
            ("Select return travel after the finish", "https://demo.runai.local/trains/return"),
            (
                "Enter passenger details (demo profile)",
                "https://demo.runai.local/trains/passenger",
            ),
            ("Reach the payment page", "https://demo.runai.local/trains/payment"),
        ),
        summary="Round trip selected — stopped before payment",
        stop_point=StopPoint.payment,
        price_eur=89.0,
    ),
}

QUESTIONS: dict[StepKind, list[tuple[str, list[str]]]] = {
    StepKind.registration: [
        (
            "Which start corral should I pick?",
            ["Under 3h30", "3h30–4h", "Over 4h"],
        ),
    ],
    StepKind.accommodation: [],
    StepKind.transport: [
        ("Preferred departure time for the confirmed trip (demo)?", ["Morning", "Afternoon"]),
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
        self._emit("message_ack", f"Instruction received: {instruction}")

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
            if self.kind is StepKind.registration:
                base = str(self.race.registration_url) if self.race and self.race.registration_url else "https://demo.runai.local/registration"
                url = base.rstrip("/") + url
            await asyncio.sleep(self._delay)
            await self._resumed.wait()
            self._emit("action", f"Demo — {self.race.name if self.race else 'recorded race'}: {message}", url)
        await asyncio.sleep(self._delay)
        await self._resumed.wait()
        context = f"{self.brief.city} · {self.brief.race_date} · {self.brief.nights} nights" if self.brief else "fixture"
        summary = f"Demo — {context}: {script.summary}"
        if answers:
            summary += f" Your answers: {'; '.join(answers)}."
        if self._messages:
            summary += f" Instructions applied: {'; '.join(self._messages)}."
        return StepResult(
            kind=self.kind,
            status=StepStatus.stopped_before_commitment,
            summary=summary,
            stop_point=script.stop_point,
            url=url,
            price_eur=script.price_eur,
            data={"headline": script.summary, "simulated": True, "provenance": {"mode": "demo", "kind": "fixture"}},
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
    TEXT = "I want to run the Milan marathon, leaving from Paris."

    def __init__(self, delay: float = 0.5):
        self.delay = delay

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        await asyncio.sleep(self.delay)
        return self.TEXT
