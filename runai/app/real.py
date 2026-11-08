"""Application adapters for Linkup, H and Gladia services."""

import asyncio
import os
import re
from collections.abc import AsyncIterable, AsyncIterator, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hai_agents.tools import Tool, tool
from pydantic import BaseModel

from runai.app.ports import AskUser, EventSink
from runai.app.providers import (
    PLATFORMS,
    forbidden_reason,
    host_matches,
    platform,
    provenance_data,
)
from runai.app.tasks import extract_budget_per_night
from runai.contracts.common import DataMode, ProvenanceKind
from runai.h.answers import answer_schema_for, apply_answer, parse_answer
from runai.h.events import to_trace_event
from runai.h.lifecycle import HLifecycle
from runai.h.runner import HRun, HRunner
from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    TraceEvent,
)
from runai.safety import guard_task
from runai.search.answers import answer_official, format_for_agent, official_domains
from runai.search.linkup_search import SearchClient, default_client, search_race
from runai.search.models import RaceSheet
from runai.voice.audio import load_pcm, pcm_chunks
from runai.voice.live import stream_voice_events

RaceSearchCall = Callable[..., RaceSheet]
TranscriptStream = Callable[..., AsyncIterator[BaseModel]]
_HOTEL_PRICE_TOTAL = re.compile(
    r"\bPRIX_TOTAL_(?:\d+_NUITS|SEJOUR)\s*:\s*(?P<price>\d[\d\s.,]*?)\s*(?:EUR|€)",
    re.IGNORECASE,
)


def _njuko_url(url: str) -> bool:
    return host_matches(url, platform("njuko").hosts)


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


LOOKUP_OFFICIAL_INFO_DESCRIPTION = (
    "Look up race rules on the official site (medical certificate, bib pick-up, cut-off times, fees) "
    "before asking the user. Returns a short cited answer from the race's official pages only."
)
_NO_OFFICIAL_SITE = "No official race website is known; ask the user with ask_user instead."
MAX_OFFICIAL_LOOKUPS = 5  # paid Linkup calls per agent run
_LOOKUP_LIMIT = "Official lookup limit reached for this run; ask the user with ask_user instead."


