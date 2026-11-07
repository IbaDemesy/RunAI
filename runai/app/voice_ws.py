"""Stream browser PCM16 mono audio to the selected transcription provider."""

import asyncio
import json
from contextlib import aclosing, suppress

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from runai.redaction import redact_secrets
from runai.voice.audio import BYTES_PER_SAMPLE, SUPPORTED_SAMPLE_RATES

router = APIRouter()
MAX_AUDIO_SECONDS = 120
IDLE_TIMEOUT_SECONDS = 20
DRAIN_TIMEOUT_SECONDS = 20
MAX_BUFFERED_FRAMES = 32


def _control(message: dict) -> dict:
    try:
        value = json.loads(message.get("text") or "")
    except (TypeError, ValueError):
        raise ValueError("Expected a JSON start or stop message.") from None
    if not isinstance(value, dict):
        raise TypeError("Expected a JSON object.")
    return value


@router.websocket("/api/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    from runai.app.server import MAX_AUDIO_BYTES

    await websocket.accept()
    tasks: list[asyncio.Task] = []
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=MAX_BUFFERED_FRAMES)
    stopped = asyncio.Event()

    def stop() -> None:
        if not stopped.is_set():
            stopped.set()
            queue.put_nowait(None)

    async def chunks():
        while (chunk := await queue.get()) is not None:
            yield chunk

    try:
        first = await asyncio.wait_for(websocket.receive(), IDLE_TIMEOUT_SECONDS)
        if first["type"] == "websocket.disconnect":
            return
        start = _control(first)
        sample_rate = start.get("sample_rate")
        if start.get("type") != "start":
            raise ValueError("The first message must start the audio session.")
        if type(sample_rate) is not int or sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"Unsupported sample rate. Choose one of {SUPPORTED_SAMPLE_RATES}.")

        providers = websocket.app.state.service.providers
        await websocket.send_json({"type": "ready", "mode": providers.mode.value, "provider": "gladia", "model": "solaria-1"})

        async def receive_audio() -> None:
            total = 0
            deadline = asyncio.get_running_loop().time() + MAX_AUDIO_SECONDS
            while True:
                timeout = None if stopped.is_set() else min(
                    IDLE_TIMEOUT_SECONDS, max(0, deadline - asyncio.get_running_loop().time())
                )
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout)
                except TimeoutError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise ValueError("Audio capture exceeds the 120-second limit.") from None
                    stop()
                    continue
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                if stopped.is_set():
                    raise ValueError("Only one audio session is allowed per connection.")
                if message.get("bytes") is not None:
                    data = message["bytes"]
                    if len(data) % BYTES_PER_SAMPLE:
                        raise ValueError("Audio frames must contain PCM16 mono samples.")
                    total += len(data)
                    if total > MAX_AUDIO_BYTES:
                        raise ValueError("Audio exceeds the maximum byte limit.")
                    if total > sample_rate * BYTES_PER_SAMPLE * MAX_AUDIO_SECONDS:
                        raise ValueError("Audio exceeds the 120-second limit.")
                    if data:
                        # Reserve one slot for the stop sentinel, even during disconnect.
                        if queue.qsize() >= MAX_BUFFERED_FRAMES - 1:
                            raise ValueError("Audio is arriving faster than it can be transcribed.")
                        queue.put_nowait(data)
                elif _control(message).get("type") == "stop":
                    stop()
                else:
                    raise ValueError("Expected PCM audio or a stop message; sessions cannot restart.")

        async def send_events() -> None:
            async with aclosing(providers.transcriber.stream(chunks(), sample_rate)) as events:
                async for event in events:
                    await websocket.send_json(redact_secrets(event.model_dump(mode="json")))
            await stopped.wait()

        receiver = asyncio.create_task(receive_audio())
        sender = asyncio.create_task(send_events())
        stopping = asyncio.create_task(stopped.wait())
        tasks.extend((receiver, sender, stopping))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stopping in done and sender not in done and receiver not in done:
            done, _ = await asyncio.wait((receiver, sender), timeout=DRAIN_TIMEOUT_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError("Timed out waiting for final transcription events.")
        for task in (receiver, sender):
            if task in done:
                task.result()
        await websocket.send_json({"type": "ended"})
        await websocket.close(code=1000)
    except WebSocketDisconnect:
        pass
    except Exception as error:  # noqa: BLE001 - provider errors must become protocol error frames
        if websocket.client_state is not WebSocketState.DISCONNECTED:
            with suppress(WebSocketDisconnect, RuntimeError):
                await websocket.send_json(redact_secrets({"type": "error", "message": str(error) or "Audio stream timed out."}))
                await websocket.close(code=1011)
    finally:
        stop()
        for task in tasks:
            if not task.done():
                task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
