"""Mesure la latence TTS disponible sans cle (Piper local, espeak-ng). ElevenLabs/OpenAI mesures seulement si la cle existe."""

import asyncio
import json
import os
import statistics
import sys
import wave
from pathlib import Path

from g711 import ulaw_to_pcm16
from tts import ElevenLabsTTS, EspeakTTS, OpenAITTS, PiperTTS

PHRASES = [
    "D'accord.",
    "Je cherche un semi-marathon en avril, je te rappelle dans un instant.",
    "J'ai trouve le semi de Paris le 5 avril. Je m'en occupe, et je t'envoie tout sur Telegram.",
]


def save_wav(path: str, ulaw: bytes) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(ulaw_to_pcm16(ulaw))


async def run(engine, runs: int = 3) -> dict:
    rows = []
    for phrase in PHRASES:
        firsts, totals = [], []
        for _ in range(runs):
            r = await engine.asynthesize(phrase)
            firsts.append(r.first_audio_ms)
            totals.append(r.total_ms)
        rows.append(
            {
                "phrase_chars": len(phrase),
                "audio_s": round(r.audio_seconds, 2),
                "first_audio_ms_median": round(statistics.median(firsts), 1),
                "total_ms_median": round(statistics.median(totals), 1),
                "rtf": round(statistics.median(totals) / 1000 / r.audio_seconds, 3),
            }
        )
    os.makedirs("results", exist_ok=True)
    save_wav(f"results/tts_{engine.name}.wav", r.ulaw_8k)
    return {
        "engine": engine.name,
        "load_ms": round(getattr(engine, "load_ms", 0.0), 1),
        "runs_per_phrase": runs,
        "rows": rows,
    }


async def main() -> None:
    out = {"cpu_count": os.cpu_count(), "results": [], "skipped": []}
    for factory in (PiperTTS, EspeakTTS, ElevenLabsTTS, OpenAITTS):
        try:
            engine = factory()
        except (
            RuntimeError,
            OSError,
            ImportError,
        ) as exc:  # cle absente : on le note, on n'invente pas de chiffre
            out["skipped"].append({"engine": factory.__name__, "reason": str(exc)})
            continue
        out["results"].append(await run(engine))
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    Path("results/bench_tts.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    asyncio.run(main())
