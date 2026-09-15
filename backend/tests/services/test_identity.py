"""Unit tests for identity service helpers (ADR 0011)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.adapters import AuthenticatedIdentity
from app.auth.session import DatabaseSessionStore
from app.models.identity import OrganizationInvitation, OrganizationMembership, User
from app.models.platform import AuditEvent
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

    # T1.13: the first-login user insert, invitation claim, and membership
    # creation each emit a mutation event in the login transaction.
    user_event = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.command == "user.create",
                AuditEvent.entity_id == user.id,
            )
        )
    ).scalar_one()
    assert user_event.entity_type == "user"
    assert user_event.organization_id == result.organization.id
    assert user_event.before_state == {}
    assert user_event.after_state["email"] == "invitee@example.com"

    invite_event = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.command == "invitation.accept",
                AuditEvent.entity_id == invite.id,
            )
        )
    ).scalar_one()
    assert invite_event.entity_type == "organization_invitation"
    assert invite_event.before_state["accepted_at"] is None
    assert invite_event.after_state["accepted_at"] is not None

    membership_event = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.command == "membership.create",
                AuditEvent.entity_id == membership.id,
            )
        )
    ).scalar_one()
    assert membership_event.entity_type == "organization_membership"
    assert membership_event.before_state == {}
    assert membership_event.after_state["role"] == "organization_administrator"


@pytest.mark.asyncio
async def test_routine_relogin_writes_no_audit_noise(session):
    """A second login with unchanged IdP claims must not mint audit rows."""
    await provision_organization(
        session,
        name="Quiet Org",
        slug="svc-quiet-org",
        admin_email="quiet@example.com",
    )
    await session.commit()

    cfg = settings(dev_auth_bypass=True)
    identity = AuthenticatedIdentity(
        subject_id="svc_quiet_1",
        email="quiet@example.com",
        name="Quiet",
    )
    await establish_session_for_identity(session, cfg, identity)
    baseline = (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.command.in_(("user.create", "user.update", "membership.create"))
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(baseline) == 2  # user.create + membership.create from first login

    await establish_session_for_identity(session, cfg, identity)
    after = (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.command.in_(("user.create", "user.update", "membership.create"))
                )
            )
        )
        .scalars()
        .all()
    )
    assert [event.id for event in after] == [event.id for event in baseline]


@pytest.mark.asyncio
async def test_upsert_user_real_change_writes_user_update(session):
    """An IdP email/name change is a real state change — audit it."""
    org = await seed_organization(session, slug="svc-audit-user-org")
    identity = AuthenticatedIdentity(subject_id="svc_audit_1", email="old@example.com", name="Old")
    user = await upsert_user(session, identity, organization_id=org.id)
    await session.commit()

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await upsert_user(
        session,
        AuthenticatedIdentity(subject_id="svc_audit_1", email="new@example.com", name="New"),
        organization_id=org.id,
    )
    await session.commit()

    events = (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == user.id,
                    AuditEvent.command.in_(("user.create", "user.update")),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2
    update_event = next(e for e in events if e.command == "user.update")
    assert update_event.before_state["email"] == "old@example.com"
    assert update_event.after_state["email"] == "new@example.com"
    assert update_event.summary["updated_fields"] == ["email", "name"]


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


@pytest.mark.asyncio
async def test_establish_session_claims_invitation_mixed_case_email(session):
    """CITEXT contract: an invite provisioned with mixed case is claimed by the
    canonically cased identity the IdP returns."""
    result = await provision_organization(
        session,
        name="Case Org",
        slug="svc-case-org",
        admin_email="Mixed.Case@Example.COM",
    )
    await session.commit()

    cfg = settings(dev_auth_bypass=True)
    user, cookie = await establish_session_for_identity(
        session,
        cfg,
        AuthenticatedIdentity(
            subject_id="svc_case_1",
            email="mixed.case@example.com",
            name="Mixed Case",
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
    assert membership.is_active is True
    assert membership.role == "organization_administrator"
    invite = (
        await session.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.email == "MIXED.CASE@example.com"
            )
        )
    ).scalar_one()
    assert invite.accepted_at is not None


@pytest.mark.asyncio
async def test_upsert_user_case_only_email_change_is_stable(session):
    """A case-only email variation from the IdP must not create a second user."""
    first = await upsert_user(
        session,
        AuthenticatedIdentity(subject_id="svc_case_2", email="Stable@Example.com", name="S"),
    )
    await session.commit()
    second = await upsert_user(
        session,
        AuthenticatedIdentity(subject_id="svc_case_2", email="stable@example.com", name="S"),
    )
    await session.commit()
    assert second.id == first.id
    rows = (await session.execute(select(User))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_claim_reactivates_inactive_membership(session):
    """A pending invite for a user with an inactive membership reactivates it
    in place (the (org, user) unique constraint forbids a second row)."""
    from app.services.members import claim_pending_invitation

    user = await upsert_user(
        session,
        AuthenticatedIdentity(subject_id="svc_react_1", email="react@example.com", name="R"),
    )
    org = await seed_organization(session, slug="svc-react-org")
    membership = await seed_membership(
        session,
        organization_id=org.id,
        user_id=user.id,
        role="auditor",
        is_active=False,
    )
    invite = OrganizationInvitation(
        organization_id=org.id,
        email="react@example.com",
        role="payroll_preparer",
    )
    session.add(invite)
    await session.commit()

    claimed = await claim_pending_invitation(session, user, org)
    await session.commit()
    assert claimed is not None
    assert claimed.id == membership.id
    assert claimed.is_active is True
    assert claimed.role == "payroll_preparer"
    refreshed_invite = (
        await session.execute(
            select(OrganizationInvitation).where(OrganizationInvitation.id == invite.id)
        )
    ).scalar_one()
    assert refreshed_invite.accepted_at is not None
