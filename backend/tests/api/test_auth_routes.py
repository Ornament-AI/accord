"""Integration tests for /api/auth/* routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.adapters import AuthenticatedIdentity, DevAuthAdapter
from app.auth.errors import AuthMisconfiguredError
from app.auth.session import sign_oauth_state
from app.config import Settings, get_settings


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://accord@localhost/accord_test",
        migrations_database_url="postgresql+asyncpg://accord@localhost/accord_test",
        environment="development",
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="http://localhost:8000/api/auth/callback",
        workos_webhook_secret="",
        session_secret_key="test-session-secret-key",
        session_cookie_name="accord_session",
        dev_auth_bypass=True,
        dev_auth_email="dev@accord.local",
        dev_auth_name="Dev Test User",
        accord_allow_weak_secrets=True,
        base_url="http://localhost:5173",
        public_app_url="http://localhost:5173",
    )
    base.update(overrides)
    return Settings.model_construct(**base)


@pytest.fixture
def dev_settings(monkeypatch):
    settings = _settings(dev_auth_bypass=True)
    monkeypatch.setattr("app.api.routes.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.auth.session.get_settings", lambda: settings)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    yield settings
    get_settings.cache_clear()


@pytest.fixture
def production_missing_workos(monkeypatch):
    settings = _settings(
        environment="production",
        dev_auth_bypass=False,
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="",
        session_secret_key="test-session-secret-key-prod",
    )
    monkeypatch.setattr("app.api.routes.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.auth.session.get_settings", lambda: settings)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    yield settings
    get_settings.cache_clear()


def _session_cookie_from_response(response) -> str | None:
    # httpx exposes Set-Cookie via response.cookies
    if "accord_session" in response.cookies:
        return response.cookies["accord_session"]
    set_cookie = response.headers.get("set-cookie", "")
    if "accord_session=" not in set_cookie:
        return None
    part = set_cookie.split("accord_session=", 1)[1]
    return part.split(";", 1)[0]


@pytest.mark.asyncio
async def test_login_establishes_dev_session_and_me_happy_path(client, dev_settings):
    login_resp = await client.get("/api/auth/login", follow_redirects=False)
    assert login_resp.status_code == 302
    assert login_resp.headers["location"] == "http://localhost:5173"

    cookie = _session_cookie_from_response(login_resp)
    assert cookie
    client.cookies.set("accord_session", cookie)

    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["id"] == DevAuthAdapter.DEV_SUBJECT_ID
    assert body["email"] == "dev@accord.local"
    assert body["name"] == "Dev Test User"


@pytest.mark.asyncio
async def test_me_without_cookie_returns_401_problem(client, dev_settings):
    client.cookies.clear()
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["status"] == 401
    assert body["detail"] == "Not authenticated"
    assert body["type"] == "about:blank"


@pytest.mark.asyncio
async def test_me_with_tampered_cookie_returns_401_not_500(client, dev_settings):
    client.cookies.set("accord_session", "totally-not-a-valid-signature")
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_logout_clears_cookie_and_me_becomes_401(client, dev_settings):
    login_resp = await client.get("/api/auth/login", follow_redirects=False)
    cookie = _session_cookie_from_response(login_resp)
    assert cookie
    client.cookies.set("accord_session", cookie)

    assert (await client.get("/api/auth/me")).status_code == 200

    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 204

    # Drop jar cookie and ensure cleared Set-Cookie does not keep us authed.
    client.cookies.clear()
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 401


@pytest.mark.asyncio
async def test_callback_happy_path_with_dev_adapter(client, dev_settings):
    state = sign_oauth_state(dev_settings)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "dev-login", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173"
    cookie = _session_cookie_from_response(resp)
    assert cookie
    client.cookies.set("accord_session", cookie)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dev@accord.local"


@pytest.mark.asyncio
async def test_callback_happy_path_with_mocked_workos_exchange(client, monkeypatch):
    settings = _settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    monkeypatch.setattr("app.api.routes.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.auth.session.get_settings", lambda: settings)

    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="user_workos_1",
            email="worker@example.com",
            name="Worker One",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    state = sign_oauth_state(settings)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    cookie = _session_cookie_from_response(resp)
    assert cookie
    client.cookies.set("accord_session", cookie)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "id": "user_workos_1",
        "email": "worker@example.com",
        "name": "Worker One",
    }
    mock_adapter.exchange_code.assert_awaited_once_with(code="auth-code")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_callback_rejects_tampered_state(client, dev_settings):
    state = sign_oauth_state(dev_settings)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "dev-login", "state": state + "tampered"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["status"] == 401
    assert body["error"] == "InvalidOAuthState"


@pytest.mark.asyncio
async def test_callback_rejects_missing_state(client, dev_settings):
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "dev-login"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "InvalidOAuthState"


@pytest.mark.asyncio
async def test_login_and_me_return_503_when_production_workos_missing(
    client, production_missing_workos
):
    login_resp = await client.get("/api/auth/login", follow_redirects=False)
    assert login_resp.status_code == 503
    login_body = login_resp.json()
    assert login_body["status"] == 503
    assert login_body["error"] == "AuthMisconfigured"
    assert "WorkOS" in login_body["detail"]

    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 503
    me_body = me_resp.json()
    assert me_body["status"] == 503
    assert me_body["error"] == "AuthMisconfigured"


def test_get_auth_adapter_production_fail_closed_unit():
    """Companion unit assertion used by route fail-closed coverage."""
    settings = _settings(
        environment="production",
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="",
        dev_auth_bypass=True,
    )
    from app.auth.adapters import get_auth_adapter

    with pytest.raises(AuthMisconfiguredError):
        get_auth_adapter(settings)
