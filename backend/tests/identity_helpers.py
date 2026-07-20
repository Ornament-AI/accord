"""Shared helpers for Phase-2 identity / auth / organization tests."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.adapters import DevAuthAdapter
from app.config import Settings, get_settings
from app.models.base import utcnow
from app.models.identity import Organization, OrganizationMembership, User
from app.models.identity import Session as SessionRow


def settings(**overrides: Any) -> Settings:
    """Build Settings via model_construct for tests (bypass env/production validators)."""
    base: dict[str, Any] = dict(
        database_url="postgresql+asyncpg://accord@localhost/accord_test",
        migrations_database_url="postgresql+asyncpg://accord@localhost/accord_test",
        environment="development",
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="http://localhost:8000/api/auth/callback",
        workos_webhook_secret="",
        session_secret_key="test-session-secret-key",
        session_cookie_name="accord_session",
        session_idle_timeout_seconds=7200,
        workos_webhook_tolerance_seconds=300,
        dev_auth_bypass=True,
        dev_auth_email="dev@accord.local",
        dev_auth_name="Dev Test User",
        accord_allow_weak_secrets=True,
        base_url="http://localhost:5173",
        public_app_url="http://localhost:5173",
    )
    base.update(overrides)
    return Settings.model_construct(**base)


# Back-compat alias used by package conftests / tests.
_settings = settings


def patch_get_settings(monkeypatch, value: Settings) -> None:
    """Patch get_settings at every import site used by identity routes/deps."""
    monkeypatch.setattr("app.api.routes.auth.get_settings", lambda: value)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: value)
    monkeypatch.setattr("app.config.get_settings", lambda: value)


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def session_cookie_from_response(response) -> str | None:
    """Extract the accord_session cookie value from an httpx response."""
    if "accord_session" in response.cookies:
        return response.cookies["accord_session"]
    set_cookie = response.headers.get("set-cookie", "")
    if "accord_session=" not in set_cookie:
        return None
    part = set_cookie.split("accord_session=", 1)[1]
    return part.split(";", 1)[0]


_session_cookie_from_response = session_cookie_from_response


async def login_dev(client, *, follow_redirects: bool = False):
    """GET /api/auth/login under DEV_AUTH_BYPASS; return (response, cookie)."""
    response = await client.get("/api/auth/login", follow_redirects=follow_redirects)
    cookie = session_cookie_from_response(response)
    if cookie:
        client.cookies.set("accord_session", cookie)
    return response, cookie


async def seed_user(
    db: AsyncSession,
    *,
    workos_user_id: str | None = None,
    email: str | None = None,
    name: str = "Seed User",
    is_platform_admin: bool = False,
) -> User:
    user = User(
        workos_user_id=workos_user_id or f"workos_{uuid4().hex[:12]}",
        email=email or f"user-{uuid4().hex[:8]}@example.com",
        name=name,
        is_platform_admin=is_platform_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def seed_organization(
    db: AsyncSession,
    *,
    name: str = "Seed Org",
    slug: str | None = None,
    is_active: bool = True,
) -> Organization:
    org = Organization(
        name=name,
        slug=slug or f"org-{uuid4().hex[:10]}",
        is_active=is_active,
    )
    db.add(org)
    await db.flush()
    return org


async def seed_membership(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str = "organization_administrator",
    is_active: bool = True,
) -> OrganizationMembership:
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        is_active=is_active,
    )
    db.add(membership)
    await db.flush()
    return membership


async def seed_session_row(
    db: AsyncSession,
    *,
    user_id: UUID,
    active_organization_id: UUID | None = None,
    expires_at=None,
    last_seen_at=None,
    revoked_at=None,
) -> SessionRow:
    now = utcnow()
    row = SessionRow(
        user_id=user_id,
        active_organization_id=active_organization_id,
        issued_at=now,
        expires_at=expires_at if expires_at is not None else now + timedelta(hours=12),
        last_seen_at=last_seen_at if last_seen_at is not None else now,
        revoked_at=revoked_at,
    )
    db.add(row)
    await db.flush()
    return row


async def user_by_workos_id(db: AsyncSession, workos_user_id: str) -> User | None:
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.workos_user_id == workos_user_id))
    return result.scalar_one_or_none()


DEV_SUBJECT = DevAuthAdapter.DEV_SUBJECT_ID
