from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from runai.models import TraceEvent, utcnow


class CommandKind(str, Enum):
    new_mission = "new_mission"
    pause = "pause"
    resume = "resume"
    correction = "correction"
    cancel = "cancel"


class CorrectionTarget(str, Enum):
    registration = "registration"
    date = "date"
    accommodation = "accommodation"
    transport = "transport"
    race = "race"
    budget = "budget"
    other = "other"


class CommandSource(str, Enum):
    voice = "voice"
    keyboard = "keyboard"


class RaceQuery(BaseModel):
    """Course telle que dite par le coureur : indices à confirmer par la recherche Linkup."""

    name: str | None = None
    city: str | None = None
    origin: str | None = None
    country: str | None = None
    distance_km: float | None = None
    date_text: str | None = None


class VoiceCommand(BaseModel):
    """Commande typée, identique qu'elle vienne de la voix ou du clavier."""

    kind: CommandKind
    race: RaceQuery | None = None
    target: CorrectionTarget | None = None
    detail: str | None = None


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    at: datetime = Field(default_factory=utcnow)
    utterance_id: str
    text: str
    is_final: bool
    language: str | None = None
    start: float | None = None
    end: float | None = None
    confidence: float | None = None


class CommandEvent(BaseModel):
    """Événement publié vers l'app web ; `early` = déclenché sur une transcription partielle."""

    type: Literal["command"] = "command"
    at: datetime = Field(default_factory=utcnow)
    command: VoiceCommand
    source: CommandSource
    text: str
    utterance_id: str | None = None
    language: str | None = None
    early: bool = False

    def to_trace_event(self) -> TraceEvent:
        return TraceEvent(
            at=self.at,
            source=self.source.value,
            type=f"command.{self.command.kind.value}",
            message=self.text,
            data=self.model_dump(mode="json", exclude={"type", "at"}),
        )


VoiceEvent = TranscriptEvent | CommandEvent
