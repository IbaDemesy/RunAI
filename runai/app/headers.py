"""Streaming-safe response security headers for the public entry point."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; "
    "connect-src 'self' https://unpkg.com https://*.hcompany.ai wss://api.gladia.io https://api.gladia.io "
    "https://tile.openstreetmap.org https://tiles.mapterhorn.com https://tiles.maps.eox.at; "
    "worker-src 'self' blob:; "
    "frame-src 'self' https://*.hcompany.ai; frame-ancestors 'none'"
)
# The simulated live view (/demo/live) is embedded by the app itself in an iframe.
FRAMEABLE_PATHS = frozenset({"/demo/live"})
SELF_FRAMING_CSP = CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, enforce: bool = False, public: bool = False):
        self.app = app
        self.enforce = enforce
        self.headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy" if enforce else b"content-security-policy-report-only", CSP.encode()),
        ]
        if public:
            self.headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                additions = list(self.headers)
                if scope["path"] in FRAMEABLE_PATHS and message["status"] == 200:
                    csp_name = b"content-security-policy" if self.enforce else b"content-security-policy-report-only"
                    additions = [
                        (b"x-frame-options", b"SAMEORIGIN") if name == b"x-frame-options"
                        else (name, SELF_FRAMING_CSP.encode()) if name == csp_name else (name, value)
                        for name, value in additions
                    ]
                if scope["path"].startswith("/api/"):
                    additions.append((b"cache-control", b"no-store"))
                names = {name for name, _ in additions}
                message = {**message, "headers": [
                    (name, value) for name, value in message.get("headers", [])
                    if name.lower() not in names
                ] + additions}
            await send(message)

        await self.app(scope, receive, send_with_headers)