def lookup_official_info_tool(
    race: Race,
    on_event: EventSink,
    client: Callable[[], SearchClient] = default_client,
) -> Tool:
    calls = 0
    answers: dict[str, str] = {}

    async def lookup_official_info(question: str) -> str:
        """Look up race rules on the official site before asking the user."""
        nonlocal calls
        domains = official_domains(race)
        if not domains:
            return _NO_OFFICIAL_SITE
        key = " ".join(question.casefold().split())
        if key in answers:
            return answers[key]
        if calls >= MAX_OFFICIAL_LOOKUPS:
            return _LOOKUP_LIMIT
        calls += 1
        try:
            answer = await asyncio.to_thread(
                answer_official, question, domains, client(), race=race
            )
        except Exception as error:  # noqa: BLE001 - a failed lookup must never crash the H session
            return f"Official lookup failed ({type(error).__name__}); ask the user with ask_user instead."
        if answer is None:
            return _NO_OFFICIAL_SITE
        on_event(
            TraceEvent(
                source="linkup",
                type="linkup_answer",
                message=question,
                data=answer.model_dump(mode="json"),
            )
        )
        answers[key] = format_for_agent(answer)
        return answers[key]

    return tool(
        lookup_official_info,
        name="lookup_official_info",
        description=LOOKUP_OFFICIAL_INFO_DESCRIPTION,
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
        return self.run.live_view_url

    @property
    def agent_view_url(self) -> str | None:
        return getattr(self.run, "agent_view_url", None)

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
        answer = parse_answer(self.kind, result.data.get("answer"))
        if answer is not None:
            result = apply_answer(result, answer)
        if (
            result.data.get("error_code") == "answer_validation"
            or (not result.data.get("error_code") and "answer_validation" in (result.error or ""))
        ):
            result.data["error_user"] = (
                "The agent finished but its report did not match the expected format."
            )
        if self.kind is StepKind.accommodation and result.status is not StepStatus.failed:
            if answer is None and result.price_eur is None and result.summary:
                match = _HOTEL_PRICE_TOTAL.search(result.summary)
                if match:
                    result.price_eur = extract_budget_per_night(
                        f"{match.group('price')} EUR"
                    )
            if result.price_eur is None:
                result.status = StepStatus.failed
                result.error = (
                    result.error
                    or "The exact total accommodation price cannot be verified."
                )
        if result.status is StepStatus.completed:
            result.status = StepStatus.failed
            result.error = (
                result.error
                or "The agent finished without an explicit stop before commitment."
            )
        result.data = {
            **result.data,
            "provenance": provenance_data(
                DataMode.live,
                ProvenanceKind.h_agent,
                f"Live H agent (session {self.session_id})",
                url=str(result.url) if result.url else None,
            ),
        }
        return result


class LifecycleAgentRun:
    def __init__(self, job, lifecycle: HLifecycle):
        self.job = job
        self.lifecycle = lifecycle

    @property
    def session_id(self):
        return self.job.h_session_id

    @property
    def live_view_url(self):
        run = self.job.run
        return run.live_view_url if run else None

    @property
    def agent_view_url(self):
        return getattr(self.job.run, "agent_view_url", None)

    @property
    def browser_observation(self):
        return getattr(self.job.run, "browser_observation", None)

    async def get_screenshot(self):
        return await self.job.run.get_screenshot() if self.job.run else None

    async def pause(self):
        await self.lifecycle.pause(self.job.job_id)

    async def resume(self):
        await self.lifecycle.resume(self.job.job_id)

    async def send_message(self, text):
        if self.job.run is None:
            raise RuntimeError("H session is still queued; retry after it starts.")
        await self.job.run.send_message(text)

    async def wait(self):
        return await self.job.wait()

    async def cancel(self):
        await self.lifecycle.cancel(self.job.job_id)


class RealBrowserAgents:
    def __init__(
        self,
        runner: HRunner | None = None,
        *,
        traces_dir: Path | None = None,
        max_steps: int | None = None,
        max_time_s: float | None = None,
        answer_client: Callable[[], SearchClient] = default_client,
    ):
        self.runner = runner or HRunner(traces_dir=traces_dir)
        self.answer_client = answer_client
        self.max_steps = max_steps or int(os.getenv("RUNAI_H_MAX_STEPS", "60"))
        self.max_time_s = max_time_s or float(os.getenv("RUNAI_H_MAX_TIME_S", "900"))
        self.lifecycle = HLifecycle(self.runner)

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
        brief=None,
    ) -> RealAgentRun:
        if start_url and (reason := forbidden_reason(start_url)):
            raise RuntimeError(f"Start URL rejected: {reason}.")
        if kind is StepKind.registration:
            start_url = str(race.registration_url) if race.registration_url else start_url
            if not start_url:
                raise RuntimeError("Official registration link missing: use the organiser's site.")
            if reason := forbidden_reason(start_url):
                raise RuntimeError(f"Registration link rejected: {reason}.")
            # Njuko stays pinned to Njuko. An organiser's site usually hands over to its own registration
            # platform on another domain, so no host allowlist there: forbidden sites and payment pages
            # still stop the agent at once (host drift guard).
            allowed_hosts = platform("njuko").hosts if _njuko_url(start_url) else None
        else:
            platform_url = getattr(brief, f"{kind.value}_url", None) or start_url
            allowed_hosts = next(
                (candidate.hosts for candidate in PLATFORMS if candidate.kind is kind and host_matches(platform_url, candidate.hosts)),
                (),
            )
        if allowed_hosts is not None and start_url and (host := urlsplit(start_url).hostname):
            allowed_hosts = tuple(dict.fromkeys((*allowed_hosts, host.lower())))
        typed_enabled = os.getenv("RUNAI_H_TYPED_ANSWERS", "1") != "0"
        job = self.lifecycle.submit(
            kind,
            guard_task(task + ("\nAnswer using the requested JSON fields." if typed_enabled else "")),
            answer_schema=answer_schema_for(kind) if typed_enabled else None,
            mission_id=mission_id,
            start_url=start_url,
            allowed_hosts=allowed_hosts,
            max_steps=self.max_steps,
            max_time_s=self.max_time_s,
            tools=[
                ask_user_tool(ask_user),
                lookup_official_info_tool(race, on_event, self.answer_client),
            ],
            timeout_s=self.max_time_s + 30,
            result_wrapper=lambda run: RealAgentRun(run, kind, on_event, self.max_time_s + 30),
        )
        return LifecycleAgentRun(job, self.lifecycle)


class RealTranscriber:
    def __init__(self, streamer: TranscriptStream = stream_voice_events):
        self.streamer = streamer

    def stream(self, chunks: AsyncIterable[bytes], sample_rate: int) -> AsyncIterator[BaseModel]:
        return self.streamer(chunks, sample_rate=sample_rate)

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        pcm, sample_rate = await asyncio.to_thread(load_pcm, audio)

        async def chunks():
            async for chunk in pcm_chunks(pcm, sample_rate, realtime=True):
                yield chunk

        transcripts = []
        async for event in self.streamer(chunks(), sample_rate=sample_rate):
            if getattr(event, "is_final", False) and event.text.strip():
                transcripts.append(event.text.strip())
        result = " ".join(transcripts).strip()
        if not result:
            raise RuntimeError("Gladia returned no final transcription.")
        return result
