"""ORM smoke tests for Phase 3 header SQLModel tables."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import select

from app.models.identity import Organization
from app.models.org_structure import Office
from tests.migrations.conftest import diag, ensure_accord_roles, run_alembic


@pytest.mark.asyncio
async def test_office_orm_roundtrip(scratch_db: str) -> None:
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
            org = Organization(
                id=uuid.uuid4(),
                name="Org",
                slug=f"org-{uuid.uuid4().hex[:8]}",
            )
            session.add(org)
            await session.flush()

            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org.id)},
            )
            office = Office(
                organization_id=org.id,
                name="Main Office",
                code="MAIN",
                jurisdiction="mumbai",
            )
            session.add(office)
            await session.commit()
            office_id = office.id
            org_id = org.id

        async with session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )
            loaded = (
                await session.execute(select(Office).where(Office.id == office_id))
            ).scalar_one()
            assert loaded.code == "MAIN"
            assert loaded.jurisdiction == "mumbai"
            assert loaded.created_at is not None
            assert loaded.updated_at is not None
    finally:
        await engine.dispose()
