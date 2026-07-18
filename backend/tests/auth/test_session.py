"""Unit tests for signed-cookie session store and OAuth state."""

from __future__ import annotations

import pytest
from fastapi import Response

from app.auth.errors import WeakSessionSecretError
from app.auth.session import (
    SignedCookieSessionStore,
    session_payload_from_identity,
    sign_oauth_state,
    verify_oauth_state,
)
from app.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://accord@localhost/accord_test",
        environment="development",
        session_secret_key="test-session-secret-key",
        session_cookie_name="accord_session",
        accord_allow_weak_secrets=True,
        base_url="http://localhost:5173",
        public_app_url="",
    )
    base.update(overrides)
    return Settings.model_construct(**base)


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
