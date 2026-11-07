"""File d'attente FIFO devant les slots H (3 pour toute l'organisation)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable

from .adapters.base import Quota

log = logging.getLogger(__name__)


class SlotTimeout(Exception):
    pass


class SlotScheduler:
    """Un slot local par session H vivante, et en tete de file on verifie aussi le quota H de l'org
    (les autres equipes consomment les memes 3 slots). Si available == 0 on re-verifie toutes les
    poll_s secondes, jusqu'a max_wait_s."""

    def __init__(self, limit: int = 3, quota_fn: Callable[[], Awaitable[Quota | None]] | None = None,
                 poll_s: float = 60.0, max_wait_s: float = 600.0):
        self.limit = limit
        self.quota_fn = quota_fn
        self.poll_s = poll_s
        self.max_wait_s = max_wait_s
        self.held: set[str] = set()
        self.queue: deque[str] = deque()
        self.last_quota: Quota | None = None
        self._cond = asyncio.Condition()

    def position(self, mid: str) -> int | None:
        try:
            return self.queue.index(mid)
        except ValueError:
            return None

    async def _h_available(self) -> bool:
        if self.quota_fn is None:
            return True
        try:
            self.last_quota = await self.quota_fn()
        except Exception as e:  # noqa: BLE001 - reseau: on laisse le queue=True de H servir de filet
            log.warning("quota H illisible: %s", type(e).__name__)
            return True
        return self.last_quota is None or self.last_quota.available > 0

    async def acquire(self, mid: str) -> None:
        deadline = time.monotonic() + self.max_wait_s
        async with self._cond:
            self.queue.append(mid)
        acquired = False
        try:
            while True:
                async with self._cond:
                    await self._cond.wait_for(lambda: self.queue[0] == mid and len(self.held) < self.limit)
                    if await self._h_available():
                        self.queue.popleft()
                        self.held.add(mid)
                        acquired = True
                        self._cond.notify_all()
                        return
                if time.monotonic() + self.poll_s > deadline:
                    raise SlotTimeout(f"quota H plein depuis {self.max_wait_s:.0f} s")
                await asyncio.sleep(self.poll_s)
        finally:
            if not acquired:
                async with self._cond:
                    if mid in self.queue:
                        self.queue.remove(mid)
                    self._cond.notify_all()

    async def release(self, mid: str) -> None:
        async with self._cond:
            self.held.discard(mid)
            self._cond.notify_all()
