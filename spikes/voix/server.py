"""Backend FastAPI de la télécommande vocale.

Lancer : .venv/bin/uvicorn server:app --app-dir spikes/voix --port 8765
Page : http://localhost:8765/  (micro du navigateur, ou bouton « Injecter l'audio de test »)
"""

import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402
from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from gladia_live import GladiaLive, live_config  # noqa: E402
from pipeline import VoiceRemote, inject_realtime, read_pcm16  # noqa: E402

load_dotenv()
app = FastAPI(title="RunAI spike voix")
TEST_AUDIO = HERE / "audio" / "scenario_gtts.wav"
GLADIA_LOCK = asyncio.Lock()  # offre gratuite Gladia : 1 session live à la fois
STATE: dict = {"h": None}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.on_event("shutdown")
async def shutdown() -> None:
    if STATE["h"]:
        await STATE["h"].cancel()


class Conn:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.gl: GladiaLive | None = None
        self.vr: VoiceRemote | None = None
        self.inject_task: asyncio.Task | None = None
        self.h_status_task: asyncio.Task | None = None
        self.opening = False
        self.pending: list[bytes] = []

    async def emit(self, ev: dict) -> None:
        with contextlib.suppress(Exception):
            await self.ws.send_text(json.dumps(ev, ensure_ascii=False, default=str))

    async def start_gladia(self) -> bool:
        if GLADIA_LOCK.locked():
            await self.emit({"type": "error", "message": "Une session Gladia live est deja ouverte"})
            return False
        await GLADIA_LOCK.acquire()
        self.vr = VoiceRemote(h=STATE["h"], emit=self.emit)
        gl = GladiaLive(self.vr.on_gladia, live_config())
        self.opening, self.pending = True, []  # le micro parle pendant l'init Gladia (~1 s) : on bufferise
        try:
            await gl.start()
        except Exception as e:  # noqa: BLE001
            GLADIA_LOCK.release()
            self.opening = False
            await self.emit({"type": "error", "message": str(e)[:300]})
            return False
        for chunk in self.pending:
            await gl.send_audio(chunk)
        self.gl, self.opening, self.pending = gl, False, []
        await self.emit({"type": "gladia_open", "session_id": self.gl.session_id,
                         "init_s": round(self.gl.init_latency_s, 3)})
        return True

    async def stop_gladia(self) -> None:
        if self.gl:
            gl, self.gl = self.gl, None
            await gl.stop()
            if self.vr:
                await self.vr.drain()
            GLADIA_LOCK.release()
            await self.emit({"type": "gladia_closed"})

    async def inject(self) -> None:
        if not await self.start_gladia():
            return

        def on_start(t0: float) -> None:
            self.vr.t0 = t0

        await inject_realtime(read_pcm16(str(TEST_AUDIO)), self.gl.send_audio, on_start)
        await self.stop_gladia()

    async def h_start(self) -> None:
        from h_control import HControl

        if STATE["h"] and STATE["h"].session_id:
            await self.emit({"type": "error", "message": "Session H deja ouverte"})
            return
        h = HControl(log=lambda m: asyncio.create_task(self.emit({"type": "log", "message": m})))
        quota = await h.wait_quota(max_wait_s=0)
        await h.create()
        STATE["h"] = h
        if self.vr:
            self.vr.h = h
        self.h_status_task = asyncio.create_task(self.poll_h())
        await self.emit({"type": "h_open", "session_id": h.session_id, "quota": quota})

    async def poll_h(self) -> None:
        while STATE["h"] and STATE["h"].session_id:
            with contextlib.suppress(Exception):
                st, steps = await STATE["h"].status()
                await self.emit({"type": "h_status", "status": st, "steps": steps})
            await asyncio.sleep(1)

    async def h_cancel(self) -> None:
        if STATE["h"]:
            await STATE["h"].cancel()
            await self.emit({"type": "h_closed"})
        STATE["h"] = None


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    c = Conn(ws)
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if c.opening:
                    if c.vr.t0 is None:
                        c.vr.t0 = time.monotonic() - 0.1
                    c.pending.append(msg["bytes"])
                elif c.gl:
                    if c.vr.t0 is None:
                        c.vr.t0 = time.monotonic() - 0.1  # approx. : 1er bloc micro = 100 ms
                    await c.gl.send_audio(msg["bytes"])
                continue
            cmd = json.loads(msg.get("text") or "{}").get("cmd")
            try:
                if cmd == "mic_start":
                    asyncio.create_task(c.start_gladia())
                elif cmd == "mic_stop":
                    await c.stop_gladia()
                elif cmd == "inject":
                    c.inject_task = asyncio.create_task(c.inject())
                elif cmd == "h_start":
                    await c.h_start()
                elif cmd == "h_cancel":
                    await c.h_cancel()
            except Exception as e:  # noqa: BLE001
                await c.emit({"type": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})
    except WebSocketDisconnect:
        pass
    finally:
        await c.stop_gladia()
