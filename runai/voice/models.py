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
    """Race as spoken by the runner: hints to confirm through Linkup search."""

    name: str | None = None
    city: str | None = None
    origin: str | None = None
    country: str | None = None
    distance_km: float | None = None
    date_text: str | None = None


class VoiceCommand(BaseModel):
    """Typed command, identical whether from voice or keyboard."""

    kind: CommandKind
    race: RaceQuery | None = None
    target: CorrectionTarget | None = None
    detail: str | None = None


class _GladiaEvent(BaseModel):
    provider: Literal["gladia"] = "gladia"
    model: str = "solaria-1"
    received_at: datetime = Field(default_factory=utcnow)


class TranscriptEvent(_GladiaEvent):
    """A complete replacement for an utterance, never text to append.

    Partials with the same utterance_id replace the previous provisional text.
    Stream revisions increase per utterance, including its final update, so
    consumers can discard older updates that arrive out of order downstream.
    """

    type: Literal["transcript"] = "transcript"
    at: datetime = Field(default_factory=utcnow)
    utterance_id: str
    revision: int = Field(default=1, ge=1)
    text: str
    is_final: bool
    language: str | None = None
    start: float | None = None
    end: float | None = None
    confidence: float | None = None


class TranslationEvent(_GladiaEvent):
    """Translation correlated with TranscriptEvent.utterance_id."""

    type: Literal["translation"] = "translation"
    utterance_id: str
    source_language: str
    target_language: str
    text: str


class Entity(BaseModel):
    type: str
    text: str
    start: float
    end: float


class EntitiesEvent(_GladiaEvent):
    """Named entities correlated with TranscriptEvent.utterance_id."""

    type: Literal["entities"] = "entities"
    utterance_id: str
    entities: list[Entity]


class SpeechEvent(_GladiaEvent):
    type: Literal["speech"] = "speech"
    kind: Literal["start", "end"]
    time: float


class WarningEvent(_GladiaEvent):
    """A nonfatal addon failure; transcription can continue."""

    type: Literal["warning"] = "warning"
    event_type: str
    message: str


class CommandEvent(BaseModel):
    """Event published to the web app; `early` means triggered by a partial transcript."""

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


VoiceEvent = TranscriptEvent | TranslationEvent | EntitiesEvent | SpeechEvent | WarningEvent | CommandEvent
