"""Client Gladia live minimal (REST init + WebSocket) avec horodatage de réception."""

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable

import httpx
import websockets

GLADIA_INIT_URL = "https://api.gladia.io/v2/live"
SAMPLE_RATE = 16000

OnMessage = Callable[[dict, float], Awaitable[None]]


def live_config(custom_vocabulary: list[str] | None = None) -> dict:
    cfg = {
        "encoding": "wav/pcm",
        "bit_depth": 16,
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "model": "solaria-1",
        "endpointing": 0.3,
        "maximum_duration_without_endpointing": 15,
        "language_config": {"languages": ["fr"], "code_switching": False},
        "messages_config": {
            "receive_partial_transcripts": True,
            "receive_final_transcripts": True,
            "receive_speech_events": True,
            "receive_pre_processing_events": False,
            "receive_realtime_processing_events": False,
            "receive_post_processing_events": False,
            "receive_acknowledgments": False,
            "receive_lifecycle_events": True,
        },
    }
    if custom_vocabulary:
        cfg["realtime_processing"] = {
            "custom_vocabulary": True,
            "custom_vocabulary_config": {"vocabulary": custom_vocabulary},
        }
    return cfg


class GladiaLive:
    def __init__(self, on_message: OnMessage, config: dict | None = None) -> None:
        self.on_message = on_message
        self.config = config or live_config()
        self.session_id: str | None = None
        self.init_latency_s: float | None = None
        self._ws = None
        self._reader: asyncio.Task | None = None
        self.closed = asyncio.Event()

    async def start(self) -> None:
        key = os.environ.get("GLADIA_API_KEY")
        if not key:
            raise RuntimeError("GLADIA_API_KEY manquante")
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(GLADIA_INIT_URL, headers={"x-gladia-key": key}, json=self.config)
        if r.status_code == 429:
            raise RuntimeError("Gladia 429 : session live deja ouverte (offre gratuite = 1 session live)")
        r.raise_for_status()
        body = r.json()
        self.session_id = body["id"]
        self._ws = await websockets.connect(body["url"], max_size=None)
        self.init_latency_s = time.monotonic() - t0
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                recv = time.monotonic()
                if isinstance(raw, bytes):
                    continue
                await self.on_message(json.loads(raw), recv)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.closed.set()

    async def send_audio(self, pcm: bytes) -> None:
        await self._ws.send(pcm)

    async def stop(self, wait_s: float = 10.0) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "stop_recording"}))
            await asyncio.wait_for(self.closed.wait(), wait_s)
        except (TimeoutError, websockets.ConnectionClosed):
            pass
        finally:
            await self._ws.close()
