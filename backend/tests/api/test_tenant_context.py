"""require_tenant_context binds app.organization_id in the same transaction."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.api.deps import require_tenant_context
from app.auth.errors import OrganizationContextRequiredError
from app.auth.principal import AuthPrincipal
from tests.identity_helpers import seed_membership, seed_organization, seed_user


@pytest.mark.asyncio
async def test_require_tenant_context_binds_organization_guc(session):
    user = await seed_user(session, workos_user_id="tenant_ctx_user")
    org = await seed_organization(session, slug="tenant-ctx-org")
    await seed_membership(session, organization_id=org.id, user_id=user.id)
    await session.commit()

    principal = AuthPrincipal(
        user_id=str(user.id),
        subject_id=user.workos_user_id,
        email=user.email,
        role="organization_administrator",
        is_active=True,
        organization_id=str(org.id),
        capabilities=frozenset({"manage_organization"}),
        session_id=str(uuid4()),
    )
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-tenant-1"))

    ctx = await require_tenant_context(request, principal, session)
    assert ctx.organization_id == str(org.id)
    assert ctx.user_id == str(user.id)

    result = await session.execute(text("SELECT current_setting('app.organization_id', true)"))
    assert result.scalar_one() == str(org.id)

    user_guc = await session.execute(text("SELECT current_setting('app.user_id', true)"))
    assert user_guc.scalar_one() == str(user.id)


@pytest.mark.asyncio
async def test_require_tenant_context_409_without_org(session):
    principal = AuthPrincipal(
        user_id=str(uuid4()),
        subject_id="x",
        email="x@example.com",
        role=None,
        is_active=True,
        organization_id=None,
        capabilities=frozenset(),
        session_id=str(uuid4()),
    )
    request = SimpleNamespace(state=SimpleNamespace(request_id=None))
    with pytest.raises(OrganizationContextRequiredError):
        await require_tenant_context(request, principal, session)
