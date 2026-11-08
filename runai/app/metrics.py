"""Lazy mission accounting API."""

from fastapi import APIRouter, HTTPException

from runai.app.mission import MissionError, MissionService
from runai.metrics import MissionMetrics, compute


def build_metrics_router(service: MissionService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/missions/{mission_id}/metrics", response_model=MissionMetrics)
    async def metrics(mission_id: str) -> MissionMetrics:
        try:
            mission = service.get(mission_id)
        except MissionError:
            raise HTTPException(404, "Mission not found") from None
        return compute(mission.id, mission.events, mission.steps, mission.status)

    return router
