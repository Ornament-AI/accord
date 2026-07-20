"""Gate D fixtures: one-org HTTP world + scratch-DB RLS imports.

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
class OneOrgWorld:
    """Singleton-org fixture for Gate D HTTP authz / isolation tests."""

    org: Organization
    admin: User
    preparer: User
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
async def one_org_world(session: AsyncSession) -> OneOrgWorld:
    """One organization with admin, preparer, and a zero-membership outsider."""
    org = await seed_organization(session, name="Gate D Org", slug="gate-d-org")

    admin = await seed_user(
        session, workos_user_id="gate_d_admin", email="admin@gate-d.test", name="Admin"
    )
    preparer = await seed_user(
        session,
        workos_user_id="gate_d_preparer",
        email="preparer@gate-d.test",
        name="Preparer",
    )
    outsider = await seed_user(
        session,
        workos_user_id="gate_d_outsider",
        email="outsider@gate-d.test",
        name="Outsider",
    )

    await seed_membership(
        session,
        organization_id=org.id,
        user_id=admin.id,
        role="organization_administrator",
    )
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=preparer.id,
        role="payroll_preparer",
    )

    await session.commit()
    return OneOrgWorld(org=org, admin=admin, preparer=preparer, outsider=outsider)
