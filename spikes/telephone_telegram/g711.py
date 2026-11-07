"""Codec G.711 mu-law (format audio Twilio Media Streams) et reechantillonnage, sans dependance."""

from array import array

_BIAS = 0x84
_CLIP = 32635


def _encode_sample(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    sample = min(sample, _CLIP) + _BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not sample & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _decode_byte(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    sample = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return -sample if sign else sample


_ENCODE_TABLE = bytes(_encode_sample(s) for s in range(-32768, 32768))
_DECODE_TABLE = array("h", (_decode_byte(b) for b in range(256)))


def pcm16_to_ulaw(pcm: bytes) -> bytes:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    return bytes(_ENCODE_TABLE[s + 32768] for s in samples)


def ulaw_to_pcm16(data: bytes) -> bytes:
    return array("h", (_DECODE_TABLE[b] for b in data)).tobytes()


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Reechantillonnage lineaire mono 16 bits (suffisant pour la voix telephonique)."""
    if src_rate == dst_rate:
        return pcm
    src = array("h")
    src.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not src:
        return b""
    n_out = int(len(src) * dst_rate / src_rate)
    step = src_rate / dst_rate
    out = array("h")
    last = len(src) - 1
    for i in range(n_out):
        pos = i * step
        j = int(pos)
        frac = pos - j
        a = src[min(j, last)]
        b = src[min(j + 1, last)]
        out.append(int(a + (b - a) * frac))
    return out.tobytes()


def frames(data: bytes, size: int):
    for i in range(0, len(data), size):
        yield data[i : i + size]
