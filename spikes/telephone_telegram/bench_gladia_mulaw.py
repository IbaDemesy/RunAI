"""Mesure Gladia live sur de l'audio telephonique injecte (mu-law 8 kHz, trames de 20 ms comme Twilio).

Voix de test : synthese Piper (pas une vraie voix humaine au telephone : resultats indicatifs).
Usage : python bench_gladia_mulaw.py [--endpointing 0.1 0.3] [--pcm16k]
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

from g711 import frames, pcm16_to_ulaw, resample_pcm16
from gladia_live import GladiaLiveSession, telephone_config

PHRASES = [
    "Trouve-moi un semi en avril et prépare tout.",
    "Je veux courir le marathon de Paris, avec un hôtel près du départ.",
    "Stop, prends plutôt le dix kilomètres.",
    "Mon adresse c'est camille point martin arobase example point com.",
    "Oui, je valide.",
]

FRAME_MS = 20
LEAD_SILENCE_S = 0.3
TAIL_SILENCE_S = 2.0


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", text)


def wer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


def piper_pcm(voice, text: str) -> tuple[bytes, int]:
    pcm, rate = bytearray(), 22050
    for chunk in voice.synthesize(text):
        pcm += chunk.audio_int16_bytes
        rate = chunk.sample_rate
    return bytes(pcm), rate


async def run_one(
    text: str, audio: bytes, config: dict, bytes_per_frame: int, silence_byte: bytes
) -> dict:
    lead = silence_byte * int(bytes_per_frame * LEAD_SILENCE_S * 1000 / FRAME_MS)
    tail = silence_byte * int(bytes_per_frame * TAIL_SILENCE_S * 1000 / FRAME_MS)
    stream = lead + audio + tail
    speech_start_offset = len(lead)
    speech_end_offset = len(lead) + len(audio)

    async with GladiaLiveSession(config) as session:
        sent = 0
        t_start = time.perf_counter()
        t_speech_start = t_speech_end = None
        for frame in frames(stream, bytes_per_frame):
            target = t_start + (sent / bytes_per_frame) * FRAME_MS / 1000
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
            if t_speech_start is None and sent >= speech_start_offset:
                t_speech_start = time.perf_counter()
            await session.send_audio(frame)
            sent += len(frame)
            if t_speech_end is None and sent >= speech_end_offset:
                t_speech_end = time.perf_counter()
        await session.stop()
        events = []
        while True:
            ev = await asyncio.wait_for(session.events.get(), timeout=15)
            if ev.kind == "closed":
                break
            events.append(ev)
        session_id, init_ms = session.session_id, session.init_ms

    def first(kind):
        return next((e for e in events if e.kind == kind), None)

    finals = [e for e in events if e.kind == "final"]
    hyp = " ".join(e.text for e in finals)
    sp, fp, ff = first("speech_start"), first("partial"), finals[0] if finals else None
    return {
        "gladia_session_id": session_id,
        "init_ms": round(init_ms, 1),
        "reference": text,
        "transcript": hyp,
        "wer": round(wer(text, hyp), 3),
        "speech_start_event_ms": round((sp.received_at - t_speech_start) * 1000)
        if sp
        else None,
        "first_partial_ms_after_speech_start": round(
            (fp.received_at - t_speech_start) * 1000
        )
        if fp
        else None,
        "last_final_ms_after_speech_end": round(
            (finals[-1].received_at - t_speech_end) * 1000
        )
        if ff
        else None,
        "audio_s": round(len(audio) / (bytes_per_frame * 1000 / FRAME_MS), 2),
        "n_partials": sum(e.kind == "partial" for e in events),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpointing", type=float, nargs="+", default=[0.1, 0.3])
    parser.add_argument(
        "--pcm16k",
        action="store_true",
        help="ajoute une reference PCM 16 kHz (qualite micro web)",
    )
    parser.add_argument(
        "--no-vocab", action="store_true", help="sans custom_vocabulary"
    )
    parser.add_argument("--out", default="results/bench_gladia_mulaw.json")
    args = parser.parse_args()

    from piper import PiperVoice

    voice = PiperVoice.load(
        os.path.expanduser("~/piper_voices/fr_FR-siwis-medium.onnx")
    )
    clips = [(t, *piper_pcm(voice, t)) for t in PHRASES]

    vocab = [] if args.no_vocab else None
    variants = [("ulaw_8k", ep) for ep in args.endpointing]
    if args.pcm16k:
        variants.append(("pcm_16k", args.endpointing[0]))

    out = {
        "voice": "piper fr_FR-siwis-medium (synthese)",
        "frame_ms": FRAME_MS,
        "custom_vocabulary": not args.no_vocab,
        "variants": [],
    }
    for fmt, ep in variants:
        rows = []
        for text, pcm, rate in clips:
            if fmt == "ulaw_8k":
                audio = pcm16_to_ulaw(resample_pcm16(pcm, rate, 8000))
                config, bpf, silence = (
                    telephone_config(endpointing=ep, vocabulary=vocab),
                    160,
                    b"\xff",
                )
            else:
                audio = resample_pcm16(pcm, rate, 16000)
                config = telephone_config(endpointing=ep, vocabulary=vocab)
                config.update(
                    {"encoding": "wav/pcm", "sample_rate": 16000, "bit_depth": 16}
                )
                bpf, silence = 640, b"\x00"
            row = await run_one(text, audio, config, bpf, silence)
            print(
                json.dumps(
                    {"format": fmt, "endpointing": ep, **row}, ensure_ascii=False
                ),
                file=sys.stderr,
            )
            rows.append(row)
        lat = [
            r["last_final_ms_after_speech_end"]
            for r in rows
            if r["last_final_ms_after_speech_end"] is not None
        ]
        part = [
            r["first_partial_ms_after_speech_start"]
            for r in rows
            if r["first_partial_ms_after_speech_start"] is not None
        ]
        out["variants"].append(
            {
                "format": fmt,
                "endpointing_s": ep,
                "median_final_after_speech_end_ms": statistics.median(lat)
                if lat
                else None,
                "max_final_after_speech_end_ms": max(lat) if lat else None,
                "median_first_partial_ms": statistics.median(part) if part else None,
                "mean_wer": round(statistics.mean(r["wer"] for r in rows), 3),
                "rows": rows,
            }
        )
    os.makedirs("results", exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            [{k: v for k, v in x.items() if k != "rows"} for x in out["variants"]],
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
