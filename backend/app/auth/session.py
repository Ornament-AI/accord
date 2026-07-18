"""Session stores: Phase-1 signed payload (tests) + Phase-2 DB-backed opaque id.

Production request handling uses ``DatabaseSessionStore`` (opaque signed session
row UUID → Postgres ``sessions`` row). ``SignedCookieSessionStore`` remains for
unit tests that exercise the Phase-1 payload cookie shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import WeakSessionSecretError
from app.config import Settings
from app.models.base import utcnow
from app.models.identity import Session as SessionRow

# Absolute session lifetime (mirrors ADR-0002).
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
LAST_SEEN_THROTTLE_SECONDS = 60
OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60
MIN_SESSION_SECRET_LENGTH = 16

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
    """Seam for applying/clearing browser session cookies."""

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


def _cookie_serializer(settings: Settings) -> URLSafeTimedSerializer:
    _assert_session_secret_strength(settings)
    return URLSafeTimedSerializer(
        secret_key=settings.session_secret_key,
        salt=_SESSION_SALT,
    )


def _apply_cookie(settings: Settings, response: Response, cookie_value: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=cookie_value,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def _clear_cookie(settings: Settings, response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


class SignedCookieSessionStore:
    """Phase 1 ``SessionStore`` using itsdangerous URLSafeTimedSerializer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._serializer = _cookie_serializer(settings)

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
        _apply_cookie(self._settings, response, cookie_value)

    def clear_session_cookie(self, response: Response) -> None:
        _clear_cookie(self._settings, response)


class DatabaseSessionStore:
    """Postgres-backed session store keyed by signed opaque session row UUID."""

    def __init__(self, settings: Settings, session: AsyncSession) -> None:
        self._settings = settings
        self._db = session
        self._serializer = _cookie_serializer(settings)

    def _sign(self, session_id: UUID) -> str:
        return self._serializer.dumps(str(session_id))

    def _unsign(self, cookie_value: str) -> UUID | None:
        if not cookie_value:
            return None
        try:
            # Intentionally no max_age here for logout/revoke — absolute expiry is
            # enforced on read via the sessions.expires_at column.
            raw = self._serializer.loads(cookie_value)
        except (BadSignature, SignatureExpired):
            return None
        try:
            return UUID(str(raw))
        except (TypeError, ValueError):
            return None

    def parse_session_id(self, cookie_value: str) -> UUID | None:
        """Return the session UUID from a signed cookie, or None if invalid."""
        return self._unsign(cookie_value)

    async def create_session(
        self,
        *,
        user_id: UUID,
        active_organization_id: UUID | None = None,
        user_agent_hash: str | None = None,
    ) -> str:
        now = utcnow()
        row = SessionRow(
            user_id=user_id,
            active_organization_id=active_organization_id,
            issued_at=now,
            expires_at=now + timedelta(seconds=SESSION_MAX_AGE_SECONDS),
            last_seen_at=now,
            user_agent_hash=user_agent_hash,
        )
        self._db.add(row)
        await self._db.flush()
        return self._sign(row.id)

    async def read_session(self, cookie_value: str) -> SessionRow | None:
        session_id = self._unsign(cookie_value)
        if session_id is None:
            return None
        row = await self._db.get(SessionRow, session_id)
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        now = utcnow()
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if now > expires_at:
            return None
        last_seen = row.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        idle_seconds = (now - last_seen).total_seconds()
        if idle_seconds > self._settings.session_idle_timeout_seconds:
            return None
        if idle_seconds > LAST_SEEN_THROTTLE_SECONDS:
            row.last_seen_at = now
            await self._db.flush()
            await self._db.commit()
        return row

    async def revoke_session(self, session_id: UUID) -> None:
        row = await self._db.get(SessionRow, session_id)
        if row is None or row.revoked_at is not None:
            return
        row.revoked_at = utcnow()
        await self._db.flush()

    async def rotate_session(
        self,
        *,
        old_session_id: UUID,
        user_id: UUID,
        active_organization_id: UUID | None,
        user_agent_hash: str | None = None,
    ) -> str:
        await self.revoke_session(old_session_id)
        return await self.create_session(
            user_id=user_id,
            active_organization_id=active_organization_id,
            user_agent_hash=user_agent_hash,
        )

    def apply_session_cookie(self, response: Response, cookie_value: str) -> None:
        _apply_cookie(self._settings, response, cookie_value)

    def clear_session_cookie(self, response: Response) -> None:
        _clear_cookie(self._settings, response)


def get_session_store(settings: Settings, db: AsyncSession) -> DatabaseSessionStore:
    """Production path: opaque signed session id backed by Postgres."""
    return DatabaseSessionStore(settings, db)


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
