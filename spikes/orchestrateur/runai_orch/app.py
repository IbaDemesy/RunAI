"""API FastAPI de l'orchestrateur RunAI.

lancer : RUNAI_H_ADAPTER=mock ../../.venv/bin/uvicorn runai_orch.app:app --port 8800
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from .adapters.base import HAdapter
from .contracts import MessageIn, MissionOut, SlotsOut, TripOut, TripRequest
from .orchestrator import CommandError, Orchestrator
from .state import InvalidTransition


def make_adapter() -> HAdapter:
    kind = os.environ.get("RUNAI_H_ADAPTER", "mock")
    if kind == "real":
        from .adapters.real import RealHAdapter

        return RealHAdapter()
    from .adapters.mock import MockHAdapter

    return MockHAdapter(speed=float(os.environ.get("RUNAI_MOCK_SPEED", "1")))


def create_app(orch: Orchestrator | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.orch.shutdown()  # annule toujours les sessions H a l'arret

    app = FastAPI(title="RunAI orchestrateur (spike)", lifespan=lifespan)
    app.state.orch = orch or Orchestrator(make_adapter(), poll_s=float(os.environ.get("RUNAI_QUOTA_POLL_S", "60")))

    def o(request: Request) -> Orchestrator:
        return request.app.state.orch

    def mission(request: Request, mid: str):
        try:
            return o(request).get(mid)
        except KeyError:
            raise HTTPException(404, "mission inconnue") from None

    async def command(request: Request, mid: str, coro_name: str, *args):
        mission(request, mid)
        try:
            m = await getattr(o(request), coro_name)(mid, *args)
        except (CommandError, InvalidTransition) as e:
            raise HTTPException(409, str(e)) from None
        return o(request).public(m)

    @app.post("/missions", response_model=TripOut, status_code=201)
    async def create(req: TripRequest, request: Request):
        trip_id, ms = await o(request).create_trip(req)
        return TripOut(trip_id=trip_id, missions=[o(request).public(m) for m in ms])

    @app.get("/trips/{trip_id}", response_model=TripOut)
    async def trip(trip_id: str, request: Request):
        ids = o(request).trips.get(trip_id)
        if ids is None:
            raise HTTPException(404, "voyage inconnu")
        return TripOut(trip_id=trip_id, missions=[o(request).public(o(request).missions[i]) for i in ids])

    @app.get("/missions/{mid}", response_model=MissionOut)
    async def get_mission(mid: str, request: Request):
        return o(request).public(mission(request, mid))

    @app.get("/missions/{mid}/events")
    async def events(mid: str, request: Request, from_seq: int = 0,
                     last_event_id: str | None = Header(default=None)):
        m = mission(request, mid)
        start = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else from_seq

        async def gen():
            yield "retry: 2000\n\n"
            async for ev in m.stream(start):
                if ev is None:
                    yield ": keep-alive\n\n"
                    continue
                yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {json.dumps(ev.model_dump(mode='json'))}\n\n"
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/missions/{mid}/pause", response_model=MissionOut)
    async def pause(mid: str, request: Request):
        return await command(request, mid, "pause")

    @app.post("/missions/{mid}/resume", response_model=MissionOut)
    async def resume(mid: str, request: Request):
        return await command(request, mid, "resume")

    @app.post("/missions/{mid}/message", response_model=MissionOut)
    async def message(mid: str, body: MessageIn, request: Request):
        return await command(request, mid, "message", body.text)

    @app.post("/missions/{mid}/cancel", response_model=MissionOut)
    async def cancel(mid: str, request: Request):
        return await command(request, mid, "cancel")

    @app.get("/slots", response_model=SlotsOut)
    async def slots(request: Request):
        sch = o(request).scheduler
        q = sch.last_quota
        return SlotsOut(local_limit=sch.limit, local_in_use=len(sch.held), queued=list(sch.queue),
                        h_quota=q.__dict__ if q else None)

    return app


app = create_app()
