"""Persist browser frames without blocking mission event delivery."""

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from runai.config import get_settings
from runai.models import StepKind

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_FRAMES = 60
CAPTURE_TTL_S = 24 * 60 * 60
logger = logging.getLogger(__name__)


class CaptureStore:
    def __init__(self, traces_dir: Path | None = None):
        self.root = (traces_dir or get_settings().traces_dir) / "screenshots"
        self.tasks: set[asyncio.Task] = set()
        self._seen: set[tuple] = set()
        self._locks: dict[tuple, asyncio.Lock] = {}

    def directory(self, mission_id: str, kind: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", mission_id) or kind not in StepKind._value2member_map_:
            raise ValueError("Invalid screenshot path")
        path = (self.root / mission_id / kind).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Invalid screenshot path")
        return path

    def frame_path(self, mission_id: str, kind: str, revision: int) -> Path:
        if type(revision) is not int or revision < 1:
            raise ValueError("Invalid screenshot revision")
        path = self.directory(mission_id, kind) / f"{revision}.png"
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Invalid screenshot path")
        return path

    def index(self, mission_id: str, kind: str) -> list[dict]:
        path = self.directory(mission_id, kind) / "index.json"
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Invalid screenshot path")
        entries = json.loads(path.read_text()) if path.exists() else []
        return [entry for entry in entries if self.frame_path(mission_id, kind, entry["revision"]).exists()]

    def purge(self) -> None:
        cutoff = time.time() - CAPTURE_TTL_S
        for path in self.root.glob("*/*/*.png"):
            try:
                if not path.is_symlink() and path.resolve().is_relative_to(self.root.resolve()) and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                logger.warning("Could not purge expired screenshot %s", path)

    def schedule(self, mission_id: str, kind: StepKind, observation: dict, run) -> None:
        revision = observation.get("revision")
        key = (mission_id, kind.value, revision)
        if type(revision) is not int or revision < 1 or key in self._seen:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Cannot capture screenshot without a running event loop")
            return
        self._seen.add(key)
        task = loop.create_task(self._capture(mission_id, kind.value, dict(observation), run))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _capture(self, mission_id: str, kind: str, observation: dict, run) -> None:
        try:
            lock = self._locks.setdefault((mission_id, kind), asyncio.Lock())
            async with lock:
                entries = await asyncio.to_thread(self.index, mission_id, kind)
                revision = observation["revision"]
                if len(entries) >= MAX_FRAMES or any(e["revision"] == revision for e in entries):
                    return
                async with asyncio.timeout(20):
                    content = await run.get_screenshot()
                current = getattr(run, "browser_observation", None)
                if current is not None and current.get("revision") != revision:
                    return
                if content is None or not content.startswith(PNG_MAGIC):
                    raise ValueError("Invalid PNG screenshot")
                entry = {key: observation.get(key) for key in ("revision", "url", "title")}
                entry["at"] = datetime.now(UTC).isoformat()
                await asyncio.to_thread(self._write, mission_id, kind, content, entries + [entry])
        except Exception:
            self._seen.discard((mission_id, kind, observation["revision"]))
            logger.warning("Could not capture screenshot for %s/%s", mission_id, kind, exc_info=True)

    def _write(self, mission_id: str, kind: str, content: bytes, entries: list[dict]) -> None:
        self.purge()
        path = self.frame_path(mission_id, kind, entries[-1]["revision"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        temporary = path.parent / "index.json.tmp"
        temporary.write_text(json.dumps(entries), encoding="utf-8")
        temporary.replace(path.parent / "index.json")
