"""Backend FastAPI : API des missions, flux SSE et page web du portail."""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from runai.app.candidates import FixtureCandidateSearch, UnavailableCandidateSearch
from runai.app.fakes import DEMO_RACES
from runai.app.mission import MissionError, MissionService
from runai.app.providers import (
    ProviderSet,
    ProviderStatus,
    build_providers,
    provider_health,
)
from runai.app.tasks import STEP_LABELS
from runai.config import get_settings
from runai.contracts.common import DataMode
from runai.contracts.mission import HumanAnswer
from runai.framing.api import build_framing_router
from runai.framing.engine import FramingEngine
from runai.h.human_questions import HumanQuestionError
from runai.models import StepKind
from runai.redaction import redact_secrets
from runai.search.candidates import LinkupCandidateSearch

STATIC_DIR = Path(__file__).parent / "static"
KEEPALIVE_SECONDS = 15
MAX_AUDIO_BYTES = 10 * 1024 * 1024


class MissionRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


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
        traces_dir=settings.traces_dir, max_concurrency=settings.h_max_concurrency,
        simulated=providers.simulated, question_timeout_s=timeout,
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


def create_app(service: MissionService | None = None) -> FastAPI:
    selected = service or build_service()
    if selected.providers is None:
        selected.providers = ProviderSet(
            DataMode.demo if selected.simulated else DataMode.live,
            selected.search, selected.agents, selected.transcriber, provider_health(),
        )

    @asynccontextmanager
    async def lifespan(app):
        yield
        for mission in list(selected.missions.values()):
            if not mission.is_terminal:
                await selected.cancel(mission.id)
        lifecycle = getattr(selected.agents, "lifecycle", None)
        if lifecycle:
            await lifecycle.aclose()

    app = FastAPI(title="RunAI", lifespan=lifespan)
    app.state.service = selected
    engine = FramingEngine(search=candidate_search(selected.providers), mode=selected.providers.mode)
    app.state.framing = engine
    app.include_router(build_framing_router(engine, selected.confirm))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def get_service() -> MissionService:
        return app.state.service

    def handle(error: MissionError) -> HTTPException:
        return HTTPException(
            status_code=404 if "inconnue" in str(error) else 409, detail=redact_secrets(str(error))
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/demo/live", include_in_schema=False)
    async def demo_live() -> FileResponse:
        return FileResponse(STATIC_DIR / "live.html")

    @app.get("/api/health")
    async def health() -> dict:
        return get_service().providers.health_payload()

    @app.post("/api/missions", status_code=410)
    async def create_mission(body: MissionRequest) -> dict:
        raise HTTPException(410, "Créez et confirmez un cadrage via /api/framings avant de lancer les agents.")

    @app.get("/api/missions/{mission_id}")
    async def get_mission(mission_id: str) -> dict:
        try:
            return get_service().snapshot(mission_id).model_dump(mode="json")
        except MissionError as error:
            raise handle(error) from None

    @app.get("/api/missions/{mission_id}/events")
    async def mission_events(mission_id: str, request: Request) -> StreamingResponse:
        service = get_service()
        try:
            mission = service.get(mission_id)
            cursor = request.headers.get("last-event-id")
            if cursor:
                prefix, _, raw = cursor.rpartition(":")
                if prefix != mission_id or not raw.isdigit() or not 0 <= int(raw) <= len(mission.envelopes):
                    raise MissionError("Last-Event-ID invalide")
        except MissionError as error:
            raise handle(error) from None

        async def stream():
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
                    pending = asyncio.ensure_future(anext(messages))
            finally:
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
                await messages.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
            raise HTTPException(status_code=422, detail="La réponse ne peut pas être vide")
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
        too_large = HTTPException(status_code=413, detail="Audio trop volumineux")
        if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
            raise too_large
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > MAX_AUDIO_BYTES:
                raise too_large
        audio = bytes(audio)
        if not audio:
            raise HTTPException(status_code=400, detail="Audio vide")
        content_type = request.headers.get("content-type", "application/octet-stream")
        try:
            return {"text": await get_service().transcribe(audio, content_type), "mode": selected.providers.mode.value}
        except Exception as error:  # noqa: BLE001 - erreur fournisseur exposée sans faux résultat
            raise HTTPException(503, redact_secrets(str(error))) from None

    @app.get("/api/live/{session_id}")
    async def live_session(session_id: str) -> dict:
        found = get_service().find_session(session_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Session inconnue")
        mission, step = found
        history = [
            event.model_dump(mode="json")
            for event in mission.events
            if event.data.get("session_id") == session_id
        ]
        return {
            "mission_id": mission.id,
            "label": STEP_LABELS[step.kind],
            "step": step.model_dump(mode="json"),
            "history": history,
        }

    return app
