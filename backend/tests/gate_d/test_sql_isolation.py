"""Direct-SQL runtime-role isolation: accord_app + accord_worker adversarial cases.

Extends tests/rls/test_identity_tenancy_rls.py without duplicating its coverage:
scoped SELECT, basic cross-org INSERT block, empty-GUC fail-closed, FORCE RLS,
and rolbypassrls flags are already proven there. This file adds UPDATE/DELETE
cross-org filtering, JOIN leakage, COUNT aggregates, never-set vs empty GUC,
malformed GUC cast errors, worker-role parity, and idempotency-key overlap reads.
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
        # Same role string in both orgs.
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
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_tenants(scratch_db)
    return scratch_db, seed


def _bind_org(conn: psycopg.Connection, role: str, org_id: uuid.UUID) -> None:
    conn.execute(f"SET ROLE {role}")
    conn.execute(
        "SELECT set_config('app.organization_id', %s, false)",
        (str(org_id),),
    )


def test_cross_org_update_and_delete_affect_zero_rows(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_a_id)
        updated = conn.execute(
            "UPDATE organization_memberships SET role = %s WHERE organization_id = %s",
            ("x", seed.org_b_id),
        ).rowcount
        deleted = conn.execute(
            "DELETE FROM organization_memberships WHERE organization_id = %s",
            (seed.org_b_id,),
        ).rowcount
        conn.rollback()

    assert updated == 0
    assert deleted == 0

    # Org B row still intact (superuser / table owner read).
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        role = conn.execute(
            "SELECT role FROM organization_memberships WHERE organization_id = %s",
            (seed.org_b_id,),
        ).fetchone()[0]
    assert role == "organization_administrator"


def test_cross_org_insert_blocked_while_bound_to_org_a(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_a_id)
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO idempotency_keys "
                "(organization_id, key, request_hash, status, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_b_id,
                    "cross-tenant-gate-d",
                    "hash-cross",
                    "in_progress",
                    expires_at,
                ),
            )


def test_join_does_not_surface_org_b_user_identity(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_a_id)
        rows = conn.execute(
            "SELECT u.email, u.name, o.slug "
            "FROM organization_memberships m "
            "JOIN organizations o ON o.id = m.organization_id "
            "JOIN users u ON u.id = m.user_id"
        ).fetchall()

    assert len(rows) == 1
    emails = {row[0] for row in rows}
    names = {row[1] for row in rows}
    slugs = {row[2] for row in rows}
    assert emails == {"a@example.com"}
    assert names == {"User A"}
    assert slugs == {"org-a"}
    assert "b@example.com" not in emails
    assert "User B" not in names
    assert "org-b" not in slugs


def test_count_aggregates_only_org_a_rows(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_a_id)
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TENANT_TABLES
        }

    assert counts == {
        "organization_memberships": 1,
        "idempotency_keys": 1,
    }


def test_absent_guc_fail_closed_matches_empty_string_guc(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        # Never call set_config — GUC unset in this session.
        absent = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TENANT_TABLES
        }

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute("SELECT set_config('app.organization_id', %s, false)", ("",))
        empty = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TENANT_TABLES
        }

    assert absent == {table: 0 for table in TENANT_TABLES}
    assert empty == absent


def test_malformed_organization_guc_raises_uuid_cast_error(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    """Empirical: ::uuid cast in RLS predicate errors; does not silently return 0 rows."""
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            ("not-a-uuid",),
        )
        with pytest.raises(psycopg.Error, match="(?i)invalid input syntax for type uuid"):
            conn.execute("SELECT count(*) FROM organization_memberships")


def test_idempotency_key_overlap_scoped_by_org_guc(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_a_id)
        rows_a = conn.execute(
            "SELECT organization_id, key, request_hash FROM idempotency_keys WHERE key = %s",
            ("dup-key",),
        ).fetchall()

    assert len(rows_a) == 1
    assert rows_a[0][0] == seed.org_a_id
    assert rows_a[0][1] == "dup-key"
    assert rows_a[0][2] == "hash-a"

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_b_id)
        rows_b = conn.execute(
            "SELECT organization_id, key, request_hash FROM idempotency_keys WHERE key = %s",
            ("dup-key",),
        ).fetchall()

    assert len(rows_b) == 1
    assert rows_b[0][0] == seed.org_b_id
    assert rows_b[0][1] == "dup-key"
    assert rows_b[0][2] == "hash-b"


# --- Worker-context parity (SET ROLE accord_worker) ---


def test_worker_select_scoped_to_organization_guc(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_worker", seed.org_a_id)
        memberships = conn.execute(
            "SELECT organization_id FROM organization_memberships"
        ).fetchall()
        keys = conn.execute(
            "SELECT organization_id, request_hash FROM idempotency_keys WHERE key = %s",
            ("dup-key",),
        ).fetchall()

    assert {row[0] for row in memberships} == {seed.org_a_id}
    assert len(keys) == 1
    assert keys[0][0] == seed.org_a_id
    assert keys[0][1] == "hash-a"


def test_worker_cross_org_insert_blocked(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, seed = seeded_rls_db
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_worker", seed.org_a_id)
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO idempotency_keys "
                "(organization_id, key, request_hash, status, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_b_id,
                    "worker-cross",
                    "hash-worker-cross",
                    "in_progress",
                    expires_at,
                ),
            )


def test_worker_fail_closed_without_organization_guc(
    seeded_rls_db: tuple[str, SeededTenants],
) -> None:
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_worker")
        for table in TENANT_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result under accord_worker"
