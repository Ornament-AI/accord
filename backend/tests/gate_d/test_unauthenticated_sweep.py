"""Programmatic unauthenticated sweep over all registered /api routes.

Allowlist is verified against route source (session-auth not required):
- GET /api/healthz, GET /api/readyz — health.py (no deps)
- GET /api/auth/login, GET /api/auth/callback — auth.py (public entry)
- POST /api/auth/logout — auth.py (idempotent 204 without cookie)
- POST /api/auth/webhooks/workos — auth.py (HMAC auth, not session cookie)

Route discovery walks ``app.routes``, unwrapping FastAPI ``_IncludedRouter``
nodes so nested ``APIRoute`` instances (with include prefixes) are covered.
Future routes are picked up automatically — no hardcoded protected-route list.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute

from app.main import app

# Session-unauthenticated by design (verified against route handlers).
_PUBLIC_API_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/healthz"),
        ("GET", "/api/readyz"),
        ("GET", "/api/auth/login"),
        ("GET", "/api/auth/callback"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/webhooks/workos"),
    }
)


def _walk_api_routes(routes, *, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield (METHOD, full_path) for every APIRoute under ``routes``."""
    for route in routes:
        if isinstance(route, APIRoute):
            path = prefix + route.path
            for method in sorted(route.methods or ()):
                if method in {"HEAD", "OPTIONS"}:
                    continue
                yield method, path
            continue

        # FastAPI >=0.128 nests include_router as _IncludedRouter.
        original = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original is not None and include_context is not None:
            nested_prefix = prefix + (getattr(include_context, "prefix", None) or "")
            yield from _walk_api_routes(original.routes, prefix=nested_prefix)
            continue

        nested = getattr(route, "routes", None)
        if nested is not None:
            nested_prefix = prefix + (getattr(route, "path", None) or "")
            yield from _walk_api_routes(nested, prefix=nested_prefix)


def _protected_api_routes() -> list[tuple[str, str]]:
    protected: list[tuple[str, str]] = []
    for method, path in _walk_api_routes(app.routes):
        if not path.startswith("/api"):
            continue
        key = (method, path)
        if key in _PUBLIC_API_ROUTES:
            continue
        protected.append(key)
    # Deduplicate when a route is registered under both "" and "/".
    return sorted(set(protected))


@pytest.mark.asyncio
async def test_all_non_public_api_routes_reject_unauthenticated_requests(client):
    protected = _protected_api_routes()
    assert protected, "expected at least one protected /api route"

    failures: list[str] = []
    for method, path in protected:
        resp = await client.request(method, path)
        if resp.status_code != 401:
            failures.append(f"{method} {path} → {resp.status_code} (body={resp.text[:200]})")

    assert not failures, "unauthenticated sweep failures:\n" + "\n".join(failures)


@pytest.mark.asyncio
async def test_public_api_allowlist_routes_do_not_require_session_cookie(client):
    """Smoke: allowlisted routes are reachable without accord_session."""
    health = await client.get("/api/healthz")
    assert health.status_code == 200

    ready = await client.get("/api/readyz")
    assert ready.status_code == 200

    login = await client.get("/api/auth/login", follow_redirects=False)
    assert login.status_code in {302, 503}

    callback = await client.get("/api/auth/callback", follow_redirects=False)
    assert callback.status_code == 302

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 204

    webhook = await client.post("/api/auth/webhooks/workos", content=b"{}")
    # Missing/invalid HMAC → 401 WebhookUnauthorized (not session auth).
    assert webhook.status_code == 401
