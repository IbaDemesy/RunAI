"""Application adapters for Linkup, H and Gladia services."""

import asyncio
import os
import re
from collections.abc import AsyncIterable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hai_agents.tools import Tool, tool
from pydantic import HttpUrl, TypeAdapter, ValidationError

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
from runai.h.answers import answer_schema_for, parse_answer
from runai.h.events import to_trace_event
from runai.h.lifecycle import HLifecycle
from runai.h.runner import HRun, HRunner
from runai.models import (
    Race,
    RunnerProfile,
    StepKind,
    StepResult,
    StepStatus,
    StopPoint,
)
from runai.safety import guard_task
from runai.search.linkup_search import search_race
from runai.search.models import RaceSheet
from runai.voice.audio import load_pcm, pcm_chunks
from runai.voice.live import stream_transcripts

RaceSearchCall = Callable[..., RaceSheet]
TranscriptStream = Callable[..., AsyncIterable[Any]]
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
            typed = answer.model_dump()
            result.data["answer_typed"] = typed
            result.data["options"] = typed.get("options", [])
            result.price_eur = None
            if typed.get("currency") == "EUR":
                result.price_eur = typed.get("total_price", typed.get("price"))
                if self.kind is StepKind.registration and result.price_eur is not None:
                    result.price_eur += typed.get("fees") or 0
            else:
                result.data["price_currency"] = typed.get("currency")
            if answer.final_url:
                try:
                    result.url = TypeAdapter(HttpUrl).validate_python(answer.final_url)
                except ValidationError:
                    pass
            result.summary = answer.summary
            result.stop_point = None
            if answer.stop_screen == "blocked":
                result.status = StepStatus.failed
                result.error = "Blocked by the site"
                if answer.blocker:
                    result.error += f": {answer.blocker}"
                    if re.search(r"captcha|anti[- ]?bot", answer.blocker, re.IGNORECASE):
                        result.error += " (captcha/anti-bot)"
            elif answer.stop_screen == "none":
                result.status = StepStatus.completed
            else:
                result.stop_point = StopPoint({
                    "account": "account_creation",
                    "health": "health_declaration",
                }.get(answer.stop_screen, answer.stop_screen))
                if result.status is not StepStatus.failed:
                    result.status = StepStatus.stopped_before_commitment
        if (
            result.data.get("error_code") == "answer_validation"
            or ("error_code" not in result.data and "answer_validation" in (result.error or ""))
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
    ):
        self.runner = runner or HRunner(traces_dir=traces_dir)
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
            if not race.registration_url or not _njuko_url(str(race.registration_url)):
                raise RuntimeError(
                    "Njuko registration link missing; Klikego and other platforms are forbidden."
                )
            start_url = str(race.registration_url)
            allowed_hosts = platform("njuko").hosts
        else:
            platform_url = getattr(brief, f"{kind.value}_url", None) or start_url
            allowed_hosts = next(
                (candidate.hosts for candidate in PLATFORMS if candidate.kind is kind and host_matches(platform_url, candidate.hosts)),
                (),
            )
        if start_url and (host := urlsplit(start_url).hostname):
            allowed_hosts = tuple(dict.fromkeys((*allowed_hosts, host.lower())))
        job = self.lifecycle.submit(
            kind,
            guard_task(task + "\nAnswer using the requested JSON fields."),
            answer_schema=answer_schema_for(kind),
            mission_id=mission_id,
            start_url=start_url,
            allowed_hosts=allowed_hosts,
            max_steps=self.max_steps,
            max_time_s=self.max_time_s,
            tools=[ask_user_tool(ask_user)],
            timeout_s=self.max_time_s + 30,
            result_wrapper=lambda run: RealAgentRun(run, kind, on_event, self.max_time_s + 30),
        )
        return LifecycleAgentRun(job, self.lifecycle)


class RealTranscriber:
    def __init__(self, streamer: TranscriptStream = stream_transcripts):
        self.streamer = streamer

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        pcm, sample_rate = await asyncio.to_thread(load_pcm, audio)

        async def chunks():
            async for chunk in pcm_chunks(pcm, sample_rate, realtime=True):
                yield chunk

        transcripts = []
        async for event in self.streamer(chunks(), sample_rate=sample_rate):
            if event.is_final and event.text.strip():
                transcripts.append(event.text.strip())
        result = " ".join(transcripts).strip()
        if not result:
            raise RuntimeError("Gladia returned no final transcription.")
        return result
