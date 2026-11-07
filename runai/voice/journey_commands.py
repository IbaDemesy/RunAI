"""Targeted journey controls, independent of the V1 mission parser."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from runai.contracts.framing import FramingReply
from runai.contracts.journey import ChapterId


@dataclass(frozen=True)
class JourneyCommand:
    target: Literal["agents", "camera", "journey"]
    action: Literal["pause", "resume", "play", "show_chapter", "seek_km"]
    chapter_id: ChapterId | None = None
    seek_km: float | None = None


CHAPTER_PHRASES = {
    ChapterId.home: ("maison", "domicile", "home"),
    ChapterId.departure_hub: (
        "gare",
        "aeroport",
        "departure hub",
        "station",
        "airport",
    ),
    ChapterId.main_transport: (
        "trajet",
        "transport",
        "train",
        "vol",
        "journey",
        "flight",
    ),
    ChapterId.arrival_hotel: ("hotel",),
    ChapterId.bib_pickup: ("dossard", "retrait du dossard", "bib pickup", "bib"),
    ChapterId.race: ("course", "race"),
    ChapterId.return_trip: ("retour", "return trip", "return"),
}


def _normalize(text: str) -> str:
    text = "".join(
        c
        for c in unicodedata.normalize("NFD", text.lower())
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", text.replace("’", "'").strip().rstrip(".!?"))


def parse_journey_command(transcript: str) -> JourneyCommand | None:
    text = _normalize(transcript)
    camera = r"(?:la |le |the )?(?:camera|survol|flyover)"
    if re.fullmatch(rf"(?:pause|arrete|stop|mets en pause|pause the) {camera}", text):
        return JourneyCommand("camera", "pause")
    if re.fullmatch(rf"(?:reprends|continue|relance|resume|play) {camera}", text):
        return JourneyCommand("camera", "play")
    if re.fullmatch(
        r"(?:pause|stop|mets en pause)(?: (?:les |the )?agents)?|agents pause", text
    ):
        return JourneyCommand("agents", "pause")
    if re.fullmatch(
        r"(?:reprends|continue|resume)(?: (?:les |the )?agents)?|agents resume", text
    ):
        return JourneyCommand("agents", "resume")
    match = re.fullmatch(
        r"(?:(?:va au|go to) )?(?:km|kilometre|kilometer|kilometres|kilometers) (\d+(?:[.,]\d+)?)",
        text,
    )
    if match:
        km = float(match[1].replace(",", "."))
        if km < float("inf"):
            return JourneyCommand("journey", "seek_km", seek_km=km)
    chapter_text = re.sub(r"^(?:voir|montre moi|montre|show me|show) ", "", text)
    chapter_text = re.sub(r"^(?:la |le |les |the |l')", "", chapter_text)
    for chapter, phrases in CHAPTER_PHRASES.items():
        if chapter_text in phrases:
            return JourneyCommand("journey", "show_chapter", chapter_id=chapter)
    return None


def build_voice_reply(transcript: str, revision: int) -> FramingReply:
    return FramingReply(revision=revision, text=transcript, channel="voice")
