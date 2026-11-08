"""FastAPI backend: mission API, SSE streams and handoff web page."""

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from runai.app import voice_ws
from runai.app.auth import BasicAuthMiddleware
from runai.app.candidates import FixtureCandidateSearch, UnavailableCandidateSearch
from runai.app.fakes import DEMO_RACES
from runai.app.headers import SecurityHeadersMiddleware
from runai.app.history import DEFAULT_LIMIT, MAX_LIMIT, list_summaries, summarize
from runai.app.mission import MissionError, MissionNotFound, MissionService
from runai.app.profile import ProfileStore
from runai.app.providers import (
    ProviderSet,
    ProviderStatus,
    build_providers,
    provider_health,
)
from runai.app.replay_export import export_replay
from runai.app.screenshots import build_screenshot_router
from runai.app.tasks import STEP_LABELS
from runai.app.telemetry import router as telemetry_router
from runai.config import get_settings
from runai.contracts.common import DataMode
from runai.contracts.framing import USER_ID_PATTERN
from runai.contracts.mission import HumanAnswer, MissionStatusV2
from runai.framing.api import build_framing_router
from runai.framing.engine import FramingEngine
from runai.framing.holo import HoloPhraser, Phraser, TemplatePhraser
from runai.h.human_questions import HumanQuestionError
from runai.logging_setup import RequestIdMiddleware, configure_logging, request_id
from runai.models import RunnerProfile, StepKind
from runai.planning import recap_adapter
from runai.redaction import redact_secrets
from runai.search.candidates import LinkupCandidateSearch
from runai.search.linkup_search import default_client
from runai.search.logistics_sweep import LinkupLogisticsSweeper

STATIC_DIR = Path(__file__).parent / "static"
ROOT_DIR = Path(__file__).resolve().parents[2]
KEEPALIVE_SECONDS = 15
MAX_AUDIO_BYTES = 10 * 1024 * 1024
logger = logging.getLogger("runai.app")


class MissionRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ProfileRequest(RunnerProfile):
    model_config = ConfigDict(extra="forbid", str_max_length=256)

    confirm_real_data: StrictBool = False

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email address")
        return value


def profile_response(profile: RunnerProfile) -> dict:
    data = profile.model_dump(mode="json")
    for field in ("license_number", "pps_number"):
        if data[field]:
            data[field] = "[REDACTED]"
    return redact_secrets(data)


def build_demo_service(delay: float | None = None) -> MissionService:
    return build_service(mode=DataMode.demo, delay=delay)


def build_service(mode: DataMode | None = None, delay: float | None = None) -> MissionService:
    settings = get_settings()
    providers = build_providers(mode, delay=delay, traces_dir=settings.traces_dir)
    agents = providers.agents
    timeout = float(os.getenv("RUNAI_QUESTION_TIMEOUT_S", "600"))
    if hasattr(agents, "max_time_s"):
        timeout = min(timeout, max(1, agents.max_time_s - 60))
    service = MissionService(
        providers.search, agents, providers.transcriber,
        traces_dir=settings.traces_dir,
        profile=ProfileStore(settings.traces_dir / "profile.json").load(),
        # Agents simulés : aucun slot H à partager, les missions ne s'attendent pas.
        max_concurrency=None if providers.simulated else settings.h_max_concurrency,
        simulated=providers.simulated, question_timeout_s=timeout,
        sweeper=LinkupLogisticsSweeper(default_client())
        if providers.mode is DataMode.live and providers.health["linkup"].status is ProviderStatus.ok
        else None,
    )
    service.providers = providers
    return service


def candidate_search(providers: ProviderSet):
    if providers.mode is DataMode.demo:
        return FixtureCandidateSearch(list(DEMO_RACES.values()), DataMode.demo)
    if providers.mode is DataMode.replay:
        race = providers.search.trace.race
        return FixtureCandidateSearch([race] if race else [], DataMode.replay)
    health = providers.health["linkup"]
    if health.status is not ProviderStatus.ok:
        return UnavailableCandidateSearch(health.detail)
    return LinkupCandidateSearch()


