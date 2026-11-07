"""Canal telephone : Twilio Voice + Media Streams bidirectionnel -> Gladia live -> dialogue -> TTS -> retour audio.

Routes :
- POST /twilio/voice  : webhook "A call comes in" ; renvoie le TwiML <Say> (accueil) + <Connect><Stream>.
- WS   /twilio/media  : flux Media Streams (JSON : connected, start, media, mark, stop).

Lancer : PUBLIC_HOST=xxxx.ngrok-free.app uvicorn phone_server:app --port 8080
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

from dialogue import GREETING, CallDialogue
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from gladia_live import GladiaLiveSession, telephone_config
from orchestrator import Mission, MockOrchestrator
from tts import build_tts, twilio_say

log = logging.getLogger("runai.phone")

OUT_CHUNK = 160 * 25  # 0,5 s de mu-law 8 kHz par message sortant


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Algorithme X-Twilio-Signature : HMAC-SHA1(url + cles triees concatenees a leurs valeurs), base64."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(
        hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


def voice_twiml(stream_url: str, caller: str, greeting: str = GREETING) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f"{twilio_say(greeting)}"
        f"<Connect><Stream url={quoteattr(stream_url)}>"
        f'<Parameter name="caller" value={quoteattr(caller)}/>'
        "</Stream></Connect></Response>"
    )


class LogNotifier:
    """« Je t'envoie tout » : le vrai notifier pousse vers Telegram (si le numero est lie a un chat) ou SMS."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def mission_started(self, caller: str, mission: Mission) -> None:
        self.sent.append((caller, mission.id))
        log.info(
            "suivi de %s envoye a %s", mission.id, caller[-4:].rjust(len(caller), "*")
        )


@dataclass
class CallMetrics:
    turns: list = field(default_factory=list)


class CallSession:
    """Etat d'un appel. Les dependances (stt_factory, tts, orchestrateur) sont injectables pour les tests."""

    def __init__(self, ws: WebSocket, stt_factory, tts, orchestrator, notifier):
        self.ws = ws
        self.stt_factory = stt_factory
        self.tts = tts
        self.notifier = notifier
        self.orchestrator = orchestrator
        self.stream_sid = ""
        self.call_sid = ""
        self.caller = ""
        self.stt = None
        self.dialogue: CallDialogue | None = None
        self.speaking = False
        self.pending_hangup = False
        self.marks = 0
        self.metrics = CallMetrics()
        self._stt_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()

    async def run(self) -> None:
        try:
            async for message in self.ws.iter_text():
                if await self.handle(json.loads(message)):
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await self.cleanup()

    async def handle(self, msg: dict) -> bool:
        event = msg.get("event")
        if event == "start":
            start = msg["start"]
            self.stream_sid = start["streamSid"]
            self.call_sid = start.get("callSid", "")
            self.caller = start.get("customParameters", {}).get("caller", "")
            fmt = start.get("mediaFormat", {})
            if fmt and (
                fmt.get("encoding") != "audio/x-mulaw"
                or int(fmt.get("sampleRate", 8000)) != 8000
            ):
                log.warning("format inattendu %s", fmt)
            self.dialogue = CallDialogue(self.orchestrator, self.caller)
            self.stt = self.stt_factory()
            await self.stt.start()
            self._stt_task = asyncio.create_task(self._consume_stt())
        elif event == "media" and self.stt is not None:
            if msg["media"].get("track", "inbound") == "inbound":
                await self.stt.send_audio(base64.b64decode(msg["media"]["payload"]))
        elif event == "mark":
            self.marks -= 1
            if self.marks <= 0:
                self.speaking = False
                if self.pending_hangup:
                    return True  # fermer le WS : Twilio poursuit le TwiML apres <Connect> (rien) et raccroche
        elif event == "stop":
            return True
        return False

    async def _consume_stt(self) -> None:
        while True:
            ev = await self.stt.events.get()
            if ev.kind == "closed":
                return
            if ev.kind == "speech_start" and self.speaking:
                await self._send(
                    {"event": "clear", "streamSid": self.stream_sid}
                )  # barge-in
                self.speaking = False
                self.marks = 0
            elif ev.kind == "final":
                t_final = time.perf_counter()
                reply = await self.dialogue.on_final_transcript(ev.text)
                if reply is None:
                    continue
                first_ms, tts_ms = None, 0.0
                for sentence in split_sentences(
                    reply.text
                ):  # phrase par phrase : la 1re part pendant que la suite se synthetise
                    audio = await self.tts.asynthesize(sentence)
                    tts_ms += audio.total_ms
                    await self.speak(
                        audio.ulaw_8k, label=f"turn{len(self.metrics.turns) + 1}"
                    )
                    if first_ms is None:
                        first_ms = round((time.perf_counter() - t_final) * 1000, 1)
                self.metrics.turns.append(
                    {
                        "user": ev.text,
                        "runai": reply.text,
                        "final_to_first_audio_sent_ms": first_ms,
                        "tts_total_ms": round(tts_ms, 1),
                    }
                )
                if reply.mission is not None:
                    await self.notifier.mission_started(self.caller, reply.mission)
                if reply.hangup:
                    self.pending_hangup = True

    async def speak(self, ulaw: bytes, label: str) -> None:
        self.speaking = True
        for i in range(0, len(ulaw), OUT_CHUNK):
            payload = base64.b64encode(ulaw[i : i + OUT_CHUNK]).decode()
            await self._send(
                {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": payload},
                }
            )
        self.marks += 1
        await self._send(
            {"event": "mark", "streamSid": self.stream_sid, "mark": {"name": label}}
        )

    async def _send(self, msg: dict) -> None:
        async with self._send_lock:
            await self.ws.send_text(json.dumps(msg))

    async def cleanup(self) -> None:
        if self.stt is not None:
            await self.stt.close()
        if self._stt_task is not None:
            self._stt_task.cancel()
        log.info("appel %s termine, metriques %s", self.call_sid, self.metrics.turns)


