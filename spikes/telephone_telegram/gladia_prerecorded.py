"""Gladia pre-enregistre en REST (httpx) pour les notes vocales Telegram (OGG/Opus).

On n'utilise pas gladiaio-sdk ici : appels REST directs (upload, pre-recorded, poll), plus simples a mesurer et a mocker.
"""

import asyncio
import os
import time
from dataclasses import dataclass

import httpx

API = "https://api.gladia.io/v2"


@dataclass
class Transcript:
    text: str
    job_id: str
    upload_ms: float
    total_ms: float


async def transcribe_bytes(
    audio: bytes,
    filename: str = "voice.ogg",
    content_type: str = "audio/ogg",
    language: str = "fr",
    vocabulary: list[str] | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    poll_s: float = 0.5,
    timeout_s: float = 60,
) -> Transcript:
    key = api_key or os.environ.get("GLADIA_API_KEY", "")
    if not key:
        raise RuntimeError("GLADIA_API_KEY manquante")
    headers = {"x-gladia-key": key}
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    t0 = time.perf_counter()
    try:
        up = await client.post(
            f"{API}/upload",
            headers=headers,
            files={"audio": (filename, audio, content_type)},
        )
        up.raise_for_status()
        upload_ms = (time.perf_counter() - t0) * 1000
        body = {
            "audio_url": up.json()["audio_url"],
            "language_config": {"languages": [language], "code_switching": False},
        }
        if vocabulary:
            body["custom_vocabulary"] = True
            body["custom_vocabulary_config"] = {"vocabulary": vocabulary}
        job = await client.post(f"{API}/pre-recorded", headers=headers, json=body)
        job.raise_for_status()
        job_id = job.json()["id"]
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            res = await client.get(f"{API}/pre-recorded/{job_id}", headers=headers)
            res.raise_for_status()
            data = res.json()
            if data["status"] == "done":
                text = data["result"]["transcription"]["full_transcript"]
                return Transcript(
                    text.strip(), job_id, upload_ms, (time.perf_counter() - t0) * 1000
                )
            if data["status"] == "error":
                raise RuntimeError(f"Gladia error {data.get('error_code')}")
            await asyncio.sleep(poll_s)
        raise TimeoutError(job_id)
    finally:
        if own:
            await client.aclose()
