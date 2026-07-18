"""ORM roundtrip smoke tests for Phase 2 identity/tenancy models."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.identity import Organization, OrganizationMembership, User
from tests.migrations.conftest import diag, ensure_accord_roles, run_alembic


@pytest.mark.asyncio
async def test_identity_tenancy_orm_roundtrip(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            org = Organization(name="Acme Payroll", slug="acme-payroll")
            user = User(
                workos_user_id="workos_orm_user",
                email="orm@example.com",
                name="ORM User",
            )
            session.add(org)
            session.add(user)
            await session.flush()

            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org.id)},
            )

            membership = OrganizationMembership(
                organization_id=org.id,
                user_id=user.id,
                role="organization_administrator",
            )
            session.add(membership)
            await session.commit()

            org_id = org.id
            user_id = user.id
            membership_id = membership.id

        async with session_factory() as session:
            loaded_org = (
                await session.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one()
            loaded_user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()

            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )
            loaded_membership = (
                await session.execute(
                    select(OrganizationMembership).where(OrganizationMembership.id == membership_id)
                )
            ).scalar_one()

            assert isinstance(loaded_org.id, uuid.UUID)
            assert isinstance(loaded_user.id, uuid.UUID)
            assert isinstance(loaded_membership.id, uuid.UUID)
            assert loaded_org.is_active is True
            assert loaded_membership.is_active is True
            assert loaded_membership.role == "organization_administrator"
            assert loaded_org.created_at is not None
            assert loaded_org.updated_at is not None
            assert loaded_user.created_at is not None
            assert loaded_membership.created_at is not None
    finally:
        await engine.dispose()
