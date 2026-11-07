"""Client Gladia live (WebSocket v2) configure pour l'audio telephonique Twilio : mu-law 8 kHz, 8 bits."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

import httpx
import websockets

GLADIA_LIVE_URL = "https://api.gladia.io/v2/live"

RUNAI_VOCABULARY = [
    "semi",
    "semi-marathon",
    "marathon",
    "dossard",
    "PPS",
    "FFA",
    "Njuko",
    "Klikego",
    "RunAI",
]


def telephone_config(
    endpointing: float = 0.3, vocabulary: list[str] | None = None
) -> dict:
    """Parametres d'init documentes : encoding wav/ulaw, sample_rate 8000, bit_depth 8 (docs.gladia.io/api-reference/v2/live/init)."""
    config = {
        "encoding": "wav/ulaw",
        "sample_rate": 8000,
        "bit_depth": 8,
        "channels": 1,
        "model": "solaria-1",
        "endpointing": endpointing,
        "maximum_duration_without_endpointing": 15,
        "language_config": {"languages": ["fr"], "code_switching": False},
        "messages_config": {
            "receive_partial_transcripts": True,
            "receive_final_transcripts": True,
            "receive_speech_events": True,
        },
    }
    words = vocabulary if vocabulary is not None else RUNAI_VOCABULARY
    if words:
        config["realtime_processing"] = {
            "custom_vocabulary": True,
            "custom_vocabulary_config": {"vocabulary": words},
        }
    return config


@dataclass
class LiveEvent:
    kind: str  # "speech_start" | "speech_end" | "partial" | "final" | "other"
    text: str
    received_at: float
    raw: dict = field(repr=False, default_factory=dict)


def parse_message(raw: dict, received_at: float) -> LiveEvent:
    kind = raw.get("type", "")
    if kind == "transcript":
        data = raw.get("data", {})
        utterance = data.get("utterance", {})
        return LiveEvent(
            "final" if data.get("is_final") else "partial",
            utterance.get("text", "").strip(),
            received_at,
            raw,
        )
    if kind in ("speech_start", "speech_end"):
        return LiveEvent(kind, "", received_at, raw)
    return LiveEvent("other", kind, received_at, raw)


class GladiaLiveSession:
    """Une session live : init HTTP puis WebSocket. Envoi audio binaire brut, reception d'evenements."""

    def __init__(
        self, config: dict, api_key: str | None = None, region: str = "eu-west"
    ):
        self.config = config
        self.api_key = api_key or os.environ.get("GLADIA_API_KEY", "")
        self.region = region
        self.session_id: str | None = None
        self.ws = None
        self.events: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self._reader: asyncio.Task | None = None
        self.init_ms: float | None = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def start(self, retries: int = 5) -> None:
        if not self.api_key:
            raise RuntimeError("GLADIA_API_KEY manquante")
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(retries):
                resp = await client.post(
                    GLADIA_LIVE_URL,
                    params={"region": self.region},
                    headers={"x-gladia-key": self.api_key},
                    json=self.config,
                )
                if resp.status_code != 429:
                    break
                await asyncio.sleep(
                    5 * (attempt + 1)
                )  # offre gratuite : 1 session live a la fois
            resp.raise_for_status()
        body = resp.json()
        self.session_id = body["id"]
        self.ws = await websockets.connect(body["url"], max_size=None)
        self.init_ms = (time.perf_counter() - t0) * 1000
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    continue
                await self.events.put(
                    parse_message(json.loads(message), time.perf_counter())
                )
        except websockets.ConnectionClosed:
            pass
        finally:
            await self.events.put(LiveEvent("closed", "", time.perf_counter()))

    async def send_audio(self, chunk: bytes) -> None:
        await self.ws.send(chunk)

    async def stop(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps({"type": "stop_recording"}))
            except websockets.ConnectionClosed:
                pass

    async def close(self) -> None:
        await self.stop()
        if self._reader is not None:
            try:
                await asyncio.wait_for(self._reader, timeout=10)
            except TimeoutError:
                self._reader.cancel()
        if self.ws is not None:
            await self.ws.close()
