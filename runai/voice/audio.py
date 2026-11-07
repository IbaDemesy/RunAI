"""Sources audio PCM 16 bits mono : fichier (local ou URL), micro, découpées en morceaux."""

import asyncio
import io
import shutil
import subprocess
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx

SUPPORTED_SAMPLE_RATES = (8000, 16000, 32000, 44100, 48000)
DEFAULT_SAMPLE_RATE = 16000
CHUNK_MS = 100
BYTES_PER_SAMPLE = 2


class AudioError(RuntimeError):
    pass


@dataclass
class AudioStream:
    sample_rate: int
    chunks: AsyncIterator[bytes]


def load_pcm(source: str | Path | bytes) -> tuple[bytes, int]:
    """Lit un WAV PCM 16 bits mono tel quel ; convertit tout autre format avec ffmpeg en 16 kHz."""
    data = source if isinstance(source, bytes) else _read_bytes(source)
    if data[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(data)) as wav:
                if (
                    wav.getsampwidth() == BYTES_PER_SAMPLE
                    and wav.getnchannels() == 1
                    and wav.getframerate() in SUPPORTED_SAMPLE_RATES
                ):
                    return wav.readframes(wav.getnframes()), wav.getframerate()
        except wave.Error:
            pass
    return _ffmpeg_to_pcm(data), DEFAULT_SAMPLE_RATE


def _read_bytes(source: str | Path) -> bytes:
    text = str(source)
    if text.startswith(("http://", "https://")):
        response = httpx.get(text, follow_redirects=True, timeout=60)
        response.raise_for_status()
        if response.content.startswith(b"version https://git-lfs"):
            raise AudioError("Pointeur Git LFS reçu : utiliser media.githubusercontent.com/media/...")
        return response.content
    return Path(source).read_bytes()


def _ffmpeg_to_pcm(data: bytes) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise AudioError("ffmpeg est requis pour convertir ce format (ou fournir un WAV PCM 16 bits mono).")
    result = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
         "-ar", str(DEFAULT_SAMPLE_RATE), "pipe:1"],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AudioError(f"Conversion ffmpeg impossible : {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def chunk_size(sample_rate: int, chunk_ms: int = CHUNK_MS) -> int:
    return sample_rate * BYTES_PER_SAMPLE * chunk_ms // 1000


async def pcm_chunks(
    pcm: bytes, sample_rate: int, *, realtime: bool = True, chunk_ms: int = CHUNK_MS
) -> AsyncIterator[bytes]:
    """Découpe le PCM ; `realtime=True` envoie au rythme de la parole, comme un micro."""
    size = chunk_size(sample_rate, chunk_ms)
    for offset in range(0, len(pcm), size):
        yield pcm[offset:offset + size]
        await asyncio.sleep(chunk_ms / 1000 if realtime else 0)


def file_stream(source: str | Path, *, realtime: bool = True) -> AudioStream:
    pcm, sample_rate = load_pcm(source)
    return AudioStream(sample_rate, pcm_chunks(pcm, sample_rate, realtime=realtime))


def microphone_stream(sample_rate: int = DEFAULT_SAMPLE_RATE, chunk_ms: int = CHUNK_MS) -> AudioStream:
    """Micro local via `sounddevice` (optionnel : `pip install sounddevice`, PortAudio requis)."""
    try:
        import sounddevice
    except (ImportError, OSError) as error:
        raise AudioError("Micro indisponible : installer sounddevice (et PortAudio).") from error

    async def chunks() -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def callback(indata, frames, time, status) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

        with sounddevice.RawInputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=chunk_size(sample_rate, chunk_ms) // BYTES_PER_SAMPLE,
            callback=callback,
        ):
            while True:
                yield await queue.get()

    return AudioStream(sample_rate, chunks())
