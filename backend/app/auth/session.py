"""Signed-cookie session store (Phase 1) behind a SessionStore Protocol seam.

Phase 2 must swap this Protocol's implementation for a Postgres-row-backed store
keyed by an opaque session id, add rotation on privilege changes, add
server-side revocation, add ``active_organization_id`` to the payload, and add
idle-timeout / absolute-TTL enforcement server-side. Cookie attributes and the
``SessionStore`` method surface should stay stable across that swap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.errors import WeakSessionSecretError
from app.auth.principal import AuthPrincipal
from app.config import Settings, get_settings

# Absolute session lifetime (mirrors ADR-0002). Idle timeout is Phase 2.
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60
MIN_SESSION_SECRET_LENGTH = 16

# Phase 1 placeholder role — real role resolution from organization_memberships
# is Phase 2. Matches AuthPrincipal.dev_test() so local admin checks keep working.
PHASE1_PLACEHOLDER_ROLE = "organization_administrator"

_SESSION_SALT = "accord-session-v1"
_OAUTH_STATE_SALT = "accord-oauth-state-v1"


@dataclass(frozen=True, slots=True)
class SessionPayload:
    """Identity fields stored in the Phase 1 signed session cookie."""

    workos_user_id: str
    email: str
    name: str | None
    issued_at: str


class SessionStore(Protocol):
    """Seam for creating/reading/clearing browser sessions.

    Phase 2 needs: swap this Protocol's implementation for a Postgres-row-backed
    store keyed by opaque session id, add rotation on privilege changes, add
    server-side revocation, add ``active_organization_id`` to the payload, add
    idle-timeout/absolute-TTL enforcement server-side.
    """

    async def create_session(self, payload: SessionPayload) -> str:
        """Persist a session and return the opaque cookie value."""
        ...

    async def read_session(self, cookie_value: str) -> SessionPayload | None:
        """Return the payload for a cookie value, or None if invalid/expired."""
        ...

    def apply_session_cookie(self, response: Response, cookie_value: str) -> None:
        """Attach the session cookie with ADR-0002 attributes."""
        ...

    def clear_session_cookie(self, response: Response) -> None:
        """Expire/clear the session cookie on the response."""
        ...


def _assert_session_secret_strength(settings: Settings) -> None:
    """Lazy secret-strength check — not run during Settings model validation."""
    secret = settings.session_secret_key or ""
    if len(secret) < MIN_SESSION_SECRET_LENGTH and not settings.accord_allow_weak_secrets:
        raise WeakSessionSecretError(
            f"SESSION_SECRET_KEY must be at least {MIN_SESSION_SECRET_LENGTH} characters "
            "(or set ACCORD_ALLOW_WEAK_SECRETS=1 for local/test use)."
        )
    if not secret:
        raise WeakSessionSecretError("SESSION_SECRET_KEY is required to sign sessions.")


class SignedCookieSessionStore:
    """Phase 1 ``SessionStore`` using itsdangerous URLSafeTimedSerializer."""

    def __init__(self, settings: Settings) -> None:
        _assert_session_secret_strength(settings)
        self._settings = settings
        self._serializer = URLSafeTimedSerializer(
            secret_key=settings.session_secret_key,
            salt=_SESSION_SALT,
        )

    async def create_session(self, payload: SessionPayload) -> str:
        return self._serializer.dumps(asdict(payload))

    async def read_session(self, cookie_value: str) -> SessionPayload | None:
        if not cookie_value:
            return None
        try:
            data: dict[str, Any] = self._serializer.loads(
                cookie_value,
                max_age=SESSION_MAX_AGE_SECONDS,
            )
        except (BadSignature, SignatureExpired):
            return None
        try:
            return SessionPayload(
                workos_user_id=str(data["workos_user_id"]),
                email=str(data["email"]),
                name=data.get("name"),
                issued_at=str(data["issued_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def apply_session_cookie(self, response: Response, cookie_value: str) -> None:
        response.set_cookie(
            key=self._settings.session_cookie_name,
            value=cookie_value,
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
            httponly=True,
            secure=self._settings.is_production,
            samesite="lax",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=self._settings.session_cookie_name,
            path="/",
            httponly=True,
            secure=self._settings.is_production,
            samesite="lax",
        )


def get_session_store(settings: Settings | None = None) -> SignedCookieSessionStore:
    return SignedCookieSessionStore(settings or get_settings())


def session_payload_from_identity(
    *,
    workos_user_id: str,
    email: str,
    name: str | None,
) -> SessionPayload:
    return SessionPayload(
        workos_user_id=workos_user_id,
        email=email,
        name=name,
        issued_at=datetime.now(UTC).isoformat(),
    )


def principal_from_session(payload: SessionPayload) -> AuthPrincipal:
    """Map a Phase 1 session payload into AuthPrincipal.

    ``user_id`` and ``subject_id`` are both the WorkOS user id until a local
    users table exists. Role is a Phase 1 placeholder.
    """
    return AuthPrincipal(
        user_id=payload.workos_user_id,
        subject_id=payload.workos_user_id,
        email=payload.email,
        role=PHASE1_PLACEHOLDER_ROLE,
        is_active=True,
        display_name=payload.name,
        organization_id=None,
    )


async def resolve_principal_from_session(request: Request) -> AuthPrincipal | None:
    """Read the signed session cookie and return an AuthPrincipal, or None."""
    settings = get_settings()
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        return None
    try:
        store = get_session_store(settings)
    except WeakSessionSecretError:
        return None
    payload = await store.read_session(cookie_value)
    if payload is None:
        return None
    return principal_from_session(payload)


def _state_serializer(settings: Settings) -> URLSafeTimedSerializer:
    _assert_session_secret_strength(settings)
    return URLSafeTimedSerializer(
        secret_key=settings.session_secret_key,
        salt=_OAUTH_STATE_SALT,
    )


def sign_oauth_state(settings: Settings, *, redirect_to: str | None = None) -> str:
    """Sign an anti-CSRF OAuth state value (no sensitive data embedded)."""
    payload: dict[str, str] = {"n": uuid4().hex}
    if redirect_to:
        payload["r"] = redirect_to
    return _state_serializer(settings).dumps(payload)


def verify_oauth_state(settings: Settings, state: str) -> dict[str, str] | None:
    """Verify a signed OAuth state; return payload or None if invalid/expired."""
    if not state:
        return None
    try:
        data = _state_serializer(settings).loads(state, max_age=OAUTH_STATE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired, WeakSessionSecretError):
        return None
    if not isinstance(data, dict) or "n" not in data:
        return None
    return {str(k): str(v) for k, v in data.items()}
