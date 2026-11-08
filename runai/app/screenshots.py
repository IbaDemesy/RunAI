"""Captures H : aucune URL ressource ni clé fournisseur exposée au navigateur."""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from runai.app.mission import MissionError, MissionService
from runai.models import StepKind


def build_screenshot_router(service: MissionService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/missions/{mission_id}/steps/{kind}/screenshots")
    async def screenshot_index(mission_id: str, kind: str):
        try:
            return await asyncio.to_thread(service.capture_store.index, mission_id, kind)
        except (ValueError, OSError):
            raise HTTPException(404, "Screenshots not found") from None

    @router.get("/api/missions/{mission_id}/steps/{kind}/screenshots/{revision}.png")
    async def stored_screenshot(mission_id: str, kind: str, revision: str):
        try:
            if not revision.isascii() or not revision.isdecimal():
                raise ValueError("Invalid revision")
            path = service.capture_store.frame_path(mission_id, kind, int(revision))
            content = await asyncio.to_thread(path.read_bytes)
        except (ValueError, OSError):
            raise HTTPException(404, "Screenshot not found") from None
        return Response(content, media_type="image/png")

    @router.get("/api/missions/{mission_id}/steps/{kind}/screenshot")
    async def screenshot(mission_id: str, kind: StepKind):
        try:
            service.get(mission_id)
        except MissionError:
            raise HTTPException(404, "Mission not found") from None
        run = service._capture_runs.get((mission_id, kind))
        if run is None:
            raise HTTPException(404, "No H screenshot available")
        try:
            async with asyncio.timeout(20):
                content = await run.get_screenshot()
        except Exception:  # noqa: BLE001
            raise HTTPException(502, "H screenshot temporarily unavailable") from None
        if content is None:
            raise HTTPException(404, "No H screenshot available")
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(502, "Invalid H screenshot")
        return Response(content, media_type="image/png", headers={"Cache-Control": "no-store"})

    return router
