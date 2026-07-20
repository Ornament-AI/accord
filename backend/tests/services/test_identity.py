"""Unit tests for identity service helpers (ADR 0011)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.adapters import AuthenticatedIdentity
from app.auth.session import DatabaseSessionStore
from app.models.identity import OrganizationInvitation, OrganizationMembership, User
from app.services.bootstrap import provision_organization
from app.services.identity import build_me_payload, establish_session_for_identity, upsert_user
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_membership, seed_organization, seed_session_row, settings


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
async def test_establish_session_auto_binds_singleton_membership(session):
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
    store = DatabaseSessionStore(cfg, session)
    row = await store.read_session(cookie)
    assert row is not None
    assert row.active_organization_id == org.id


@pytest.mark.asyncio
async def test_establish_session_claims_pending_invitation(session):
    result = await provision_organization(
        session,
        name="Invite Org",
        slug="svc-invite-org",
        admin_email="invitee@example.com",
    )
    await session.commit()

    cfg = settings(dev_auth_bypass=True)
    user, cookie = await establish_session_for_identity(
        session,
        cfg,
        AuthenticatedIdentity(
            subject_id="svc_invite_1",
            email="invitee@example.com",
            name="Invitee",
        ),
    )
    assert cookie
    store = DatabaseSessionStore(cfg, session)
    row = await store.read_session(cookie)
    assert row is not None
    assert row.active_organization_id == result.organization.id

    await bind_tenant_context(session, organization_id=result.organization.id, user_id=user.id)
    membership = (
        await session.execute(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        )
    ).scalar_one()
    assert membership.role == "organization_administrator"
    invite = (
        await session.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.email == "invitee@example.com"
            )
        )
    ).scalar_one()
    assert invite.accepted_at is not None


@pytest.mark.asyncio
async def test_build_me_payload_access_states(session):
    cfg_user = await upsert_user(
        session,
        AuthenticatedIdentity(
            subject_id="svc_me_1",
            email="me@example.com",
            name="Me",
        ),
    )
    await session.commit()
    session_row = await seed_session_row(session, user_id=cfg_user.id)
    await session.commit()

    unboot = await build_me_payload(session, cfg_user, session_row)
    assert unboot["access_state"] == "unbootstrapped"
    assert unboot["organization"] is None
    assert unboot["membership"] is None

    org = await seed_organization(session, slug="svc-me-org")
    await session.commit()
    unprov = await build_me_payload(session, cfg_user, session_row)
    assert unprov["access_state"] == "unprovisioned"
    assert unprov["organization"]["id"] == str(org.id)
    assert unprov["membership"] is None

    await seed_membership(session, organization_id=org.id, user_id=cfg_user.id)
    await session.commit()
    session_row.active_organization_id = org.id
    await session.commit()

    active = await build_me_payload(session, cfg_user, session_row)
    assert active["access_state"] == "active"
    assert active["organization"]["slug"] == "svc-me-org"
    assert active["membership"]["role"] == "organization_administrator"
    assert "manage_organization" in active["membership"]["capabilities"]
