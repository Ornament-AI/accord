"""Integration tests for /api/auth/* routes (ADR 0011 singular /me)."""

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
from app.models.identity import OrganizationInvitation, Session as SessionRow
from app.models.identity import User
from app.services.bootstrap import provision_organization
from app.tenancy import bind_tenant_context
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
    assert body["access_state"] == "unbootstrapped"
    assert body["organization"] is None
    assert body["membership"] is None
    assert "organizations" not in body
    assert "active_organization" not in body

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
    assert body["access_state"] == "unbootstrapped"


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
    assert body["access_state"] == "unbootstrapped"
    assert body["organization"] is None
    assert body["membership"] is None
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


# --- /me access_state shapes (ADR 0011) --------------------------------------


@pytest.mark.asyncio
async def test_me_unbootstrapped_when_no_organization(client, dev_settings):
    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    assert body["access_state"] == "unbootstrapped"
    assert body["organization"] is None
    assert body["membership"] is None


@pytest.mark.asyncio
async def test_me_unprovisioned_when_org_exists_without_membership(
    client, dev_settings, session
):
    await seed_organization(session, name="Solo Org", slug="solo-org")
    await session.commit()

    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    assert body["access_state"] == "unprovisioned"
    assert body["organization"] is not None
    assert body["organization"]["slug"] == "solo-org"
    assert body["membership"] is None


@pytest.mark.asyncio
async def test_me_active_when_membership_exists(client, dev_settings, session):
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
    assert body["access_state"] == "active"
    assert body["organization"]["id"] == str(org.id)
    assert body["organization"]["slug"] == "solo-org"
    assert body["membership"] is not None
    assert body["membership"]["role"] == "organization_administrator"
    assert "manage_organization" in body["membership"]["capabilities"]


@pytest.mark.asyncio
async def test_login_claims_pending_invitation(client, dev_settings, session):
    """Pending invite matching login email is claimed atomically → access_state active."""
    result = await provision_organization(
        session,
        name="Invite Org",
        slug="invite-org",
        admin_email="dev@accord.local",
    )
    await session.commit()

    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    assert body["access_state"] == "active"
    assert body["organization"]["id"] == str(result.organization.id)
    assert body["membership"]["role"] == "organization_administrator"

    await bind_tenant_context(session, organization_id=result.organization.id)
    invite = (
        await session.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == result.organization.id,
                OrganizationInvitation.email == "dev@accord.local",
            )
        )
    ).scalar_one()
    assert invite.accepted_at is not None


@pytest.mark.asyncio
async def test_switch_organization_route_removed(client, dev_settings):
    await login_dev(client)
    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert resp.status_code in {404, 405}


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


# --- callback upsert / invite claim --------------------------------------


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
async def test_callback_claims_invite_and_activates(client, monkeypatch, session):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)

    result = await provision_organization(
        session,
        name="Auto Org",
        slug="auto-org",
        admin_email="auto@example.com",
    )
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
    assert body["access_state"] == "active"
    assert body["organization"]["id"] == str(result.organization.id)
    assert body["membership"]["role"] == "organization_administrator"
    clear_settings_cache()


@pytest.mark.asyncio
async def test_callback_unprovisioned_when_org_exists_without_invite(
    client, monkeypatch, session
):
    value = settings(
        dev_auth_bypass=False,
        workos_client_id="client_test",
        workos_api_key="key_test",
        workos_redirect_uri="http://test/api/auth/callback",
    )
    patch_get_settings(monkeypatch, value)

    org = await seed_organization(session, slug="unprov-org")
    await session.commit()

    mock_adapter = MagicMock()
    mock_adapter.exchange_code = AsyncMock(
        return_value=AuthenticatedIdentity(
            subject_id="unprov_1",
            email="outsider@example.com",
            name="Outsider",
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
    assert body["access_state"] == "unprovisioned"
    assert body["organization"]["id"] == str(org.id)
    assert body["membership"] is None
    clear_settings_cache()


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
