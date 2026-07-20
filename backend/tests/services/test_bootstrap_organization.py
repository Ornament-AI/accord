"""Tests for privileged singleton organization bootstrap (ADR 0011)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text

from app.exceptions import ConflictError
from app.models.identity import Organization, OrganizationInvitation, OrganizationMembership
from app.services.bootstrap import provision_organization
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_user


@pytest.mark.asyncio
async def test_provision_organization_creates_once(session):
    result = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    assert result.created is True
    orgs = (await session.execute(select(Organization))).scalars().all()
    assert len(orgs) == 1
    await bind_tenant_context(session, organization_id=orgs[0].id)
    invite = (await session.execute(select(OrganizationInvitation))).scalar_one()
    assert invite.email == "admin@example.com"
    assert invite.role == "organization_administrator"


@pytest.mark.asyncio
async def test_provision_organization_idempotent_identical_rerun(session):
    first = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    second = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    assert first.created is True
    assert second.created is False
    assert second.organization.id == first.organization.id
    orgs = (await session.execute(select(Organization))).scalars().all()
    assert len(orgs) == 1


@pytest.mark.asyncio
async def test_provision_organization_divergent_rerun_fails_without_escalation(session):
    await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    with pytest.raises(ConflictError, match="different name, slug, or admin"):
        await provision_organization(
            session,
            name="Other",
            slug="acme",
            admin_email="admin@example.com",
        )
    with pytest.raises(ConflictError, match="different name, slug, or admin"):
        await provision_organization(
            session,
            name="Acme",
            slug="acme",
            admin_email="other@example.com",
        )
    await bind_tenant_context(
        session,
        organization_id=(await session.execute(select(Organization))).scalar_one().id,
    )
    invites = (await session.execute(select(OrganizationInvitation))).scalars().all()
    assert len(invites) == 1
    assert invites[0].email == "admin@example.com"
    memberships = (await session.execute(select(OrganizationMembership))).scalars().all()
    assert memberships == []


@pytest.mark.asyncio
async def test_provision_organization_uses_existing_user_membership(session):
    user = await seed_user(session, email="admin@example.com")
    await session.commit()
    result = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="Admin@example.com",  # citext
    )
    assert result.created is True
    await bind_tenant_context(session, organization_id=result.organization.id)
    membership = (
        await session.execute(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        )
    ).scalar_one()
    assert membership.role == "organization_administrator"


@pytest.mark.asyncio
async def test_second_organization_insert_fails_singleton_index(session):
    await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    with pytest.raises(Exception):
        await session.execute(
            text(
                "INSERT INTO organizations (name, slug, is_active) VALUES ('Other', 'other', true)"
            )
        )
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_concurrent_provision_one_winner(clean_identity_tables):
    """Two parallel creates → one success, one ConflictError (DB authoritative)."""
    from app.db import get_session_factory

    factory = get_session_factory()

    async def attempt(label: str):
        async with factory() as session:
            return await provision_organization(
                session,
                name="Race Org",
                slug="race-org",
                admin_email=f"{label}@example.com",
            )

    results = await asyncio.gather(
        attempt("a"),
        attempt("b"),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ConflictError)


@pytest.mark.asyncio
async def test_provision_organization_idempotent_mixed_case_admin_email(session):
    """CITEXT contract: a differently cased admin email on rerun is the same
    intent and must be an idempotent no-op."""
    first = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="Admin@Example.COM",
    )
    second = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    assert first.created is True
    assert second.created is False
    orgs = (await session.execute(select(Organization))).scalars().all()
    assert len(orgs) == 1
    invites = (await session.execute(select(OrganizationInvitation))).scalars().all()
    assert len(invites) == 1


@pytest.mark.asyncio
async def test_provision_member_mixed_case_email_matches_existing_user(session):
    """CITEXT contract: provisioning with a differently cased email resolves
    the existing user into a membership instead of minting an invitation."""
    from app.services.members import provision_member

    result = await provision_organization(
        session,
        name="Acme",
        slug="acme",
        admin_email="admin@example.com",
    )
    await seed_user(session, email="worker@example.com")
    kind, _ = await provision_member(
        session,
        organization_id=result.organization.id,
        email="Worker@Example.COM",
        role="payroll_preparer",
    )
    assert kind == "membership"
    invites = (await session.execute(select(OrganizationInvitation))).scalars().all()
    assert [i.email for i in invites] == ["admin@example.com"]
