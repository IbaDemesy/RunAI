"""Mot de passe optionnel devant l'app (HTTP Basic), pour un hébergement de POC.

Activé par `RUNAI_BASIC_AUTH=utilisateur:motdepasse`. `/api/health` reste ouvert
pour les sondes de l'hébergeur ; il n'expose que le mode (démo ou réel).
"""

import base64
import binascii
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_PATHS = frozenset({"/api/health"})


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp, credentials: str):
        user, sep, password = credentials.partition(":")
        if not sep or not user or not password:
            raise ValueError("RUNAI_BASIC_AUTH doit être au format utilisateur:motdepasse")
        self.app = app
        self.expected = credentials.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] in PUBLIC_PATHS
            or self._authorized(scope)
        ):
            await self.app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", b'Basic realm="RunAI", charset="UTF-8"'),
                    (b"content-type", b"text/plain; charset=utf-8"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"Mot de passe requis"}
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
        return secrets.compare_digest(decoded, self.expected)
