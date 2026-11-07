from fastapi import APIRouter, HTTPException

from runai.contracts.framing import (
    FramingConfirm,
    FramingCreate,
    FramingError,
    FramingReply,
    FramingSession,
)
from runai.contracts.mission import MissionSnapshot
from runai.framing.engine import FramingEngine, OnConfirm


def build_framing_router(engine: FramingEngine, on_confirm: OnConfirm) -> APIRouter:
    router = APIRouter(prefix="/api/framings", tags=["framing"])

    def get(framing_id: str) -> FramingSession:
        try:
            return engine.get(framing_id)
        except KeyError as exc:
            raise HTTPException(404, "Unknown framing") from exc

    async def call(operation):
        try:
            return await operation
        except FramingError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("", status_code=201, response_model=FramingSession)
    async def create(request: FramingCreate):
        return await call(engine.create(request))

    @router.get("/{framing_id}", response_model=FramingSession)
    async def retrieve(framing_id: str):
        return get(framing_id)

    @router.post("/{framing_id}/replies", response_model=FramingSession)
    async def reply(framing_id: str, request: FramingReply):
        get(framing_id)
        return await call(engine.reply(framing_id, request))

    @router.post("/{framing_id}/confirm", response_model=MissionSnapshot)
    async def confirm(framing_id: str, request: FramingConfirm):
        get(framing_id)
        return await call(engine.confirm(framing_id, request, on_confirm))

    @router.post("/{framing_id}/cancel", response_model=FramingSession)
    async def cancel(framing_id: str):
        get(framing_id)
        return await call(engine.cancel(framing_id))

    return router
