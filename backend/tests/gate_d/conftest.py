"""Gate D fixtures: two-org HTTP world + scratch-DB RLS imports.

HTTP tests use the shared accord_test DB (client/session) with ORM seed helpers
and signed cookies. SQL isolation tests reuse migrations scratch_db fixtures
via direct import (same pattern as tests/rls/conftest.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import DatabaseSessionStore
from app.models.identity import Organization, User
from tests.identity_helpers import (  # noqa: F401
    clear_settings_cache,
    patch_get_settings,
    seed_membership,
    seed_organization,
    seed_user,
    settings,
)
from tests.migrations.conftest import (  # noqa: F401
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
    scratch_db,
)


@pytest_asyncio.fixture(autouse=True)
async def _autouse_clean_identity_tables(clean_identity_tables):
    """Keep identity tables empty between Gate D HTTP/shared-DB tests."""
    yield


@pytest.fixture
def dev_settings(monkeypatch):
    value = settings(dev_auth_bypass=True)
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()


@dataclass(frozen=True)
class TwoOrgWorld:
    """Overlapping two-org fixture for HTTP adversarial isolation tests."""

    org_a: Organization
    org_b: Organization
    admin_a: User
    preparer_a: User
    admin_b: User
    user_ab: User
    outsider: User


async def mint_session_cookie(
    db: AsyncSession,
    settings_obj,
    *,
    user_id: UUID,
    active_organization_id: UUID | None = None,
) -> str:
    """Create a DB session row and return a correctly signed accord_session cookie."""
    store = DatabaseSessionStore(settings_obj, db)
    cookie = await store.create_session(
        user_id=user_id,
        active_organization_id=active_organization_id,
    )
    await db.commit()
    return cookie


def apply_session_cookie(client: AsyncClient, cookie: str) -> None:
    client.cookies.clear()
    client.cookies.set("accord_session", cookie)


@pytest_asyncio.fixture
async def two_org_world(session: AsyncSession) -> TwoOrgWorld:
    """Org A/B with overlapping roles, dual-membership user, and an outsider."""
    org_a = await seed_organization(session, name="Gate D Org A", slug="gate-d-org-a")
    org_b = await seed_organization(session, name="Gate D Org B", slug="gate-d-org-b")

    admin_a = await seed_user(
        session, workos_user_id="gate_d_admin_a", email="admin-a@gate-d.test", name="Admin A"
    )
    preparer_a = await seed_user(
        session,
        workos_user_id="gate_d_preparer_a",
        email="preparer-a@gate-d.test",
        name="Preparer A",
    )
    admin_b = await seed_user(
        session, workos_user_id="gate_d_admin_b", email="admin-b@gate-d.test", name="Admin B"
    )
    user_ab = await seed_user(
        session, workos_user_id="gate_d_user_ab", email="user-ab@gate-d.test", name="User AB"
    )
    outsider = await seed_user(
        session,
        workos_user_id="gate_d_outsider",
        email="outsider@gate-d.test",
        name="Outsider",
    )

    # Same role string in both orgs (overlapping business data at membership level).
    await seed_membership(
        session,
        organization_id=org_a.id,
        user_id=admin_a.id,
        role="organization_administrator",
    )
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=admin_b.id,
        role="organization_administrator",
    )
    await seed_membership(
        session,
        organization_id=org_a.id,
        user_id=preparer_a.id,
        role="payroll_preparer",
    )
    # Dual membership with observable capability differences across orgs.
    await seed_membership(
        session,
        organization_id=org_a.id,
        user_id=user_ab.id,
        role="organization_administrator",
    )
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=user_ab.id,
        role="payroll_reviewer",
    )

    await session.commit()
    return TwoOrgWorld(
        org_a=org_a,
        org_b=org_b,
        admin_a=admin_a,
        preparer_a=preparer_a,
        admin_b=admin_b,
        user_ab=user_ab,
        outsider=outsider,
    )
