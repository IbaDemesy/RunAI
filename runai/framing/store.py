"""Persist framing conversations so a restart does not erase an unfinished one (24 h retention)."""

import contextlib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from runai.contracts.framing import FramingSession
from runai.redaction import redact_secrets

logger = logging.getLogger(__name__)
_FRAMING_ID = re.compile(r"[0-9a-f]{32}")
RETENTION_SECONDS = 24 * 3600


class FramingStore:
    def __init__(self, directory: Path, retention_s: float = RETENTION_SECONDS):
        self.directory = Path(directory)
        self.retention_s = retention_s

    def save(self, session: FramingSession) -> None:
        if not _FRAMING_ID.fullmatch(session.id):
            return
        temporary = None
        try:
            content = json.dumps(redact_secrets(session.model_dump(mode="json")), ensure_ascii=False)
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory,
                prefix=f".{session.id}-", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
            os.replace(temporary, self.directory / f"{session.id}.json")
        except (OSError, ValueError):
            logger.warning("Could not save framing %s", session.id)
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def load(self) -> list[FramingSession]:
        """Return the conversations still worth restoring; expired or unreadable files are dropped."""
        sessions = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                if path.is_symlink() or not _FRAMING_ID.fullmatch(path.stem):
                    continue
                if time.time() - path.stat().st_mtime > self.retention_s:
                    path.unlink(missing_ok=True)
                    continue
                session = FramingSession.model_validate(json.loads(path.read_text(encoding="utf-8")))
                if session.id == path.stem:
                    sessions.append(session)
            except (OSError, ValueError):
                logger.warning("Skipping invalid framing file %s", path.name)
        return sessions
