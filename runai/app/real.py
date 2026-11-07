"""Adaptateurs des services Linkup, H et Gladia pour l'application."""

import asyncio
import os
import re
from collections.abc import AsyncIterable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hai_agents.tools import Tool, tool

from runai.app.ports import AskUser, EventSink
from runai.app.tasks import extract_budget_per_night
from runai.h.events import to_trace_event
from runai.h.runner import HRun, HRunner
from runai.models import Race, RunnerProfile, StepKind, StepResult, StepStatus
from runai.safety import guard_task
from runai.search.linkup_search import search_race
from runai.search.models import RaceSheet
from runai.voice.audio import load_pcm, pcm_chunks
from runai.voice.live import stream_transcripts

RaceSearchCall = Callable[..., RaceSheet]
TranscriptStream = Callable[..., AsyncIterable[Any]]
_HOTEL_PRICE_TOTAL = re.compile(
    r"\bPRIX_TOTAL_2_NUITS\s*:\s*(?P<price>\d[\d\s.,]*?)\s*(?:EUR|€)",
    re.IGNORECASE,
)


def _njuko_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "njuko.com" or host.endswith(".njuko.com")


class RealRaceSearch:
    def __init__(self, search: RaceSearchCall = search_race):
        self.search = search

    async def find_race(self, query: str) -> Race:
        sheet = await asyncio.to_thread(self.search, query)
        return sheet.to_race()


def ask_user_tool(ask_user: AskUser) -> Tool:
    async def ask_user_callback(question: str, options: list[str]) -> str:
        """Ask the runner for missing information instead of guessing."""
        return await ask_user(question, options)

    return tool(
        ask_user_callback,
        name="ask_user",
        description="Ask the user to choose or provide missing information before proceeding.",
    )


class RealAgentRun:
    def __init__(
        self,
        run: HRun,
        kind: StepKind,
        on_event: EventSink,
        timeout_s: float,
    ):
        self.run = run
        self.kind = kind
        self.on_event = on_event
        self.timeout_s = timeout_s
        self.session_id = run.id

    @property
    def live_view_url(self) -> str | None:
        return self.run.live_view_url or self.run.agent_view_url

    async def pause(self) -> None:
        await self.run.pause()

    async def resume(self) -> None:
        await self.run.resume()

    async def send_message(self, text: str) -> None:
        await self.run.send_message(text)

    async def wait(self) -> StepResult:
        async def forward(event: dict[str, Any]) -> None:
            self.on_event(to_trace_event(event, self.session_id, self.kind.value))

        result = await self.run.wait(on_event=forward, timeout_s=self.timeout_s)
        if self.kind is StepKind.accommodation and result.status is not StepStatus.failed:
            if result.price_eur is None and result.summary:
                match = _HOTEL_PRICE_TOTAL.search(result.summary)
                if match:
                    result.price_eur = extract_budget_per_night(
                        f"{match.group('price')} EUR"
                    )
            if result.price_eur is None:
                result.status = StepStatus.failed
                result.error = (
                    result.error
                    or "Le prix total exact des deux nuits n'est pas vérifiable."
                )
        if result.status is StepStatus.completed:
            result.status = StepStatus.failed
            result.error = (
                result.error
                or "L'agent a terminé sans point d'arrêt avant engagement explicite."
            )
        return result


class RealBrowserAgents:
    def __init__(
        self,
        runner: HRunner | None = None,
        *,
        traces_dir: Path | None = None,
        max_steps: int | None = None,
        max_time_s: float | None = None,
    ):
        self.runner = runner or HRunner(traces_dir=traces_dir)
        self.max_steps = max_steps or int(os.getenv("RUNAI_H_MAX_STEPS", "30"))
        self.max_time_s = max_time_s or float(os.getenv("RUNAI_H_MAX_TIME_S", "240"))

    async def start(
        self,
        kind: StepKind,
        task: str,
        race: Race,
        profile: RunnerProfile,
        on_event: EventSink,
        ask_user: AskUser,
        mission_id: str | None = None,
    ) -> RealAgentRun:
        start_url = None
        if kind is StepKind.registration:
            if not race.registration_url or not _njuko_url(str(race.registration_url)):
                raise RuntimeError(
                    "Lien d'inscription Njuko manquant ; Klikego et les autres plateformes sont interdits."
                )
            start_url = str(race.registration_url)
        run = await self.runner.start(
            kind,
            guard_task(task),
            mission_id=mission_id,
            start_url=start_url,
            max_steps=self.max_steps,
            max_time_s=self.max_time_s,
            tools=[ask_user_tool(ask_user)],
        )
        return RealAgentRun(
            run,
            kind,
            on_event,
            timeout_s=self.max_time_s + 30,
        )


class RealTranscriber:
    def __init__(self, streamer: TranscriptStream = stream_transcripts):
        self.streamer = streamer

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        pcm, sample_rate = await asyncio.to_thread(load_pcm, audio)

        async def chunks():
            async for chunk in pcm_chunks(pcm, sample_rate, realtime=False):
                yield chunk

        transcripts = []
        async for event in self.streamer(chunks(), sample_rate=sample_rate):
            if event.is_final and event.text.strip():
                transcripts.append(event.text.strip())
        result = " ".join(transcripts).strip()
        if not result:
            raise RuntimeError("Gladia n'a renvoyé aucune transcription finale.")
        return result
