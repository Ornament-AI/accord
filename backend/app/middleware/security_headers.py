"""Security headers middleware (pure ASGI) — hardens non-preflight responses.

Adds standard security headers to HTTP responses that reach this middleware.
OPTIONS requests are left untouched so CORSMiddleware can handle preflight
responses exclusively.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

# ---------------------------------------------------------------------------
# Header definitions
# ---------------------------------------------------------------------------

_SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    # Disabled in favour of CSP; modern browsers ignore this header when CSP
    # is present, but the value 0 explicitly opts out of XSS auditors that
    # could introduce secondary vulnerabilities.
    "x-xss-protection": "0",
    "content-security-policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware:
    """Injects security headers into every non-preflight HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip CORS preflight — CORSMiddleware owns OPTIONS responses.
        if scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in _SECURITY_HEADERS.items():
                    headers.append((name.encode(), value.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
