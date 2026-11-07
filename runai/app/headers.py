"""Streaming-safe response security headers for the public entry point."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data: blob: https:; "
    "connect-src 'self' https://unpkg.com https://*.hcompany.ai wss://api.gladia.io https://api.gladia.io; "
    "frame-src https://agp.eu.hcompany.ai https://*.hcompany.ai; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, enforce: bool = False):
        self.app = app
        self.headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy" if enforce else b"content-security-policy-report-only", CSP.encode()),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                additions = list(self.headers)
                if scope["path"].startswith("/api/"):
                    additions.append((b"cache-control", b"no-store"))
                names = {name for name, _ in additions}
                message = {**message, "headers": [
                    (name, value) for name, value in message.get("headers", [])
                    if name.lower() not in names
                ] + additions}
            await send(message)

        await self.app(scope, receive, send_with_headers)
