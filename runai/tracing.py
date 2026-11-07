import re
from pathlib import Path

from runai.config import get_settings
from runai.models import TraceEvent
from runai.redaction import redact_secrets

_MISSION_ID = re.compile(r"[A-Za-z0-9_-]+")


class TraceWriter:
    """Journal JSONL d'une mission : sert au replay, au debug et à la boucle de réparation Devin."""

    def __init__(self, mission_id: str, traces_dir: Path | None = None):
        if not _MISSION_ID.fullmatch(mission_id):
            raise ValueError(f"mission_id invalide : {mission_id!r}")
        directory = traces_dir or get_settings().traces_dir
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{mission_id}.jsonl"

    def write(self, event: TraceEvent) -> None:
        event = TraceEvent.model_validate(redact_secrets(event.model_dump(mode="json")))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def read(self) -> list[TraceEvent]:
        if not self.path.exists():
            return []
        return [
            TraceEvent.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
