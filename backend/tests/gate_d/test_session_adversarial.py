"""Session/cookie adversarial cases beyond simple tampering covered in api tests."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text

from app.auth.session import DatabaseSessionStore
from app.models.base import utcnow
from app.models.identity import Session as SessionRow
from app.models.identity import User
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import seed_session_row, seed_user


@pytest.mark.asyncio
async def test_revoked_session_cookie_returns_401_not_500(client, dev_settings, session):
    user = await seed_user(session, workos_user_id="gate_d_revoke_user")
    cookie = await mint_session_cookie(session, dev_settings, user_id=user.id)
    apply_session_cookie(client, cookie)
    assert (await client.get("/api/auth/me")).status_code == 200

    store = DatabaseSessionStore(dev_settings, session)
    sid = store.parse_session_id(cookie)
    assert sid is not None
    row = await session.get(SessionRow, sid)
    assert row is not None
    row.revoked_at = utcnow()
    await session.commit()

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_expired_session_cookie_returns_401(client, dev_settings, session):
    user = await seed_user(session, workos_user_id="gate_d_expire_user")
    row = await seed_session_row(
        session,
        user_id=user.id,
        expires_at=utcnow() - timedelta(seconds=1),
    )
    await session.commit()
    cookie = DatabaseSessionStore(dev_settings, session)._sign(row.id)
    apply_session_cookie(client, cookie)

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_cookie_signed_with_wrong_secret_returns_401(client, dev_settings, session):
    user = await seed_user(session, workos_user_id="gate_d_wrong_secret_user")
    row = await seed_session_row(session, user_id=user.id)
    await session.commit()

    wrong = URLSafeTimedSerializer(
        secret_key="definitely-not-the-real-session-secret",
        salt="accord-session-v1",
    )
    cookie = wrong.dumps(str(row.id))
    apply_session_cookie(client, cookie)

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_signed_cookie_for_missing_session_returns_401(client, dev_settings, session):
    missing_id = uuid4()
    cookie = DatabaseSessionStore(dev_settings, session)._sign(missing_id)
    apply_session_cookie(client, cookie)

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_garbage_unsigned_cookie_returns_401(client, dev_settings):
    apply_session_cookie(client, "not-a-signed-cookie-value-at-all")
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_orphaned_session_user_deleted_returns_401_not_500(client, dev_settings, session):
    """FK sessions.user_id → users.id is NO ACTION; orphan via replication_role."""
    user = await seed_user(session, workos_user_id="gate_d_orphan_user")
    user_id = user.id
    cookie = await mint_session_cookie(session, dev_settings, user_id=user_id)
    apply_session_cookie(client, cookie)
    assert (await client.get("/api/auth/me")).status_code == 200

    store = DatabaseSessionStore(dev_settings, session)
    sid = store.parse_session_id(cookie)
    assert sid is not None

    # Direct DELETE is blocked by FK; disable trigger enforcement briefly.
    try:
        await session.execute(text("SET session_replication_role = replica"))
        await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    finally:
        await session.execute(text("SET session_replication_role = DEFAULT"))
    await session.commit()

    session.expire_all()
    orphan = await session.get(SessionRow, sid)
    assert orphan is not None
    assert await session.get(User, user_id) is None

    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"
