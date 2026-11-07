"""Télécommande vocale : messages Gladia -> intentions -> actions sur la session H."""

import asyncio
import time
import wave
from collections.abc import Awaitable, Callable

from intents import (
    CORRECTION,
    PAUSE,
    RESUME,
    VALIDATE,
    correction_text,
    detect_fast,
    is_correction,
)

CHUNK_S = 0.1
CORRECTION_PREFIX = "Correction de l'utilisateur (dictee vocale), applique-la maintenant : "

Emit = Callable[[dict], Awaitable[None]]


async def _noop(_: dict) -> None:
    return None


class VoiceRemote:
    def __init__(self, h=None, emit: Emit = _noop) -> None:
        self.h = h
        self.emit = emit
        self.t0: float | None = None
        self.transcripts: list[dict] = []
        self.speech_events: list[dict] = []
        self.intents: list[dict] = []
        self.actions: list[dict] = []
        self._fired: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []

    def rel(self, t: float) -> float | None:
        return None if self.t0 is None else round(t - self.t0, 3)

    async def on_gladia(self, msg: dict, recv: float) -> None:
        typ = msg.get("type")
        data = msg.get("data") or {}
        if typ in ("speech_start", "speech_end"):
            ev = {"type": typ, "recv": recv, "time": data.get("time")}
            self.speech_events.append(ev)
            await self.emit({"type": typ, "t": self.rel(recv), "audio_time": data.get("time")})
            return
        if typ != "transcript":
            if typ in ("error", "end_session", "start_session"):
                await self.emit({"type": "gladia_" + typ, "data": data})
            return
        utt = data.get("utterance") or {}
        text = (utt.get("text") or "").strip()
        if not text:
            return
        uid = data.get("id", "")
        final = bool(data.get("is_final"))
        rec = {"id": uid, "final": final, "text": text, "recv": recv, "start": utt.get("start"),
               "end": utt.get("end"), "words": [{"w": w.get("word"), "s": w.get("start"), "e": w.get("end")}
                                                 for w in utt.get("words") or []]}
        self.transcripts.append(rec)
        await self.emit({"type": "transcript", "final": final, "id": uid, "text": text,
                         "t": self.rel(recv), "audio_end": utt.get("end")})
        fast = detect_fast(text)
        if fast and (uid, fast) not in self._fired:
            self._fire(fast, uid, text, final, recv)
        if final and is_correction(text) and (uid, CORRECTION) not in self._fired:
            self._fire(CORRECTION, uid, text, final, recv)

    def _fire(self, name: str, uid: str, text: str, final: bool, recv: float) -> None:
        detect = time.monotonic()
        self._fired.add((uid, name))
        it = {"intent": name, "id": uid, "text": text, "from_final": final, "recv": recv, "detect": detect,
              "detect_after_msg_ms": round((detect - recv) * 1000, 3)}
        self.intents.append(it)
        self._tasks.append(asyncio.create_task(self._act(it)))

    async def _act(self, it: dict) -> None:
        await self.emit({"type": "intent", "intent": it["intent"], "text": it["text"],
                         "from_final": it["from_final"], "t": self.rel(it["detect"]),
                         "detect_after_msg_ms": it["detect_after_msg_ms"]})
        async with self._lock:
            act = {"intent": it["intent"], "start": time.monotonic(), "dry_run": self.h is None}
            try:
                await self._do(it, act)
            except Exception as e:  # noqa: BLE001
                act["error"] = f"{type(e).__name__}: {getattr(e, 'status_code', '')} {str(e)[:200]}"
            self.actions.append(act)
            await self.emit({"type": "action", **{k: v for k, v in act.items() if k != "start"}})

    async def _do(self, it: dict, act: dict) -> None:
        name, h = it["intent"], self.h
        if name == VALIDATE:
            act["note"] = "validation humaine enregistree ; aucune soumission ni paiement"
            return
        if h is None or h.session_id is None:
            act["note"] = "dry-run (pas de session H)"
            return
        if name == PAUSE:
            act["call_s"] = await h.pause()
            st, dt, polls = await h.wait_status({"paused"}, timeout_s=60)
        elif name == RESUME:
            act["call_s"] = await h.resume()
            st, dt, polls = await h.wait_status({"running"}, timeout_s=60)
        elif name == CORRECTION:
            st, _ = await h.status()
            if st in ("completed", "failed", "timed_out", "interrupted", "idle"):
                # Un message sur une session terminee la relance (facturee, prend un slot) : on refuse.
                act["note"] = f"correction non envoyee : session H {st}"
                return
            msg = CORRECTION_PREFIX + correction_text(it["text"])
            act["message"] = msg
            act["sent_at"] = time.monotonic()
            act["call_s"] = await h.send_message(msg)
            st, dt, polls = await h.wait_status({"running"}, timeout_s=60)
        else:
            return
        act.update({"status_reached": st, "call_to_status_s": round(dt + act["call_s"], 3), "polls": polls})
        act["steps"] = (await h.status())[1]

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def read_pcm16(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return w.readframes(w.getnframes())


async def inject_realtime(pcm: bytes, send, on_start=None) -> float:
    """Envoie l'audio au rythme réel ; le bloc k part à t0+(k+1)*100 ms comme un micro."""
    step = int(16000 * 2 * CHUNK_S)
    t0 = time.monotonic()
    if on_start:
        on_start(t0)
    for k, i in enumerate(range(0, len(pcm), step)):
        delay = t0 + (k + 1) * CHUNK_S - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        await send(pcm[i:i + step])
    return t0
