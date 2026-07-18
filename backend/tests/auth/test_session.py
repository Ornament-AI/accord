"""Unit tests for signed-cookie + DatabaseSessionStore and OAuth state."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import Response

from app.auth.errors import WeakSessionSecretError
from app.auth.session import (
    DatabaseSessionStore,
    SignedCookieSessionStore,
    session_payload_from_identity,
    sign_oauth_state,
    verify_oauth_state,
)
from app.models.base import utcnow
from app.models.identity import Session as SessionRow
from tests.identity_helpers import seed_user, settings as _settings


@pytest.mark.asyncio
async def test_signed_cookie_round_trip():
    store = SignedCookieSessionStore(_settings())
    payload = session_payload_from_identity(
        workos_user_id="user_123",
        email="user@example.com",
        name="User Example",
    )
    cookie = await store.create_session(payload)
    loaded = await store.read_session(cookie)
    assert loaded is not None
    assert loaded.workos_user_id == "user_123"
    assert loaded.email == "user@example.com"
    assert loaded.name == "User Example"


@pytest.mark.asyncio
async def test_tampered_cookie_returns_none():
    store = SignedCookieSessionStore(_settings())
    payload = session_payload_from_identity(
        workos_user_id="user_123",
        email="user@example.com",
        name=None,
    )
    cookie = await store.create_session(payload)
    assert await store.read_session(cookie + "tamper") is None
    assert await store.read_session("not-a-valid-cookie") is None


def test_weak_secret_rejected_lazily_when_not_allowed():
    settings = _settings(session_secret_key="short", accord_allow_weak_secrets=False)
    with pytest.raises(WeakSessionSecretError):
        SignedCookieSessionStore(settings)


def test_weak_secret_allowed_when_flag_set():
    settings = _settings(session_secret_key="short", accord_allow_weak_secrets=True)
    store = SignedCookieSessionStore(settings)
    assert store is not None


def test_oauth_state_round_trip_and_tamper_rejection():
    settings = _settings()
    state = sign_oauth_state(settings)
    assert verify_oauth_state(settings, state) is not None
    assert verify_oauth_state(settings, state + "x") is None
    assert verify_oauth_state(settings, "") is None


def test_clear_session_cookie_sets_expiry():
    store = SignedCookieSessionStore(_settings())
    response = Response()
    store.clear_session_cookie(response)
    set_cookie = response.headers.get("set-cookie", "")
    assert "accord_session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


@pytest.mark.asyncio
async def test_database_session_store_create_read_round_trip(session):
    user = await seed_user(session, workos_user_id="db_sess_rt")
    await session.commit()

    store = DatabaseSessionStore(_settings(session_idle_timeout_seconds=7200), session)
    cookie = await store.create_session(user_id=user.id)
    await session.commit()

    row = await store.read_session(cookie)
    assert row is not None
    assert row.user_id == user.id
    assert row.revoked_at is None
    assert store.parse_session_id(cookie) == row.id


@pytest.mark.asyncio
async def test_database_session_store_rejects_expired(session):
    user = await seed_user(session, workos_user_id="db_sess_exp")
    await session.commit()
    store = DatabaseSessionStore(_settings(), session)
    cookie = await store.create_session(user_id=user.id)
    await session.commit()

    sid = store.parse_session_id(cookie)
    row = await session.get(SessionRow, sid)
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=5)
    await session.commit()

    assert await store.read_session(cookie) is None


@pytest.mark.asyncio
async def test_database_session_store_rejects_idle_stale(session):
    user = await seed_user(session, workos_user_id="db_sess_idle")
    await session.commit()
    cfg = _settings(session_idle_timeout_seconds=7200)
    store = DatabaseSessionStore(cfg, session)
    cookie = await store.create_session(user_id=user.id)
    await session.commit()

    sid = store.parse_session_id(cookie)
    row = await session.get(SessionRow, sid)
    assert row is not None
    row.last_seen_at = utcnow() - timedelta(seconds=cfg.session_idle_timeout_seconds + 30)
    await session.commit()

    assert await store.read_session(cookie) is None


@pytest.mark.asyncio
async def test_database_session_store_rejects_revoked(session):
    user = await seed_user(session, workos_user_id="db_sess_rev")
    await session.commit()
    store = DatabaseSessionStore(_settings(), session)
    cookie = await store.create_session(user_id=user.id)
    await session.commit()

    sid = store.parse_session_id(cookie)
    assert sid is not None
    await store.revoke_session(sid)
    await session.commit()

    assert await store.read_session(cookie) is None
