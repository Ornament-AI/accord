"""Behavioral RLS tests for Phase 2 tenant-owned tables (ADR 0011).

SET ROLE accord_app on a superuser connection is the intended approach here:
FORCE RLS still applies, so policies are exercised without needing role passwords.

Isolation proofs use a single organization row: empty/wrong GUC ⇒ 0 rows;
correct GUC ⇒ rows; second organization INSERT fails the singleton unique index.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.errors import UniqueViolation

from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
)

TENANT_TABLES = (
    "organization_memberships",
    "organization_settings",
    "idempotency_keys",
)


@dataclass(frozen=True)
class SeededOrg:
    org_id: uuid.UUID
    user_id: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_org(database_url: str) -> SeededOrg:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
            (org_id, "Org A", "org-a"),
        )
        conn.execute(
            "INSERT INTO users (id, workos_user_id, email, name) VALUES (%s, %s, %s, %s)",
            (user_id, "workos_user_a", "a@example.com", "User A"),
        )
        conn.execute(
            "INSERT INTO organization_memberships "
            "(organization_id, user_id, role) VALUES (%s, %s, %s)",
            (org_id, user_id, "organization_administrator"),
        )
        conn.execute(
            "INSERT INTO organization_settings (organization_id) VALUES (%s)",
            (org_id,),
        )
        conn.execute(
            "INSERT INTO idempotency_keys "
            "(organization_id, key, request_hash, status, expires_at) VALUES "
            "(%s, %s, %s, %s, %s)",
            (org_id, "dup-key", "hash-a", "in_progress", expires_at),
        )
        conn.commit()

    return SeededOrg(org_id=org_id, user_id=user_id)


@pytest.fixture
def seeded_rls_db(scratch_db: str) -> tuple[str, SeededOrg]:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    # Roles are cluster-wide; re-apply against the scratch DB so GRANT USAGE and
    # ALTER DEFAULT PRIVILEGES take effect in this database.
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_org(scratch_db)
    return scratch_db, seed


def test_tenant_select_scoped_to_organization_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_id),),
        )

        memberships = conn.execute(
            "SELECT organization_id FROM organization_memberships"
        ).fetchall()
        settings = conn.execute("SELECT organization_id FROM organization_settings").fetchall()
        keys = conn.execute("SELECT organization_id, key FROM idempotency_keys").fetchall()

    assert {row[0] for row in memberships} == {seed.org_id}
    assert {row[0] for row in settings} == {seed.org_id}
    assert {row[0] for row in keys} == {seed.org_id}
    assert all(row[1] == "dup-key" for row in keys)


def test_select_fail_closed_with_wrong_organization_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, _seed = seeded_rls_db
    wrong_org_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(wrong_org_id),),
        )
        for table in TENANT_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected zero rows under wrong GUC"


def test_insert_blocked_while_bound_to_wrong_organization_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    wrong_org_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(wrong_org_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO idempotency_keys "
                "(organization_id, key, request_hash, status, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_id,
                    "cross-tenant",
                    "hash-cross",
                    "in_progress",
                    expires_at,
                ),
            )


def test_select_fail_closed_without_organization_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, _seed = seeded_rls_db

    # Fresh connection: no set_config — policies must return zero rows.
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        for table in TENANT_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result"


def test_second_organization_insert_fails_singleton_index(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(UniqueViolation, match="(?i)uq_organizations_singleton"):
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
                (uuid.uuid4(), "Org B", "org-b"),
            )


def test_tenant_tables_force_row_level_security(
    seeded_rls_db: tuple[str, SeededOrg],
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
    seeded_rls_db: tuple[str, SeededOrg],
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
