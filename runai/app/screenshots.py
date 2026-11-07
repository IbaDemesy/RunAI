"""Captures H : aucune URL ressource ni clé fournisseur exposée au navigateur."""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from runai.app.mission import MissionError, MissionService
from runai.models import StepKind


def build_screenshot_router(service: MissionService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/missions/{mission_id}/steps/{kind}/screenshot")
    async def screenshot(mission_id: str, kind: StepKind):
        try:
            service.get(mission_id)
        except MissionError:
            raise HTTPException(404, "Mission introuvable") from None
        run = service._capture_runs.get((mission_id, kind))
        if run is None:
            raise HTTPException(404, "Aucune capture H disponible")
        try:
            async with asyncio.timeout(20):
                content = await run.get_screenshot()
        except Exception:  # noqa: BLE001
            raise HTTPException(502, "Capture H temporairement indisponible") from None
        if content is None:
            raise HTTPException(404, "Aucune capture H disponible")
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(502, "Capture H invalide")
        return Response(content, media_type="image/png", headers={"Cache-Control": "no-store"})

    return router
