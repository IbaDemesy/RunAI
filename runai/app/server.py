"""Backend FastAPI : API des missions, flux SSE et page web du portail."""

import asyncio
import contextlib
import json
import os
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from runai.app.auth import BasicAuthMiddleware
from runai.app.fakes import FakeBrowserAgents, FakeRaceSearch, FakeTranscriber
from runai.app.mission import MissionError, MissionService
from runai.app.tasks import STEP_LABELS
from runai.config import get_settings
from runai.h.runner import api_keys_from_env
from runai.models import StepKind

STATIC_DIR = Path(__file__).parent / "static"
KEEPALIVE_SECONDS = 15
MAX_AUDIO_BYTES = 10 * 1024 * 1024


class MissionRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=500)


def build_demo_service(delay: float | None = None) -> MissionService:
    delay = float(os.getenv("RUNAI_DEMO_DELAY", "1.5")) if delay is None else delay
    settings = get_settings()
    return MissionService(
        FakeRaceSearch(delay=delay),
        FakeBrowserAgents(delay=delay),
        FakeTranscriber(delay=delay / 3),
        traces_dir=settings.traces_dir,
        # Agents simulés : aucun slot H à partager, les missions ne s'attendent pas.
        max_concurrency=None,
        simulated=True,
    )


def build_service() -> MissionService:
    settings = get_settings()
    if (
        os.getenv("RUNAI_DEMO") == "1"
        or not api_keys_from_env()
        or not settings.linkup_api_key
    ):
        return build_demo_service()

    from runai.app.real import RealBrowserAgents, RealRaceSearch, RealTranscriber

    delay = float(os.getenv("RUNAI_DEMO_DELAY", "1.5"))
    transcriber = (
        RealTranscriber()
        if settings.gladia_api_key
        else FakeTranscriber(delay=delay / 3)
    )
    agents = RealBrowserAgents(traces_dir=settings.traces_dir)
    question_timeout_s = min(
        float(os.getenv("RUNAI_QUESTION_TIMEOUT_S", "600")),
        agents.max_time_s - 60,
    )
    return MissionService(
        RealRaceSearch(),
        agents,
        transcriber,
        traces_dir=settings.traces_dir,
        max_concurrency=settings.h_max_concurrency,
        simulated=False,
        question_timeout_s=question_timeout_s,
    )


def create_app(service: MissionService | None = None) -> FastAPI:
    app = FastAPI(title="RunAI")
    if credentials := os.getenv("RUNAI_BASIC_AUTH"):
        app.add_middleware(BasicAuthMiddleware, credentials=credentials)
    app.state.service = service or build_service()
    if (
        os.getenv("RUNAI_PUBLIC") == "1"
        and not os.getenv("RUNAI_BASIC_AUTH")
        and not app.state.service.simulated
    ):
        raise RuntimeError(
            "RUNAI_PUBLIC=1 en mode réel : définissez RUNAI_BASIC_AUTH, sinon n'importe qui consomme vos crédits"
        )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def get_service() -> MissionService:
        return app.state.service

    def handle(error: MissionError) -> HTTPException:
        return HTTPException(
            status_code=404 if "inconnue" in str(error) else 409, detail=str(error)
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/demo/live", include_in_schema=False)
    async def demo_live() -> FileResponse:
        return FileResponse(STATIC_DIR / "live.html")

    @app.get("/api/health")
    async def health() -> dict:
        selected = get_service()
        return {
            "ok": True,
            "mode": "demo" if selected.simulated else "real",
            "simulated": selected.simulated,
        }

    @app.post("/api/missions", status_code=201)
    async def create_mission(body: MissionRequest) -> dict:
        mission = await get_service().create(body.query)
        return mission.snapshot(include_events=True)

    @app.get("/api/missions/{mission_id}")
    async def get_mission(mission_id: str) -> dict:
        try:
            return get_service().get(mission_id).snapshot(include_events=True)
        except MissionError as error:
            raise handle(error) from None

    @app.get("/api/missions/{mission_id}/events")
    async def mission_events(mission_id: str, request: Request) -> StreamingResponse:
        service = get_service()
        try:
            service.get(mission_id)
        except MissionError as error:
            raise handle(error) from None

        async def stream():
            messages = service.subscribe(mission_id)
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
                        name, data = pending.result()
                    except StopAsyncIteration:
                        yield "event: end\ndata: {}\n\n"
                        break
                    yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    pending = asyncio.ensure_future(anext(messages))
            finally:
                pending.cancel()
                with anyio.CancelScope(shield=True):
                    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
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
            return get_service().get(mission_id).snapshot()
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/resume")
    async def resume_all(mission_id: str) -> dict:
        try:
            await get_service().resume_all(mission_id)
            return get_service().get(mission_id).snapshot()
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/steps/{kind}/pause")
    async def pause_step(mission_id: str, kind: StepKind) -> dict:
        try:
            await get_service().pause(mission_id, kind)
            return get_service().get(mission_id).snapshot()
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/steps/{kind}/resume")
    async def resume_step(mission_id: str, kind: StepKind) -> dict:
        try:
            await get_service().resume(mission_id, kind)
            return get_service().get(mission_id).snapshot()
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/steps/{kind}/message")
    async def message_step(
        mission_id: str, kind: StepKind, body: MessageRequest
    ) -> dict:
        try:
            await get_service().send_message(mission_id, kind, body.text)
            return get_service().get(mission_id).snapshot()
        except MissionError as error:
            raise handle(error) from None

    @app.post("/api/missions/{mission_id}/questions/{question_id}/answer")
    async def answer_question(
        mission_id: str, question_id: str, body: AnswerRequest
    ) -> dict:
        if not body.answer.strip():
            raise HTTPException(status_code=422, detail="La réponse ne peut pas être vide")
        try:
            get_service().answer_question(mission_id, question_id, body.answer)
            return get_service().get(mission_id).snapshot()
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
        return {"text": await get_service().transcribe(audio, content_type)}

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
