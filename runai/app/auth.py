"""Optional HTTP Basic authentication; only the health probe is public."""

import base64
import binascii
import math
import secrets
import time

from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_PATHS = frozenset({"/api/health"})


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp, credentials: str):
        pairs = [pair.strip() for pair in credentials.split(",")]
        for pair in pairs:
            user, sep, password = pair.partition(":")
            if not sep or not user or not password:
                raise ValueError("RUNAI_BASIC_AUTH must contain user:password pairs separated by commas")
        self.app = app
        self.expected = [pair.encode() for pair in pairs]
        self.failures: dict[str, list[float]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] in PUBLIC_PATHS
        ):
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        self.failures = {
            ip: recent for ip, attempts in self.failures.items()
            if (recent := [stamp for stamp in attempts if now - stamp < 60])
        }
        forwarded = dict(scope["headers"]).get(b"x-forwarded-for", b"")
        client = scope.get("client")
        ip = forwarded.decode("latin-1").split(",", 1)[0].strip() or (client[0] if client else "unknown")
        attempts = self.failures.get(ip, [])
        if len(attempts) >= 5:
            status = 429
            headers = [(b"retry-after", str(max(1, math.ceil(60 - (now - attempts[0])))).encode())]
            body = b"Too many authentication attempts. Try again later."
        elif self._authorized(scope):
            await self.app(scope, receive, send)
            return
        else:
            self.failures.setdefault(ip, []).append(now)
            status = 401
            headers = [(b"www-authenticate", b'Basic realm="RunAI", charset="UTF-8"')]
            body = b"Authentication required"
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

    def _authorized(self, scope: Scope) -> bool:
        header = dict(scope["headers"]).get(b"authorization", b"")
        scheme, _, token = header.partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            decoded = base64.b64decode(token, validate=True)
        except (binascii.Error, ValueError):
            return False
        matches = [secrets.compare_digest(decoded, expected) for expected in self.expected]
        return any(matches)
