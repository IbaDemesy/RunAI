"""Faux client Twilio Media Streams : simule un appel complet contre phone_server (sans compte Twilio).

Envoie connected/start puis l'audio de l'appelant en temps reel (trames mu-law de 20 ms, silence entre les tours),
recoit l'audio de RunAI, renvoie les `mark` apres la duree de lecture (comme Twilio) et mesure
la latence percue : fin de parole de l'appelant -> premier audio RunAI recu.

Usage : python fake_twilio_call.py  (lance le serveur en local sur un port libre, Gladia live reel, TTS Piper)
"""

import asyncio
import base64
import json
import os
import socket
import sys
import threading
import time
import wave

import uvicorn
import websockets
from g711 import pcm16_to_ulaw, resample_pcm16, ulaw_to_pcm16

CALLER_TURNS = ["Trouve-moi un semi en avril et prépare tout.", "Oui, vas-y."]
SILENCE = b"\xff" * 160


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def caller_audio(texts: list[str]) -> list[bytes]:
    from piper import PiperVoice

    voice = PiperVoice.load(
        os.path.expanduser("~/piper_voices/fr_FR-siwis-medium.onnx")
    )
    out = []
    for text in texts:
        pcm, rate = bytearray(), 22050
        for chunk in voice.synthesize(text):
            pcm += chunk.audio_int16_bytes
            rate = chunk.sample_rate
        out.append(pcm16_to_ulaw(resample_pcm16(bytes(pcm), rate, 8000)))
    return out


async def call(url: str, turns: list[bytes], timeout_s: float = 40) -> dict:
    stream_sid = "MZ" + "0" * 32
    received = bytearray()
    result = {"turns": [], "hangup_by_server": False}
    async with websockets.connect(url) as ws:
        await ws.send(
            json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        )
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "sequenceNumber": "1",
                    "start": {
                        "streamSid": stream_sid,
                        "callSid": "CA_fake_0001",
                        "tracks": ["inbound"],
                        "mediaFormat": {
                            "encoding": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "channels": 1,
                        },
                        "customParameters": {"caller": "+33600000000"},
                    },
                    "streamSid": stream_sid,
                }
            )
        )
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        state = {"speech_end": None}
        seq = 2

        async def sender():
            nonlocal seq
            t0 = time.perf_counter()
            n = 0
            pending = b""
            while True:
                if not pending and not queue.empty():
                    pending = queue.get_nowait()
                if pending:
                    frame, pending = pending[:160], pending[160:]
                    if not pending:
                        state["speech_end"] = time.perf_counter()
                else:
                    frame = SILENCE
                n += 1
                await asyncio.sleep(max(0, t0 + n * 0.02 - time.perf_counter()))
                payload = base64.b64encode(frame).decode()
                await ws.send(
                    json.dumps(
                        {
                            "event": "media",
                            "sequenceNumber": str(seq),
                            "media": {
                                "track": "inbound",
                                "chunk": str(n),
                                "timestamp": str(n * 20),
                                "payload": payload,
                            },
                            "streamSid": stream_sid,
                        }
                    )
                )
                seq += 1

        async def receiver():
            turn = {"latency": None, "audio": 0, "since_mark": 0}
            awaiting_end = False
            while True:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=1.0 if awaiting_end else None
                    )
                except (
                    TimeoutError
                ):  # plus rien apres le dernier mark : fin du tour RunAI
                    result["turns"].append(
                        {
                            "speech_end_to_first_runai_audio_ms": turn["latency"],
                            "runai_audio_s": round(turn["audio"] / 8000, 2),
                        }
                    )
                    turn = {"latency": None, "audio": 0, "since_mark": 0}
                    awaiting_end = False
                    turn_done.set()
                    continue
                msg = json.loads(raw)
                if msg["event"] == "media":
                    chunk = base64.b64decode(msg["media"]["payload"])
                    if turn["latency"] is None and state["speech_end"] is not None:
                        turn["latency"] = round(
                            (time.perf_counter() - state["speech_end"]) * 1000
                        )
                        state["speech_end"] = None
                    turn["audio"] += len(chunk)
                    turn["since_mark"] += len(chunk)
                    received.extend(chunk)
                elif msg["event"] == "mark":
                    await asyncio.sleep(
                        turn["since_mark"] / 8000
                    )  # Twilio renvoie le mark quand la lecture est finie
                    turn["since_mark"] = 0
                    await ws.send(
                        json.dumps(
                            {
                                "event": "mark",
                                "sequenceNumber": "0",
                                "mark": {"name": msg["mark"]["name"]},
                                "streamSid": stream_sid,
                            }
                        )
                    )
                    awaiting_end = True

        turn_done = asyncio.Event()
        send_task = asyncio.create_task(sender())
        recv_task = asyncio.create_task(receiver())
        try:
            await asyncio.sleep(0.5)
            for audio in turns:
                turn_done.clear()
                await queue.put(audio)
                await asyncio.wait_for(turn_done.wait(), timeout=timeout_s)
                await asyncio.sleep(0.3)
            try:
                await asyncio.wait_for(recv_task, timeout=10)
            except websockets.ConnectionClosedOK:
                pass
            result["hangup_by_server"] = True
        except (TimeoutError, websockets.ConnectionClosed) as exc:
            result["error"] = repr(exc)
        finally:
            send_task.cancel()
            recv_task.cancel()
    os.makedirs("results", exist_ok=True)
    with wave.open("results/fake_call_runai_audio.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(ulaw_to_pcm16(bytes(received)))
    return result


def main() -> None:
    import phone_server

    port = free_port()
    app = phone_server.create_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    turns = caller_audio(CALLER_TURNS)
    result = asyncio.run(call(f"ws://127.0.0.1:{port}/twilio/media", turns))
    time.sleep(1)
    result["server_metrics"] = [c.metrics.turns for c in app.state.calls]
    result["notified"] = app.state.notifier.sent
    result["gladia_session_ids"] = [c.stt.session_id for c in app.state.calls if c.stt]
    result["missions"] = {
        k: v.statuses for k, v in app.state.orchestrator.missions.items()
    }
    server.should_exit = True
    print(json.dumps(result, indent=2, ensure_ascii=False))
    with open("results/fake_call.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    sys.exit(0 if result.get("hangup_by_server") else 1)


if __name__ == "__main__":
    main()