def framing_phraser(providers: ProviderSet) -> Phraser:
    """Use Holo to rephrase live questions when an H key is available, otherwise use templates."""
    key = get_settings().hai_api_key
    if providers.mode is DataMode.live and key and os.getenv("RUNAI_FRAMING_LLM", "1") != "0":
        return HoloPhraser(key)
    return TemplatePhraser()


def app_version() -> str:
    return (os.getenv("RENDER_GIT_COMMIT") or "")[:7] or "dev"


def create_app(service: MissionService | None = None) -> FastAPI:
    configure_logging()
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    selected = service or build_service()
    if selected.providers is None:
        selected.providers = ProviderSet(
            DataMode.demo if selected.simulated else DataMode.live,
            selected.search, selected.agents, selected.transcriber, provider_health(),
        )
    if selected.phraser is None:
        selected.phraser = framing_phraser(selected.providers)

    @asynccontextmanager
    async def lifespan(app):
        selected.rehydrate()
        yield
        for mission in list(selected.missions.values()):
            if not mission.is_terminal:
                await selected.cancel(mission.id)
        lifecycle = getattr(selected.agents, "lifecycle", None)
        if lifecycle:
            await lifecycle.aclose()

    public_without_auth = os.getenv("RUNAI_PUBLIC") == "1" and not os.getenv("RUNAI_BASIC_AUTH")
    if public_without_auth and not selected.simulated:
        raise RuntimeError(
            "RUNAI_PUBLIC=1 in live mode: set RUNAI_BASIC_AUTH or anyone can use your credits"
        )
    app = FastAPI(title="RunAI", lifespan=lifespan)
    if credentials := os.getenv("RUNAI_BASIC_AUTH"):
        app.add_middleware(BasicAuthMiddleware, credentials=credentials)
    app.add_middleware(SecurityHeadersMiddleware, enforce=os.getenv("RUNAI_CSP_ENFORCE") == "1")
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return JSONResponse(redact_secrets({"detail": error.detail}), status_code=error.status_code,
                            headers=redact_secrets(error.headers))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        detail = json.dumps(redact_secrets(jsonable_encoder(error.errors())), ensure_ascii=False)
        return JSONResponse({"detail": detail}, status_code=422)
    app.state.service = selected
    engine = FramingEngine(
        search=candidate_search(selected.providers), mode=selected.providers.mode,
        phraser=selected.phraser,
    )
    app.state.framing = engine
    app.include_router(build_framing_router(engine, selected.confirm))
    app.include_router(build_screenshot_router(selected))
    app.include_router(telemetry_router)
    app.include_router(voice_ws.router)
    app.mount("/static/contract-fixtures", StaticFiles(directory=ROOT_DIR / "runai/contracts/fixtures"), name="contract-fixtures")
    app.mount("/static/flyover", StaticFiles(directory=ROOT_DIR / "web/flyover"), name="flyover")
    app.mount("/static/voice", StaticFiles(directory=ROOT_DIR / "web/voice"), name="voice")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def get_service() -> MissionService:
        return app.state.service

    @app.get("/api/profile")
    async def get_profile() -> dict:
        profile = get_service().profile
        if public_without_auth and not profile.fictional:
            profile = RunnerProfile()
        return profile_response(profile)

    @app.put("/api/profile")
    async def put_profile(body: ProfileRequest) -> dict:
        if public_without_auth and (
            body.confirm_real_data or body.email.rsplit("@", 1)[-1].lower() != "example.com"
        ):
            raise HTTPException(403, "Real profiles require authentication on a public app")
        if body.email.rsplit("@", 1)[-1].lower() != "example.com" and not body.confirm_real_data:
            raise HTTPException(422, "Confirm real data before sharing it with H agents")
        profile = RunnerProfile.model_validate(body.model_dump(exclude={"confirm_real_data", "fictional"}))
        profile.fictional = not body.confirm_real_data
        service = get_service()
        for field in ("license_number", "pps_number"):
            if getattr(profile, field) == "[REDACTED]":
                setattr(profile, field, None if public_without_auth else getattr(service.profile, field))
        path = service.traces_dir if service.traces_dir is not None else get_settings().traces_dir
        ProfileStore(path / "profile.json").save(profile)
        service.profile = profile
        return profile_response(profile)

    @app.get("/api/prefill")
    async def prefill(user_id: str | None = None) -> dict:
        missions = [mission for mission in get_service().missions.values()
                    if mission.plan is not None
                    and (user_id is None or getattr(mission, "user_id", None) == user_id)]
        if not missions:
            raise HTTPException(404, "No confirmed brief found")
        latest = max(missions, key=lambda mission: mission.created_at)
        return redact_secrets(latest.plan.brief.model_dump(mode="json", include={
            "origin", "transport_mode", "budget_total_eur", "nights", "preferences",
        }))

    def handle(error: MissionError) -> HTTPException:
        return HTTPException(
            status_code=404 if isinstance(error, MissionNotFound) else 409, detail=redact_secrets(str(error))
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/demo/live", include_in_schema=False)
    async def demo_live() -> FileResponse:
        return FileResponse(STATIC_DIR / "live.html")

    @app.get("/api/health")
    async def health() -> dict:
        service = get_service()
        payload = service.providers.health_payload()
        payload.update(
            uptime_s=round(time.monotonic() - started, 1),
            version=app_version(),
            started_at=started_at,
            active_missions=sum(1 for mission in service.missions.values() if not mission.is_terminal),
        )
        return redact_secrets(payload)

    @app.post("/api/missions", status_code=410)
    async def create_mission(body: MissionRequest) -> dict:
        raise HTTPException(410, "Create and confirm framing via /api/framings before launching agents.")

    @app.get("/api/missions")
    async def list_missions(
        user_id: str = Query(pattern=USER_ID_PATTERN),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        status: MissionStatusV2 | None = None,
    ) -> list[dict]:
        summaries = list_summaries(
            list(get_service().missions.values()), user_id=user_id, status=status, limit=limit
        )
        return [summary.model_dump(mode="json") for summary in summaries]

    @app.get("/api/missions/{mission_id}/summary")
    async def mission_summary(mission_id: str) -> dict:
        mission = get_service().missions.get(mission_id)
        if mission is None:
            raise HTTPException(404, "Unknown mission")
        return summarize(mission).model_dump(mode="json")

    @app.get("/api/missions/{mission_id}")
    async def get_mission(mission_id: str) -> dict:
        try:
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.get("/api/missions/{mission_id}/replay.json")
    async def replay_export(mission_id: str) -> JSONResponse:
        try:
            mission = get_service().get(mission_id)
        except MissionError:
            raise HTTPException(404, "Unknown mission") from None
        if not mission.is_terminal:
            raise HTTPException(409, "Mission is not terminal")
        return JSONResponse(export_replay(mission).model_dump(mode="json"), headers={
            "Content-Disposition": f'attachment; filename="{mission.id}.replay.json"',
        })

    @app.get("/api/missions/{mission_id}/events")
    async def mission_events(mission_id: str, request: Request) -> StreamingResponse:
        service = get_service()
        try:
            mission = service.get(mission_id)
            cursor = request.headers.get("last-event-id")
            if cursor:
                prefix, _, raw = cursor.rpartition(":")
                if not prefix or not raw.isascii() or not raw.isdigit() or len(raw) > 20:
                    raise HTTPException(400, "Invalid Last-Event-ID")
                if prefix != mission_id or not 0 <= int(raw) <= len(mission.envelopes):
                    raise MissionError("Invalid Last-Event-ID")
        except MissionError as error:
            raise handle(error) from None

        rid = request_id()

        async def stream():
            opened = time.monotonic()
            events_sent = 0
            last_event_id = request.headers.get("last-event-id")
            log_extra = {"request_id": rid, "mission_id": mission_id}
            logger.info("sse_open", extra={**log_extra, "last_event_id": last_event_id})
            messages = service.subscribe_events(mission_id, request.headers.get("last-event-id"))
            pending = asyncio.ensure_future(anext(messages))
            try:
                while True:
                    done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_SECONDS)
                    if await request.is_disconnected():
                        break
                    if not done:
                        yield ": keepalive\n\n"
                        continue
                    try:
                        event = pending.result()
                    except StopAsyncIteration:
                        break
                    yield event.to_sse()
                    events_sent += 1
                    last_event_id = event.event_id
                    pending = asyncio.ensure_future(anext(messages))
            finally:
                pending.cancel()
                with anyio.CancelScope(shield=True):
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await pending
                    await messages.aclose()
                logger.info("sse_close", extra={
                    **log_extra, "duration_s": round(time.monotonic() - opened, 1),
                    "events_sent": events_sent, "last_event_id": last_event_id,
                })

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/missions/{mission_id}/journey")
    async def journey(mission_id: str):
        try:
            return get_service().get_journey(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise HTTPException(404, redact_secrets(str(error))) from None

    @app.get("/api/missions/{mission_id}/recap.{format}")
    async def export_recap(mission_id: str, format: str, revision: int | None = None):
        renderers = {"html": (recap_adapter.render_html, "text/html"),
                     "pdf": (recap_adapter.render_pdf, "application/pdf"),
                     "ics": (recap_adapter.render_ics, "text/calendar")}
        if format not in renderers:
            raise HTTPException(404, "Unknown export format")
        try:
            snapshot = get_service().get_recap(mission_id, revision)
        except MissionError as error:
            raise HTTPException(404, redact_secrets(str(error))) from None
        renderer, media = renderers[format]
        try:
            content = await run_in_threadpool(renderer, snapshot)
        except Exception as error:  # noqa: BLE001 - report rendering errors without substituting another snapshot
            raise HTTPException(503, redact_secrets(str(error))) from None
        return Response(content, media_type=media, headers={
            "X-RunAI-Journey-Revision": str(snapshot.revision),
            "Content-Disposition": f'inline; filename="{mission_id}-r{snapshot.revision}.{format}"',
        })

    @app.post("/api/missions/{mission_id}/pause")
    async def pause_all(mission_id: str) -> dict:
        try:
            await get_service().pause_all(mission_id)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/resume")
    async def resume_all(mission_id: str) -> dict:
        try:
            await get_service().resume_all(mission_id)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/steps/{kind}/pause")
    async def pause_step(mission_id: str, kind: StepKind) -> dict:
        try:
            await get_service().pause(mission_id, kind)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/steps/{kind}/resume")
    async def resume_step(mission_id: str, kind: StepKind) -> dict:
        try:
            await get_service().resume(mission_id, kind)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/steps/{kind}/message")
    async def message_step(
        mission_id: str, kind: StepKind, body: MessageRequest
    ) -> dict:
        try:
            await get_service().send_message(mission_id, kind, body.text)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/questions/{question_id}/answer")
    async def answer_question(
        mission_id: str, question_id: str, body: HumanAnswer
    ) -> dict:
        if not body.answer.strip():
            raise HTTPException(status_code=422, detail="The answer cannot be empty")
        try:
            get_service().answer_question(mission_id, question_id, body)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except HumanQuestionError as error:
            raise HTTPException(409, redact_secrets(str(error))) from None
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/cancel")
    async def cancel_mission(mission_id: str) -> dict:
        try:
            await get_service().cancel(mission_id)
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/transcribe")
    async def transcribe(request: Request) -> dict:
        too_large = HTTPException(status_code=413, detail="Audio too large")
        if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
            raise too_large
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > MAX_AUDIO_BYTES:
                raise too_large
        audio = bytes(audio)
        if not audio:
            raise HTTPException(status_code=400, detail="Empty audio")
        content_type = request.headers.get("content-type", "application/octet-stream")
        try:
            return redact_secrets({"text": await get_service().transcribe(audio, content_type), "mode": selected.providers.mode.value})
        except Exception:
            logger.exception("Audio transcription failed")
            raise HTTPException(503, "Audio transcription is temporarily unavailable.") from None

    @app.get("/api/live/{session_id}")
    async def live_session(session_id: str) -> dict:
        found = get_service().find_session(session_id)
        if found is None:
            raise handle(MissionNotFound("Unknown session"))
        mission, step = found
        history = [
            event.model_dump(mode="json")
            for event in mission.events
            if event.data.get("session_id") == session_id
        ]
        return redact_secrets({
            "mission_id": mission.id,
            "label": STEP_LABELS[step.kind],
            "step": step.model_dump(mode="json"),
            "history": history,
        })

    return app
