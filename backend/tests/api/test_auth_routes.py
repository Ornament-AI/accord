"""Integration tests for /api/auth/* routes (Phase-2 DB sessions)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.adapters import AuthenticatedIdentity, DevAuthAdapter
from app.auth.errors import AuthMisconfiguredError
from app.auth.session import DatabaseSessionStore, sign_oauth_state
from app.models.base import utcnow
from app.models.identity import Session as SessionRow
from app.models.identity import User
from tests.identity_helpers import (
    DEV_SUBJECT,
    clear_settings_cache,
    login_dev,
    patch_get_settings,
    seed_membership,
    seed_organization,
    session_cookie_from_response,
    settings,
    user_by_workos_id,
)


@pytest.mark.asyncio
async def test_login_establishes_dev_session_and_me_happy_path(client, dev_settings, session):
    login_resp, cookie = await login_dev(client)
    assert login_resp.status_code == 302
    assert login_resp.headers["location"] == "http://localhost:5173"
    assert cookie

    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    # Local users.id UUID — not the WorkOS / Dev subject string.
    UUID(body["id"])
    assert body["id"] != DevAuthAdapter.DEV_SUBJECT_ID
    assert body["email"] == "dev@accord.local"
    assert body["name"] == "Dev Test User"
    assert body["is_platform_admin"] is False
    assert body["active_organization"] is None
    assert body["organizations"] == []

    user = await user_by_workos_id(session, DEV_SUBJECT)
    assert user is not None
    assert user.workos_user_id == DEV_SUBJECT
    assert str(user.id) == body["id"]


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
async def test_logout_clears_cookie_revokes_session_and_me_401(client, dev_settings, session):
    _, cookie = await login_dev(client)
    assert cookie
    assert (await client.get("/api/auth/me")).status_code == 200

    store = DatabaseSessionStore(dev_settings, session)
    session_id = store.parse_session_id(cookie)
    assert session_id is not None

    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 204
    set_cookie = logout_resp.headers.get("set-cookie", "")
    assert "accord_session=" in set_cookie

    session.expire_all()
    row = await session.get(SessionRow, session_id)
    assert row is not None
    assert row.revoked_at is not None

    # Old cookie must not authenticate after revoke.
    client.cookies.clear()
    client.cookies.set("accord_session", cookie)
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
    cookie = session_cookie_from_response(resp)
    assert cookie
    client.cookies.set("accord_session", cookie)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    UUID(body["id"])
    assert body["email"] == "dev@accord.local"


@pytest.mark.asyncio
async def test_callback_happy_path_with_mocked_workos_exchange(client, monkeypatch, session):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)

    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="user_workos_1",
            email="worker@example.com",
            name="Worker One",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    state = sign_oauth_state(value)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    cookie = session_cookie_from_response(resp)
    assert cookie
    client.cookies.set("accord_session", cookie)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    UUID(body["id"])
    assert body["email"] == "worker@example.com"
    assert body["name"] == "Worker One"
    assert body["is_platform_admin"] is False
    assert body["organizations"] == []
    mock_adapter.exchange_code.assert_awaited_once_with(code="auth-code")

    user = await user_by_workos_id(session, "user_workos_1")
    assert user is not None
    assert str(user.id) == body["id"]
    clear_settings_cache()


@pytest.mark.asyncio
async def test_callback_invalid_state_redirects_with_error(client, dev_settings):
    state = sign_oauth_state(dev_settings)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "dev-login", "state": state + "tampered"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=invalid_state"


@pytest.mark.asyncio
async def test_callback_missing_state_redirects_with_error(client, dev_settings):
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "dev-login"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=invalid_state"


@pytest.mark.asyncio
async def test_callback_missing_code_redirects_auth_failed(client, dev_settings):
    state = sign_oauth_state(dev_settings)
    resp = await client.get(
        "/api/auth/callback",
        params={"state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/login?error=auth_failed"


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
    value = settings(
        environment="production",
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="",
        dev_auth_bypass=True,
    )
    from app.auth.adapters import get_auth_adapter

    with pytest.raises(AuthMisconfiguredError):
        get_auth_adapter(value)


# --- /me membership shapes -------------------------------------------------


@pytest.mark.asyncio
async def test_me_zero_memberships(client, dev_settings):
    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    assert body["organizations"] == []
    assert body["active_organization"] is None


@pytest.mark.asyncio
async def test_me_one_membership_auto_activates_on_login(client, dev_settings, session):
    user = User(
        workos_user_id=DEV_SUBJECT,
        email="dev@accord.local",
        name="Dev Test User",
    )
    session.add(user)
    await session.flush()
    org = await seed_organization(session, name="Solo Org", slug="solo-org")
    await seed_membership(session, organization_id=org.id, user_id=user.id)
    await session.commit()

    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["slug"] == "solo-org"
    assert body["active_organization"] is not None
    assert body["active_organization"]["id"] == str(org.id)
    assert body["active_organization"]["role"] == "organization_administrator"
    assert "manage_organization" in body["active_organization"]["capabilities"]


@pytest.mark.asyncio
async def test_me_two_memberships_lists_both_active_null_until_switch(
    client, dev_settings, session
):
    user = User(
        workos_user_id=DEV_SUBJECT,
        email="dev@accord.local",
        name="Dev Test User",
    )
    session.add(user)
    await session.flush()
    org_a = await seed_organization(session, name="Alpha", slug="alpha-co")
    org_b = await seed_organization(session, name="Beta", slug="beta-co")
    await seed_membership(session, organization_id=org_a.id, user_id=user.id)
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=user.id,
        role="payroll_preparer",
    )
    await session.commit()

    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    slugs = {o["slug"] for o in body["organizations"]}
    assert slugs == {"alpha-co", "beta-co"}
    assert body["active_organization"] is None

    switch = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(org_b.id)},
    )
    assert switch.status_code == 200
    switched = switch.json()
    assert switched["active_organization"]["id"] == str(org_b.id)
    assert switched["active_organization"]["role"] == "payroll_preparer"
    # Cookie rotated — jar updated from Set-Cookie.
    new_cookie = session_cookie_from_response(switch)
    if new_cookie:
        client.cookies.set("accord_session", new_cookie)
    me = (await client.get("/api/auth/me")).json()
    assert me["active_organization"]["id"] == str(org_b.id)


# --- return_to validation --------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "//evil.com",
        "https://evil.com",
        "http://evil.com",
        "/\\evil.com",
        "\\\\evil.com",
        "not-a-path",
    ],
)
def test_validate_return_to_rejects_unsafe(value):
    from app.api.routes.auth import validate_return_to

    assert validate_return_to(value) is None


def test_validate_return_to_accepts_relative_path():
    from app.api.routes.auth import validate_return_to

    assert validate_return_to("/pay-runs") == "/pay-runs"
    assert validate_return_to("/settings/org") == "/settings/org"
    assert validate_return_to(None) is None
    assert validate_return_to("") is None


@pytest.mark.asyncio
async def test_return_to_round_trip_via_callback_state(client, monkeypatch):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)
    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="user_rt_1",
            email="rt@example.com",
            name="Return To",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    state = sign_oauth_state(value, redirect_to="/pay-runs")
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/pay-runs"
    clear_settings_cache()


@pytest.mark.asyncio
async def test_callback_drops_evil_return_to_in_state(client, monkeypatch):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)
    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="user_evil_rt",
            email="evil@example.com",
            name="Evil",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    # Bypass sign_oauth_state validation by embedding evil r in signed payload.
    from itsdangerous import URLSafeTimedSerializer

    serializer = URLSafeTimedSerializer(
        secret_key=value.session_secret_key,
        salt="accord-oauth-state-v1",
    )
    state = serializer.dumps({"n": "nonce", "r": "https://evil.com"})
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.com" not in resp.headers["location"]
    assert resp.headers["location"] == "http://localhost:5173"
    clear_settings_cache()


@pytest.mark.asyncio
async def test_login_dev_return_to_valid_redirects(client, dev_settings):
    resp = await client.get(
        "/api/auth/login",
        params={"return_to": "/pay-runs"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173/pay-runs"


@pytest.mark.asyncio
async def test_login_dev_return_to_invalid_dropped(client, dev_settings):
    resp = await client.get(
        "/api/auth/login",
        params={"return_to": "https://evil.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:5173"


# --- callback upsert / auto-activate --------------------------------------


@pytest.mark.asyncio
async def test_callback_upsert_creates_user_and_updates_existing(client, monkeypatch, session):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)

    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="upsert_user_1",
            email="first@example.com",
            name="First Name",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    state = sign_oauth_state(value)
    await client.get(
        "/api/auth/callback",
        params={"code": "c1", "state": state},
        follow_redirects=False,
    )
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1
    assert users[0].email == "first@example.com"

    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="upsert_user_1",
            email="updated@example.com",
            name="Updated Name",
        )
    )
    state2 = sign_oauth_state(value)
    await client.get(
        "/api/auth/callback",
        params={"code": "c2", "state": state2},
        follow_redirects=False,
    )
    session.expire_all()
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1
    assert users[0].email == "updated@example.com"
    assert users[0].name == "Updated Name"
    clear_settings_cache()


@pytest.mark.asyncio
async def test_callback_sole_membership_auto_activates(client, monkeypatch, session):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)

    user = User(
        workos_user_id="auto_act_1",
        email="auto@example.com",
        name="Auto",
    )
    session.add(user)
    await session.flush()
    org = await seed_organization(session, slug="auto-org")
    await seed_membership(session, organization_id=org.id, user_id=user.id)
    await session.commit()

    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="auto_act_1",
            email="auto@example.com",
            name="Auto",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    state = sign_oauth_state(value)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    cookie = session_cookie_from_response(resp)
    client.cookies.set("accord_session", cookie)
    body = (await client.get("/api/auth/me")).json()
    assert body["active_organization"]["id"] == str(org.id)
    clear_settings_cache()


@pytest.mark.asyncio
async def test_callback_multiple_memberships_active_null(client, monkeypatch, session):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)

    user = User(
        workos_user_id="multi_act_1",
        email="multi@example.com",
        name="Multi",
    )
    session.add(user)
    await session.flush()
    org_a = await seed_organization(session, slug="multi-a")
    org_b = await seed_organization(session, slug="multi-b")
    await seed_membership(session, organization_id=org_a.id, user_id=user.id)
    await seed_membership(session, organization_id=org_b.id, user_id=user.id)
    await session.commit()

    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="multi_act_1",
            email="multi@example.com",
            name="Multi",
        )
    )
    monkeypatch.setattr("app.api.routes.auth.get_auth_adapter", lambda _s: mock_adapter)

    state = sign_oauth_state(value)
    resp = await client.get(
        "/api/auth/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    cookie = session_cookie_from_response(resp)
    client.cookies.set("accord_session", cookie)
    body = (await client.get("/api/auth/me")).json()
    assert body["active_organization"] is None
    assert len(body["organizations"]) == 2
    clear_settings_cache()


# --- switch-organization ---------------------------------------------------


@pytest.mark.asyncio
async def test_switch_organization_happy_rotates_session(client, dev_settings, session):
    user = User(
        workos_user_id=DEV_SUBJECT,
        email="dev@accord.local",
        name="Dev Test User",
    )
    session.add(user)
    await session.flush()
    org_a = await seed_organization(session, slug="switch-a")
    org_b = await seed_organization(session, slug="switch-b")
    await seed_membership(session, organization_id=org_a.id, user_id=user.id)
    await seed_membership(session, organization_id=org_b.id, user_id=user.id)
    await session.commit()

    _, old_cookie = await login_dev(client)
    assert old_cookie
    store = DatabaseSessionStore(dev_settings, session)
    old_sid = store.parse_session_id(old_cookie)

    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(org_a.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_organization"]["id"] == str(org_a.id)
    new_cookie = session_cookie_from_response(resp)
    assert new_cookie
    assert new_cookie != old_cookie

    session.expire_all()
    old_row = await session.get(SessionRow, old_sid)
    assert old_row is not None
    assert old_row.revoked_at is not None


@pytest.mark.asyncio
async def test_switch_organization_403_no_membership(client, dev_settings, session):
    await login_dev(client)
    foreign = await seed_organization(session, slug="foreign-org")
    await session.commit()

    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(foreign.id)},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "MembershipForbidden"


@pytest.mark.asyncio
async def test_switch_organization_403_inactive_membership(client, dev_settings, session):
    user = User(
        workos_user_id=DEV_SUBJECT,
        email="dev@accord.local",
        name="Dev Test User",
    )
    session.add(user)
    await session.flush()
    org = await seed_organization(session, slug="inactive-mem")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=user.id,
        is_active=False,
    )
    await session.commit()

    await login_dev(client)
    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(org.id)},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "MembershipForbidden"


@pytest.mark.asyncio
async def test_switch_organization_403_inactive_org(client, dev_settings, session):
    user = User(
        workos_user_id=DEV_SUBJECT,
        email="dev@accord.local",
        name="Dev Test User",
    )
    session.add(user)
    await session.flush()
    org = await seed_organization(session, slug="inactive-org", is_active=False)
    await seed_membership(session, organization_id=org.id, user_id=user.id)
    await session.commit()

    await login_dev(client)
    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(org.id)},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "MembershipForbidden"


# --- session expiry / idle / revoked --------------------------------------


@pytest.mark.asyncio
async def test_me_401_when_session_expired(client, dev_settings, session):
    _, cookie = await login_dev(client)
    store = DatabaseSessionStore(dev_settings, session)
    sid = store.parse_session_id(cookie)
    row = await session.get(SessionRow, sid)
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_401_when_session_idle_stale(client, dev_settings, session):
    _, cookie = await login_dev(client)
    store = DatabaseSessionStore(dev_settings, session)
    sid = store.parse_session_id(cookie)
    row = await session.get(SessionRow, sid)
    assert row is not None
    row.last_seen_at = utcnow() - timedelta(seconds=dev_settings.session_idle_timeout_seconds + 10)
    await session.commit()

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_401_when_session_revoked(client, dev_settings, session):
    _, cookie = await login_dev(client)
    store = DatabaseSessionStore(dev_settings, session)
    sid = store.parse_session_id(cookie)
    row = await session.get(SessionRow, sid)
    assert row is not None
    row.revoked_at = utcnow()
    await session.commit()

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
