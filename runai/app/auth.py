"""Optional HTTP Basic authentication; only the health probe is public."""

import base64
import binascii
import math
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256

from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_PATHS = frozenset({"/api/health"})


@dataclass
class FailureWindow:
    expires: float
    count: int = 0
    blocked_until: float = 0


class BasicAuthMiddleware:
    max_failure_keys = 4096

    def __init__(self, app: ASGIApp, credentials: str):
        pairs = [pair.strip() for pair in credentials.split(",")]
        for pair in pairs:
            user, sep, password = pair.partition(":")
            if not sep or not user or not password:
                raise ValueError("RUNAI_BASIC_AUTH must contain user:password pairs separated by commas")
        self.app = app
        self.expected = [pair.encode() for pair in pairs]
        self.failures: OrderedDict[str, FailureWindow] = OrderedDict()
        self.username_failures: OrderedDict[str, FailureWindow] = OrderedDict()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in PUBLIC_PATHS:
            scope.setdefault("state", {})["basic_authenticated"] = self._authorized(self._credentials(scope))
        if (
            scope["type"] not in {"http", "websocket"}
            or (scope["type"] == "http" and scope["path"] in PUBLIC_PATHS)
        ):
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        self._expire(self.failures, now)
        self._expire(self.username_failures, now)
        forwarded = dict(scope["headers"]).get(b"x-forwarded-for", b"")
        client = scope.get("client")
        ip = forwarded.decode("latin-1").rsplit(",", 1)[-1].strip() or (client[0] if client else "unknown")
        ip = sha256(ip.encode()).hexdigest()
        decoded = self._credentials(scope)
        username = sha256(decoded.partition(b":")[0]).hexdigest() if decoded else None
        attempts = self.failures.get(ip)
        user_attempts = self.username_failures.get(username)
        blocked_until = attempts.expires if attempts and attempts.count >= 5 else 0
        authorized = self._authorized(decoded)
        if not blocked_until and authorized:
            await self.app(scope, receive, send)
            return
        if not blocked_until and user_attempts:
            blocked_until = user_attempts.blocked_until
        if blocked_until > now:
            status = 429
            headers = [(b"retry-after", str(max(1, math.ceil(blocked_until - now))).encode())]
            body = b"Too many authentication attempts. Try again later."
        else:
            self._record(self.failures, ip, now)
            if username:
                user_attempts = self._record(self.username_failures, username, now)
                if user_attempts.count >= 10:
                    delay = min(30, 2 ** min(5, user_attempts.count - 10))
                    user_attempts.blocked_until = min(user_attempts.expires, now + delay)
            status = 401
            headers = [(b"www-authenticate", b'Basic realm="RunAI", charset="UTF-8"')]
            body = b"Authentication required"
        if scope["type"] == "websocket":
            if "websocket.http.response" in scope.get("extensions", {}):
                await send({"type": "websocket.http.response.start", "status": 403 if status == 401 else status, "headers": headers})
                await send({"type": "websocket.http.response.body", "body": body})
            else:
                await receive()
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers + [
                    (b"content-type", b"text/plain; charset=utf-8"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": body}
        )

    @staticmethod
    def _expire(table: OrderedDict[str, FailureWindow], now: float) -> None:
        while table and next(iter(table.values())).expires <= now:
            table.popitem(last=False)

    def _record(self, table: OrderedDict[str, FailureWindow], key: str, now: float) -> FailureWindow:
        if key not in table:
            if len(table) >= self.max_failure_keys:
                table.popitem(last=False)
            table[key] = FailureWindow(expires=now + 60)
        window = table[key]
        window.count = min(15, window.count + 1)
        return window

    def _credentials(self, scope: Scope) -> bytes | None:
        header = dict(scope["headers"]).get(b"authorization", b"")
        scheme, _, token = header.partition(b" ")
        if scheme.lower() != b"basic":
            return None
        try:
            return base64.b64decode(token, validate=True)
        except (binascii.Error, ValueError):
            return None

    def _authorized(self, decoded: bytes | None) -> bool:
        matches = [secrets.compare_digest(decoded, expected) for expected in self.expected] if decoded is not None else []
        return any(matches)
