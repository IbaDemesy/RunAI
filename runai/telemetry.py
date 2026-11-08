"""Bounded, process-local provider call diagnostics."""

import logging
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from math import ceil
from threading import Lock
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from runai.redaction import redact_secrets

Provider = Literal["linkup", "holo", "gladia", "h"]
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
logger = logging.getLogger("runai.telemetry")


class ProviderCall(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    provider: Provider
    operation: str
    started_at: datetime
    duration_ms: float
    ok: bool
    error: str | None = None
    correlation_id: str | None = None
    meta: dict = Field(default_factory=dict)


class CallLog:
    def __init__(self, maxlen: int = 2000):
        self._calls: deque[ProviderCall] = deque(maxlen=maxlen)
        self._lock = Lock()

    def record(self, call: ProviderCall) -> None:
        call = ProviderCall.model_validate(redact_secrets(call.model_dump()))
        with self._lock:
            self._calls.append(call)
        logger.info("%s", call.model_dump_json())

    def list(self, correlation_id=None, provider=None, limit=None) -> list[ProviderCall]:
        with self._lock:
            calls = [call.model_copy(deep=True) for call in self._calls
                     if (correlation_id is None or call.correlation_id == correlation_id)
                     and (provider is None or call.provider == provider)]
        return calls if limit is None else calls[-limit:] if limit > 0 else []

    def summary(self) -> dict:
        calls = self.list()
        result = {}
        for provider in dict.fromkeys(call.provider for call in calls):
            group = [call for call in calls if call.provider == provider]
            durations = sorted(call.duration_ms for call in group)
            result[provider] = {
                "count": len(group), "error_rate": sum(not call.ok for call in group) / len(group),
                "p50": durations[ceil(len(group) * .5) - 1],
                "p95": durations[ceil(len(group) * .95) - 1],
                "est_cost_usd": sum(call.meta.get("est_cost_usd", 0) or 0 for call in group),
            }
        return result


default_log = CallLog()


@contextmanager
def correlate(id: str):
    token = correlation_id.set(id)
    try:
        yield
    finally:
        correlation_id.reset(token)


class timed:
    def __init__(self, provider: Provider, operation: str, **meta):
        self.provider, self.operation, self.meta = provider, operation, meta

    def __enter__(self):
        self.started_at = datetime.now(UTC)
        self.start = perf_counter()
        self.correlation = correlation_id.get()
        return self

    def __exit__(self, exc_type, exc, traceback):
        default_log.record(ProviderCall(
            provider=self.provider, operation=self.operation, started_at=self.started_at,
            duration_ms=(perf_counter() - self.start) * 1000, ok=exc is None,
            error=redact_secrets(str(exc)) if exc is not None else None,
            correlation_id=self.correlation, meta=self.meta,
        ))
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *args):
        return self.__exit__(*args)
