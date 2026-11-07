"""Génère le scénario audio de test (espeak-ng, fr, 16 kHz mono) et les offsets des phrases."""

import json
import subprocess
import sys
import wave
from pathlib import Path

RATE = 16000
SCENARIO = [
    (1.0, "Stop, attends une seconde."),
    (12.0, "C'est bon, reprends."),
    (8.0, "Non, cherche plutôt le semi-marathon de Paris."),
    (8.0, "Parfait, je valide."),
]
TAIL_S = 3.0


def tts(text: str, engine: str) -> bytes:
    if engine == "gtts":
        import io

        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(text, lang="fr").write_to_fp(buf)
        audio = buf.getvalue()
    else:
        audio = subprocess.run(["espeak-ng", "-v", "fr", "-s", "155", "--stdout", text],
                               check=True, capture_output=True).stdout
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(RATE),
                           "-f", "s16le", "pipe:1"], input=audio, check=True, capture_output=True).stdout


def build(out: Path, engine: str) -> dict:
    pcm, phrases = b"", []
    for gap, text in SCENARIO:
        pcm += b"\x00\x00" * int(gap * RATE)
        start = len(pcm) / 2 / RATE
        pcm += tts(text, engine)
        phrases.append({"text": text, "start": round(start, 3), "end": round(len(pcm) / 2 / RATE, 3)})
    pcm += b"\x00\x00" * int(TAIL_S * RATE)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    meta = {"wav": out.name, "tts": engine, "duration_s": round(len(pcm) / 2 / RATE, 3), "phrases": phrases}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


if __name__ == "__main__":
    # python make_audio.py [espeak|gtts] [sortie.wav] ; gtts demande `pip install gTTS` et du réseau.
    engine = sys.argv[1] if len(sys.argv) > 1 else "espeak"
    default = Path(__file__).parent / "audio" / f"scenario_{engine}.wav"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else default
    target.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build(target, engine), ensure_ascii=False, indent=2))
