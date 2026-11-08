"""Logging configuration: JSON or text lines, request ids, secrets redaction.

`RUNAI_LOG_FORMAT=json|text` (json by default on Render or with `RUNAI_PUBLIC=1`)
and `RUNAI_LOG_LEVEL` (INFO by default).
"""

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from runai.redaction import redact_secrets

_request_id: ContextVar[str | None] = ContextVar("runai_request_id", default=None)
_HANDLER_NAME = "runai"
_STD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "color_message"}
_ALIGNED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
SSE_PATH_SUFFIX = "/events"

logger = logging.getLogger("runai.http")


def request_id() -> str | None:
    """Id of the HTTP request being handled, if any."""
    return _request_id.get()


def _extras(record: logging.LogRecord) -> dict:
    extras = {key: value for key, value in vars(record).items() if key not in _STD_ATTRS}
    if "request_id" not in extras and (current := request_id()):
        extras["request_id"] = current
    return extras


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(redact_secrets(payload), default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        if extras := _extras(record):
            line += " " + " ".join(f"{key}={value}" for key, value in extras.items())
        return redact_secrets(line)


def default_format(env=None) -> str:
    env = os.environ if env is None else env
    explicit = env.get("RUNAI_LOG_FORMAT", "").strip().lower()
    if explicit in {"json", "text"}:
        return explicit
    return "json" if env.get("RUNAI_PUBLIC") == "1" or env.get("RENDER") else "text"


def configure_logging(force: bool = False) -> logging.Handler:
    """Install one handler on the root logger (idempotent) and route uvicorn to it."""
    root = logging.getLogger()
    level = os.getenv("RUNAI_LOG_LEVEL", "INFO").upper()
    handler = next((h for h in root.handlers if h.get_name() == _HANDLER_NAME), None)
    if handler is None or force:
        if handler is not None:
            root.removeHandler(handler)
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(_HANDLER_NAME)
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter() if default_format() == "json" else TextFormatter())
    root.setLevel(level)
    for name in _ALIGNED_LOGGERS:
        aligned = logging.getLogger(name)
        aligned.handlers = []
        aligned.propagate = True
    # Our 'request' lines replace uvicorn's access lines (they add request id and latency).
    logging.getLogger("uvicorn.access").disabled = True
    return handler


def is_sse_path(path: str) -> bool:
    return path.startswith("/api/missions/") and path.endswith(SSE_PATH_SUFFIX)


class RequestIdMiddleware:
    """Read or generate `X-Request-ID`, echo it, and log one line per non-SSE request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1").strip()
        rid = incoming[:128] if incoming and incoming.isprintable() else uuid.uuid4().hex
        token = _request_id.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", rid.encode("latin-1"))]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if not is_sse_path(scope["path"]):
                logger.info(
                    "request",
                    extra={
                        "request_id": rid,
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            _request_id.reset(token)
