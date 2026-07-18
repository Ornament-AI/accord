"""Unit tests for identity service helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.adapters import AuthenticatedIdentity
from app.models.identity import User
from app.services.identity import establish_session_for_identity, upsert_user
from tests.identity_helpers import seed_membership, seed_organization, settings


@pytest.mark.asyncio
async def test_upsert_user_creates_then_updates(session):
    identity = AuthenticatedIdentity(
        subject_id="svc_upsert_1",
        email="a@example.com",
        name="Alpha",
    )
    user = await upsert_user(session, identity)
    await session.commit()
    assert user.email == "a@example.com"

    updated = await upsert_user(
        session,
        AuthenticatedIdentity(
            subject_id="svc_upsert_1",
            email="b@example.com",
            name="Beta",
        ),
    )
    await session.commit()
    assert updated.id == user.id
    rows = (await session.execute(select(User))).scalars().all()
    assert len(rows) == 1
    assert rows[0].email == "b@example.com"
    assert rows[0].name == "Beta"


@pytest.mark.asyncio
async def test_establish_session_auto_activates_sole_membership(session):
    user = await upsert_user(
        session,
        AuthenticatedIdentity(
            subject_id="svc_auto_1",
            email="auto@example.com",
            name="Auto",
        ),
    )
    org = await seed_organization(session, slug="svc-auto-org")
    await seed_membership(session, organization_id=org.id, user_id=user.id)
    await session.commit()

    cfg = settings(dev_auth_bypass=True)
    user2, cookie = await establish_session_for_identity(
        session,
        cfg,
        AuthenticatedIdentity(
            subject_id="svc_auto_1",
            email="auto@example.com",
            name="Auto",
        ),
    )
    assert user2.id == user.id
    assert cookie
    from app.auth.session import DatabaseSessionStore

    store = DatabaseSessionStore(cfg, session)
    row = await store.read_session(cookie)
    assert row is not None
    assert row.active_organization_id == org.id