def create_app(stt_factory=None, tts=None, orchestrator=None, notifier=None) -> FastAPI:
    app = FastAPI(title="RunAI phone channel (spike)")
    app.state.stt_factory = stt_factory or (
        lambda: GladiaLiveSession(telephone_config(endpointing=0.1))
    )
    app.state.tts = tts
    app.state.orchestrator = orchestrator or MockOrchestrator()
    app.state.notifier = notifier or LogNotifier()
    app.state.calls: list[CallSession] = []

    @app.post("/twilio/voice")
    async def voice(request: Request) -> Response:
        form = dict(await request.form())
        token = os.environ.get("TWILIO_AUTH_TOKEN")
        if token:
            expected = twilio_signature(token, str(request.url), form)
            if not hmac.compare_digest(
                expected, request.headers.get("X-Twilio-Signature", "")
            ):
                return Response(status_code=403)
        host = os.environ.get("PUBLIC_HOST") or request.headers.get("host", "localhost")
        scheme = "ws" if host.startswith(("localhost", "127.")) else "wss"
        return Response(
            voice_twiml(f"{scheme}://{host}/twilio/media", form.get("From", "")),
            media_type="application/xml",
        )

    @app.websocket("/twilio/media")
    async def media(ws: WebSocket) -> None:
        await ws.accept()
        if app.state.tts is None:
            app.state.tts = build_tts()
        call = CallSession(
            ws,
            app.state.stt_factory,
            app.state.tts,
            app.state.orchestrator,
            app.state.notifier,
        )
        app.state.calls.append(call)
        await call.run()
        try:
            await ws.close()
        except RuntimeError:
            pass

    @app.get("/metrics")
    async def metrics() -> dict:
        return {
            "calls": [
                {"call_sid": c.call_sid, "turns": c.metrics.turns}
                for c in app.state.calls
            ]
        }

    return app


app = create_app()
