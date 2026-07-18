"""Real-connection tests for transaction-local tenant GUCs (ADR-0001)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.tenancy import bind_tenant_context, tenant_context


async def _current_setting(session: AsyncSession, name: str) -> str | None:
    result = await session.execute(
        text("SELECT current_setting(:name, true)"),
        {"name": name},
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_set_config_local_visible_within_transaction(session: AsyncSession) -> None:
    org_id = str(uuid.uuid4())

    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id)
        assert await _current_setting(session, "app.organization_id") == org_id


@pytest.mark.asyncio
async def test_set_config_local_clears_after_transaction_ends(
    session: AsyncSession,
) -> None:
    org_id = str(uuid.uuid4())

    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id)
        assert await _current_setting(session, "app.organization_id") == org_id

    # New transaction on the same session — SET LOCAL must not leak.
    async with session.begin():
        leaked = await _current_setting(session, "app.organization_id")
        assert leaked is None or leaked == ""


@pytest.mark.asyncio
async def test_set_config_local_clears_on_rollback(session: AsyncSession) -> None:
    org_id = str(uuid.uuid4())

    await session.begin()
    try:
        await bind_tenant_context(session, organization_id=org_id)
        assert await _current_setting(session, "app.organization_id") == org_id
        await session.rollback()
    except Exception:
        await session.rollback()
        raise

    async with session.begin():
        leaked = await _current_setting(session, "app.organization_id")
        assert leaked is None or leaked == ""


@pytest.mark.asyncio
async def test_tenant_context_sets_organization_user_and_request_id(
    session: AsyncSession,
) -> None:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    request_id = "a1b2c3d4e5f6789012345678abcdef01"

    async with session.begin():
        async with tenant_context(
            session,
            organization_id=org_id,
            user_id=user_id,
            request_id=request_id,
        ) as bound:
            assert await _current_setting(bound, "app.organization_id") == str(org_id)
            assert await _current_setting(bound, "app.user_id") == str(user_id)
            assert await _current_setting(bound, "app.request_id") == request_id

    # Fresh session checkout must also see a clean GUC (pool safety).
    factory = get_session_factory()
    async with factory() as other:
        async with other.begin():
            leaked = await _current_setting(other, "app.organization_id")
            assert leaked is None or leaked == ""
