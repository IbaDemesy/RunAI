"""Local persistence for the runner profile shared with H agents."""

from pathlib import Path

from pydantic import ValidationError

from runai.config import get_settings
from runai.models import RunnerProfile


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else get_settings().traces_dir / "profile.json"

    def load(self) -> RunnerProfile:
        try:
            return RunnerProfile.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return RunnerProfile()

    def save(self, profile: RunnerProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        self.path.chmod(0o600)
