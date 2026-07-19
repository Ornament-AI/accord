"""Behavioral RLS tests for Phase 2 tenant-owned tables.

SET ROLE accord_app on a superuser connection is the intended approach here:
FORCE RLS still applies, so policies are exercised without needing role passwords.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
)

TENANT_TABLES = (
    "organization_memberships",
    "idempotency_keys",
)


@dataclass(frozen=True)
class SeededTenants:
    org_a_id: uuid.UUID
    org_b_id: uuid.UUID
    user_a_id: uuid.UUID
    user_b_id: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_tenants(database_url: str) -> SeededTenants:
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s), (%s, %s, %s)",
            (org_a_id, "Org A", "org-a", org_b_id, "Org B", "org-b"),
        )
        conn.execute(
            "INSERT INTO users (id, workos_user_id, email, name) VALUES "
            "(%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                user_a_id,
                "workos_user_a",
                "a@example.com",
                "User A",
                user_b_id,
                "workos_user_b",
                "b@example.com",
                "User B",
            ),
        )
        conn.execute(
            "INSERT INTO organization_memberships "
            "(organization_id, user_id, role) VALUES "
            "(%s, %s, %s), (%s, %s, %s)",
            (
                org_a_id,
                user_a_id,
                "organization_administrator",
                org_b_id,
                user_b_id,
                "organization_administrator",
            ),
        )
        # Same key string in both orgs — uniqueness is per-organization.
        conn.execute(
            "INSERT INTO idempotency_keys "
            "(organization_id, key, request_hash, status, expires_at) VALUES "
            "(%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)",
            (
                org_a_id,
                "dup-key",
                "hash-a",
                "in_progress",
                expires_at,
                org_b_id,
                "dup-key",
                "hash-b",
                "in_progress",
                expires_at,
            ),
        )
        conn.commit()

    return SeededTenants(
        org_a_id=org_a_id,
        org_b_id=org_b_id,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
    )


@pytest.fixture
def seeded_rls_db(scratch_db: str) -> tuple[str, SeededTenants]:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    # Roles are cluster-wide; re-apply against the scratch DB so GRANT USAGE and
    # ALTER DEFAULT PRIVILEGES take effect in this database.
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_tenants(scratch_db)
    return scratch_db, seed


def test_tenant_select_scoped_to_organization_guc(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )

        memberships = conn.execute(
            "SELECT organization_id FROM organization_memberships"
        ).fetchall()
        keys = conn.execute("SELECT organization_id, key FROM idempotency_keys").fetchall()

    assert {row[0] for row in memberships} == {seed.org_a_id}
    assert {row[0] for row in keys} == {seed.org_a_id}
    assert all(row[1] == "dup-key" for row in keys)


def test_insert_wrong_organization_blocked_by_rls(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO idempotency_keys "
                "(organization_id, key, request_hash, status, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_b_id,
                    "cross-tenant",
                    "hash-cross",
                    "in_progress",
                    expires_at,
                ),
            )


def test_select_fail_closed_without_organization_guc(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, _seed = seeded_rls_db

    # Fresh connection: no set_config — policies must return zero rows.
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        for table in TENANT_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result"


def test_tenant_tables_force_row_level_security(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        for table in TENANT_TABLES:
            forced = conn.execute(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE relname = %s AND relnamespace = "
                "(SELECT oid FROM pg_namespace WHERE nspname = 'public')",
                (table,),
            ).fetchone()[0]
            assert forced is True, f"{table}: expected FORCE RLS"


def test_accord_roles_cannot_bypass_rls(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        for role in ("accord_app", "accord_worker"):
            row = conn.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (role,),
            ).fetchone()
            assert row is not None, f"missing role {role}"
            assert row[0] is False, f"{role}: expected rolsuper=false"
            assert row[1] is False, f"{role}: expected rolbypassrls=false"
