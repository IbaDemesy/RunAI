"""Atomic, redacted mission documents for single-process restart recovery."""

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from runai.config import get_settings
from runai.contracts.framing import FramingSummary, FramingTurn
from runai.contracts.journey import JourneyPlan
from runai.contracts.mission import EventEnvelope, MissionSnapshot
from runai.framing.launch import LaunchPlan
from runai.models import TraceEvent
from runai.redaction import redact_secrets
from runai.tracing import _MISSION_ID

logger = logging.getLogger(__name__)
SAVE_INTERVAL_SECONDS = 0.5
_POSIX = os.name == "posix"


class StoredMission(BaseModel):
    schema_version: Literal["mission-store.v1"] = "mission-store.v1"
    snapshot: MissionSnapshot
    envelopes: list[EventEnvelope] = Field(default_factory=list)
    framing_summary: FramingSummary | None = None
    framing_turns: list[FramingTurn] = Field(default_factory=list)
    plan: LaunchPlan
    created_at: datetime
    finished_at: datetime | None = None
    user_id: str | None = None
    journey: JourneyPlan | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "StoredMission":
        mission_id = self.snapshot.mission_id
        if not _MISSION_ID.fullmatch(mission_id):
            raise ValueError("Invalid mission ID")
        if self.snapshot.sequence != len(self.envelopes):
            raise ValueError("Snapshot and event sequence disagree")
        for sequence, event in enumerate(self.envelopes, 1):
            if (event.mission_id, event.sequence, event.event_id) != (mission_id, sequence, f"{mission_id}:{sequence}"):
                raise ValueError("Invalid stored event identity or sequence")
            if event.type == "trace":
                TraceEvent.model_validate(event.payload)
        if any(question.mission_id != mission_id for question in self.snapshot.questions):
            raise ValueError("Invalid stored question identity")
        if self.journey and (self.journey.mission_id != mission_id or self.journey.revision != self.snapshot.journey_revision):
            raise ValueError("Invalid stored journey identity or revision")
        return self


class MissionStore:
    def __init__(self, traces_dir: Path | None = None):
        self.directory = (traces_dir or get_settings().traces_dir) / "missions"
        self._last_saved: dict[str, float] = {}
        self._pending: dict[str, Callable[[], StoredMission]] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}

    def save(self, mission_id: str, document: Callable[[], StoredMission], *, terminal: bool = False) -> None:
        if not _MISSION_ID.fullmatch(mission_id):
            raise ValueError("Invalid mission ID")
        self._pending[mission_id] = document
        remaining = SAVE_INTERVAL_SECONDS - (time.monotonic() - self._last_saved.get(mission_id, float("-inf")))
        if terminal or remaining <= 0:
            self._flush(mission_id)
        elif mission_id not in self._timers:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            self._timers[mission_id] = loop.call_later(remaining, self._flush, mission_id)

    def _flush(self, mission_id: str) -> None:
        if timer := self._timers.pop(mission_id, None):
            timer.cancel()
        factory = self._pending.pop(mission_id, None)
        if factory is None:
            return
        temporary = None
        try:
            document = factory()
            if document.snapshot.mission_id != mission_id:
                raise ValueError("Stored mission ID does not match destination")
            content = json.dumps(redact_secrets(document.model_dump(mode="json")), ensure_ascii=False)
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=f".{mission_id}-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.directory / f"{mission_id}.json")
            if _POSIX:
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            self._last_saved[mission_id] = time.monotonic()
        except (OSError, ValueError) as error:
            logger.warning("Could not save mission %s: %s", redact_secrets(mission_id),
                           redact_secrets(f"{type(error).__name__}: {error}"))
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def load(self) -> list[StoredMission]:
        documents = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                if path.is_symlink() or not _MISSION_ID.fullmatch(path.stem):
                    raise ValueError("Invalid mission file")
                document = StoredMission.model_validate(redact_secrets(json.loads(path.read_text(encoding="utf-8"))))
                if document.snapshot.mission_id != path.stem:
                    raise ValueError("Stored mission ID does not match filename")
            except (OSError, ValueError):
                logger.warning("Skipping invalid mission file %s", redact_secrets(path.name))
                continue
            documents.append(document)
        return documents
