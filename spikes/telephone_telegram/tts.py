"""Synthese vocale pour le canal telephone. Gladia ne fait pas de TTS : briques interchangeables.

Toutes les implementations renvoient du mu-law 8 kHz pret a etre envoye a Twilio (sauf TwilioSay, qui produit du TwiML).
"""

import asyncio
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from xml.sax.saxutils import escape

import httpx
from g711 import pcm16_to_ulaw, resample_pcm16

DEFAULT_PIPER_VOICE = os.environ.get(
    "PIPER_VOICE", os.path.expanduser("~/piper_voices/fr_FR-siwis-medium.onnx")
)


@dataclass
class TTSResult:
    ulaw_8k: bytes
    first_audio_ms: float  # temps jusqu'au premier octet audio disponible
    total_ms: float  # temps jusqu'a l'audio complet
    audio_seconds: float


class PiperTTS:
    """Piper local (onnxruntime, CPU). Le modele est charge une fois, la synthese est streamee par phrase."""

    name = "piper"

    def __init__(self, model_path: str = DEFAULT_PIPER_VOICE):
        from piper import PiperVoice

        t0 = time.perf_counter()
        self.voice = PiperVoice.load(model_path)
        self.load_ms = (time.perf_counter() - t0) * 1000

    def synthesize(self, text: str) -> TTSResult:
        t0 = time.perf_counter()
        first = None
        out = bytearray()
        for chunk in self.voice.synthesize(text):
            pcm = resample_pcm16(chunk.audio_int16_bytes, chunk.sample_rate, 8000)
            out += pcm16_to_ulaw(pcm)
            if first is None:
                first = (time.perf_counter() - t0) * 1000
        total = (time.perf_counter() - t0) * 1000
        return TTSResult(bytes(out), first or total, total, len(out) / 8000)

    async def asynthesize(self, text: str) -> TTSResult:
        return await asyncio.to_thread(self.synthesize, text)


class EspeakTTS:
    """espeak-ng (robotique, mais zero dependance reseau). Plan C."""

    name = "espeak-ng"

    def __init__(self, voice: str = "fr"):
        if not shutil.which("espeak-ng"):
            raise RuntimeError("espeak-ng absent (sudo apt-get install -y espeak-ng)")
        self.voice = voice

    def synthesize(self, text: str) -> TTSResult:
        t0 = time.perf_counter()
        wav = subprocess.run(
            ["espeak-ng", "-v", self.voice, "--stdout", text],
            capture_output=True,
            check=True,
        ).stdout
        pcm = wav[44:]  # en-tete WAV standard 44 octets, 22050 Hz mono 16 bits
        ulaw = pcm16_to_ulaw(resample_pcm16(pcm, 22050, 8000))
        total = (time.perf_counter() - t0) * 1000
        return TTSResult(ulaw, total, total, len(ulaw) / 8000)

    async def asynthesize(self, text: str) -> TTSResult:
        return await asyncio.to_thread(self.synthesize, text)


class ElevenLabsTTS:
    """ElevenLabs en streaming, sortie native ulaw_8000 (aucune conversion). Cle : ELEVENLABS_API_KEY. Non mesure (pas de cle)."""

    name = "elevenlabs"

    def __init__(
        self,
        voice_id: str | None = None,
        model_id: str = "eleven_flash_v2_5",
        api_key: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY manquante")
        self.voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")
        if not self.voice_id:
            raise RuntimeError(
                "ELEVENLABS_VOICE_ID manquant (choisir une voix FR dans la Voice Library)"
            )
        self.model_id = model_id

    async def asynthesize(self, text: str) -> TTSResult:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
        t0 = time.perf_counter()
        first = None
        out = bytearray()
        async with (
            httpx.AsyncClient(timeout=30) as client,
            client.stream(
                "POST",
                url,
                params={"output_format": "ulaw_8000"},
                headers={"xi-api-key": self.api_key},
                json={"text": text, "model_id": self.model_id, "language_code": "fr"},
            ) as resp,
        ):
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                out += chunk
        total = (time.perf_counter() - t0) * 1000
        return TTSResult(bytes(out), first or total, total, len(out) / 8000)


class OpenAITTS:
    """OpenAI /v1/audio/speech, response_format=pcm (24 kHz 16 bits) -> 8 kHz mu-law. Cle : OPENAI_API_KEY. Non mesure (pas de cle).

    Attention : la doc OpenAI annonce l'arret de tts-1 / gpt-4o-mini-tts le 6 janvier 2027.
    """

    name = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        api_key: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY manquante")
        self.model = model
        self.voice = voice

    async def asynthesize(self, text: str) -> TTSResult:
        t0 = time.perf_counter()
        first = None
        pcm = bytearray()
        async with (
            httpx.AsyncClient(timeout=30) as client,
            client.stream(
                "POST",
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "voice": self.voice,
                    "input": text,
                    "response_format": "pcm",
                },
            ) as resp,
        ):
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                pcm += chunk
        ulaw = pcm16_to_ulaw(resample_pcm16(bytes(pcm), 24000, 8000))
        total = (time.perf_counter() - t0) * 1000
        return TTSResult(ulaw, first or total, total, len(ulaw) / 8000)


def twilio_say(
    text: str, voice: str = "Google.fr-FR-Standard-A", language: str = "fr-FR"
) -> str:
    """TTS natif Twilio : un verbe TwiML <Say>, synthese cote Twilio (aucune latence chez nous, mais hors flux bidirectionnel)."""
    return f'<Say voice="{escape(voice)}" language="{escape(language)}">{escape(text)}</Say>'


def build_tts(name: str | None = None):
    """Choix par variable RUNAI_TTS (piper par defaut), repli espeak-ng si Piper indisponible."""
    name = name or os.environ.get("RUNAI_TTS", "piper")
    if name == "elevenlabs":
        return ElevenLabsTTS()
    if name == "openai":
        return OpenAITTS()
    if name == "espeak-ng":
        return EspeakTTS()
    try:
        return PiperTTS()
    except (ImportError, OSError):
        return EspeakTTS()
