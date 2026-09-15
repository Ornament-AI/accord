"""CSRF synchronizer-token middleware (pure ASGI).

Cookie-authenticated unsafe requests (POST/PUT/PATCH/DELETE) must carry the
``accord_csrf`` cookie and echo its exact value back in the ``X-CSRF-Token``
header. The cookie value is a server-signed token bound to the SHA-256 of the
session cookie value, so a same-site sibling app that can plant cookies still
cannot forge the binding. Requests without a session cookie pass straight
through — downstream auth returns 401 — which auto-exempts the login,
magic-code, OAuth callback, and WorkOS webhook entry points without an
exemption list.
"""

from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.responses import problem_response
from app.auth.session import verify_csrf_token
from app.config import get_settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER_NAME = "x-csrf-token"


class CsrfMiddleware:
    """Enforce the session-bound synchronizer CSRF token on mutations."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        settings = get_settings()
        session_cookie = request.cookies.get(settings.session_cookie_name)
        if not session_cookie:
            # Unauthenticated entry points (login, magic-code, OAuth callback,
            # WorkOS webhook) carry no session cookie and fail closed at the
            # auth layer instead.
            await self.app(scope, receive, send)
            return

        csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        valid = (
            csrf_cookie is not None
            and csrf_header is not None
            and hmac.compare_digest(csrf_header, csrf_cookie)
            and verify_csrf_token(settings, session_cookie, csrf_cookie)
        )
        if valid:
            await self.app(scope, receive, send)
            return

        request_id = getattr(request.state, "request_id", None)
        response = problem_response(
            status_code=403,
            detail="CSRF token missing or invalid.",
            instance=str(request.url.path),
            error="CsrfTokenInvalid",
            request_id=request_id,
            headers={"X-Request-ID": request_id} if request_id else None,
        )
        await response(scope, receive, send)
