"""Mesure Telegram sans token : note vocale OGG/Opus (format Telegram) -> Gladia pre-enregistre (upload + job + poll).

Audio : Piper (synthese FR) encode en OGG/Opus 48 kHz mono via ffmpeg, comme une note vocale Telegram.
Usage : python bench_telegram_voice.py [--repeat 2]
"""

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from bench_gladia_mulaw import wer
from gladia_live import RUNAI_VOCABULARY
from gladia_prerecorded import transcribe_bytes

PHRASES = [
    "Trouve-moi un semi en avril et prépare tout.",
    "Je veux courir le marathon de Paris, avec un hôtel près du départ.",
]


def voice_note(text: str) -> bytes:
    from piper import PiperVoice

    voice = PiperVoice.load(
        os.path.expanduser("~/piper_voices/fr_FR-siwis-medium.onnx")
    )
    with tempfile.TemporaryDirectory() as d:
        wav_path, ogg_path = os.path.join(d, "in.wav"), os.path.join(d, "voice.ogg")
        with wave.open(wav_path, "wb") as w:
            voice.synthesize_wav(text, w)
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                wav_path,
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                ogg_path,
            ],
            check=True,
        )
        with open(ogg_path, "rb") as f:
            return f.read()


async def main(repeat: int) -> None:
    rows = []
    for text in PHRASES:
        audio = voice_note(text)
        for _ in range(repeat):
            t0 = time.perf_counter()
            res = await transcribe_bytes(audio, vocabulary=RUNAI_VOCABULARY)
            rows.append(
                {
                    "gladia_job_id": res.job_id,
                    "reference": text,
                    "transcript": res.text,
                    "wer": round(wer(text, res.text), 3),
                    "ogg_bytes": len(audio),
                    "upload_ms": round(res.upload_ms),
                    "total_ms": round((time.perf_counter() - t0) * 1000),
                }
            )
            print(json.dumps(rows[-1], ensure_ascii=False))
    os.makedirs("results", exist_ok=True)
    Path("results/bench_telegram_voice.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--repeat", type=int, default=2)
    asyncio.run(main(p.parse_args().repeat))
