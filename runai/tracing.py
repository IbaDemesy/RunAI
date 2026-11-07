from pathlib import Path

from runai.config import get_settings
from runai.models import TraceEvent


class TraceWriter:
    """Journal JSONL d'une mission : sert au replay, au debug et à la boucle de réparation Devin."""

    def __init__(self, mission_id: str, traces_dir: Path | None = None):
        directory = traces_dir or get_settings().traces_dir
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{mission_id}.jsonl"

    def write(self, event: TraceEvent) -> None:
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
