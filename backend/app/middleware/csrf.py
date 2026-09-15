"""CSRF synchronizer-token middleware (pure ASGI).

Cookie-authenticated unsafe requests (POST/PUT/PATCH/DELETE) must carry the
``accord_csrf`` cookie and echo its exact value back in the ``X-CSRF-Token``
header. The cookie value is a server-signed token bound to the SHA-256 of the
session cookie value, so a same-site sibling app that can plant cookies still
cannot forge the binding. Requests without a session cookie pass straight
through — downstream auth returns 401 — which auto-exempts the login,
magic-code, OAuth callback, and WorkOS webhook entry points without an
exemption list.

Sessions that predate the CSRF rollout (valid session cookie, no ``accord_csrf``
cookie) are re-minted a session-bound token on any response — safe requests
self-heal transparently, and a rejected mutation attaches the fresh cookie so
the client's next attempt succeeds. The minted token still requires the
session cookie itself, so this never weakens the binding.
"""

from __future__ import annotations

import hmac

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.responses import problem_response
from app.auth.session import (
    WeakSessionSecretError,
    apply_csrf_cookie,
    verify_csrf_token,
)
from app.config import get_settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER_NAME = "x-csrf-token"


def _send_with_csrf_cookie(
    send: Send,
    settings,
    session_cookie: str,
) -> Send:
    """Attach a freshly minted session-bound ``accord_csrf`` Set-Cookie."""

    async def send_with_cookie(message: Message) -> None:
        if message["type"] == "http.response.start":
            probe = Response()
            try:
                apply_csrf_cookie(settings, probe, session_cookie)
            except WeakSessionSecretError:
                pass
            headers = MutableHeaders(raw=message.setdefault("headers", []))
            for key, value in probe.raw_headers:
                if key.lower() == b"set-cookie":
                    headers.append("set-cookie", value.decode("latin-1"))
        await send(message)

    return send_with_cookie


class CsrfMiddleware:
    """Enforce the session-bound synchronizer CSRF token on mutations."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
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
        bound_valid = csrf_cookie is not None and verify_csrf_token(
            settings, session_cookie, csrf_cookie
        )

        if scope["method"] not in UNSAFE_METHODS:
            if bound_valid:
                await self.app(scope, receive, send)
            else:
                # Legacy/expired token: refresh the bound cookie so the client
                # has one before its next mutation.
                await self.app(
                    scope,
                    receive,
                    _send_with_csrf_cookie(send, settings, session_cookie),
                )
            return

        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        valid = (
            bound_valid
            and csrf_header is not None
            and csrf_cookie is not None
            and hmac.compare_digest(csrf_header, csrf_cookie)
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
        if not bound_valid:
            # Attach a fresh bound token so a pre-existing session recovers on
            # the next attempt instead of staying locked out until expiry.
            try:
                apply_csrf_cookie(settings, response, session_cookie)
            except WeakSessionSecretError:
                pass
        await response(scope, receive, send)
