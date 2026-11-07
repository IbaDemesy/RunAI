"""Détection d'intentions vocales (règles, français) pour piloter un agent H."""

import re
import unicodedata
from dataclasses import dataclass

PAUSE = "pause"
RESUME = "resume"
VALIDATE = "validate"
CORRECTION = "correction"

_PAUSE_RE = re.compile(r"\b(stop+|pause|attends?|arrete|arretez|halte)\b")
_LEADING_NO_RE = re.compile(r"^\s*non\b")
_RESUME_RE = re.compile(r"\b(reprends?|reprenez|continue|continuez|vas[- ]y|repars)\b")
_VALIDATE_RE = re.compile(r"\b(je valide|c est valide|valide|je confirme)\b")
_CORRECTION_RE = re.compile(
    r"\b(plutot|a la place|en fait|change|corrige|prends|cherche|moins de|plus de|pas le|pas la)\b"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 -]+", " ", text).replace("'", " ")


@dataclass(frozen=True)
class Intent:
    name: str
    text: str


def detect_fast(text: str) -> str | None:
    """Intentions déclenchables sur un partiel (avant la fin de la phrase)."""
    t = normalize(text)
    if _PAUSE_RE.search(t) or _LEADING_NO_RE.search(t):
        return PAUSE
    if _RESUME_RE.search(t):
        return RESUME
    if _VALIDATE_RE.search(t):
        return VALIDATE
    return None


def is_correction(text: str) -> bool:
    """Une correction exige la phrase complète : on ne la teste que sur un final."""
    return bool(_CORRECTION_RE.search(normalize(text)))


def correction_text(text: str) -> str:
    """Retire l'interjection de tête ("Non, attends,") avant d'envoyer à l'agent."""
    return re.sub(r"^\s*(non|stop|attends?)[\s,.!]*", "", text, flags=re.IGNORECASE).strip() or text
