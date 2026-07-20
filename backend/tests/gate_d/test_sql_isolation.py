"""Direct-SQL runtime-role isolation: accord_app + accord_worker (ADR 0011).

Extends tests/rls/test_identity_tenancy_rls.py without duplicating its coverage:
scoped SELECT, basic wrong-GUC INSERT block, empty-GUC fail-closed, FORCE RLS,
and rolbypassrls flags are already proven there. This file adds UPDATE/DELETE
fail-closed filtering, JOIN leakage, COUNT aggregates, never-set vs empty GUC,
malformed GUC cast errors, worker-role parity, and singleton org enforcement.
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
    other_user_id: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_org(database_url: str) -> SeededOrg:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
            (org_id, "Org A", "org-a"),
        )
        conn.execute(
            "INSERT INTO users (id, workos_user_id, email, name) VALUES "
            "(%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                user_id,
                "workos_user_a",
                "a@example.com",
                "User A",
                other_user_id,
                "workos_user_b",
                "b@example.com",
                "User B",
            ),
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

    return SeededOrg(org_id=org_id, user_id=user_id, other_user_id=other_user_id)


@pytest.fixture
def seeded_rls_db(scratch_db: str) -> tuple[str, SeededOrg]:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_org(scratch_db)
    return scratch_db, seed


def _bind_org(conn: psycopg.Connection, role: str, org_id: uuid.UUID) -> None:
    conn.execute(f"SET ROLE {role}")
    conn.execute(
        "SELECT set_config('app.organization_id', %s, false)",
        (str(org_id),),
    )


def test_wrong_guc_update_and_delete_affect_zero_rows(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db
    wrong_org_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", wrong_org_id)
        updated = conn.execute(
            "UPDATE organization_memberships SET role = %s WHERE organization_id = %s",
            ("x", seed.org_id),
        ).rowcount
        deleted = conn.execute(
            "DELETE FROM organization_memberships WHERE organization_id = %s",
            (seed.org_id,),
        ).rowcount
        conn.rollback()

    assert updated == 0
    assert deleted == 0

    # Row still intact (superuser / table owner read).
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        role = conn.execute(
            "SELECT role FROM organization_memberships WHERE organization_id = %s",
            (seed.org_id,),
        ).fetchone()[0]
    assert role == "organization_administrator"


def test_insert_blocked_while_bound_to_wrong_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    wrong_org_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", wrong_org_id)
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO idempotency_keys "
                "(organization_id, key, request_hash, status, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_id,
                    "cross-tenant-gate-d",
                    "hash-cross",
                    "in_progress",
                    expires_at,
                ),
            )


def test_join_does_not_surface_rows_under_wrong_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_id)
        rows = conn.execute(
            "SELECT u.email, u.name, o.slug "
            "FROM organization_memberships m "
            "JOIN organizations o ON o.id = m.organization_id "
            "JOIN users u ON u.id = m.user_id"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "a@example.com"
    assert rows[0][1] == "User A"
    assert rows[0][2] == "org-a"

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", uuid.uuid4())
        wrong = conn.execute(
            "SELECT u.email FROM organization_memberships m JOIN users u ON u.id = m.user_id"
        ).fetchall()

    assert wrong == []


def test_count_aggregates_only_bound_org_rows(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_id)
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TENANT_TABLES
        }

    assert counts == {
        "organization_memberships": 1,
        "organization_settings": 1,
        "idempotency_keys": 1,
    }

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", uuid.uuid4())
        wrong_counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TENANT_TABLES
        }

    assert wrong_counts == {table: 0 for table in TENANT_TABLES}


def test_absent_guc_fail_closed_matches_empty_string_guc(
    seeded_rls_db: tuple[str, SeededOrg],
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
    seeded_rls_db: tuple[str, SeededOrg],
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


def test_idempotency_key_scoped_by_org_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", seed.org_id)
        rows = conn.execute(
            "SELECT organization_id, key, request_hash FROM idempotency_keys WHERE key = %s",
            ("dup-key",),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == seed.org_id
    assert rows[0][1] == "dup-key"
    assert rows[0][2] == "hash-a"

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_app", uuid.uuid4())
        wrong = conn.execute(
            "SELECT organization_id FROM idempotency_keys WHERE key = %s",
            ("dup-key",),
        ).fetchall()

    assert wrong == []


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


# --- Worker-context parity (SET ROLE accord_worker) ---


def test_worker_select_scoped_to_organization_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_worker", seed.org_id)
        memberships = conn.execute(
            "SELECT organization_id FROM organization_memberships"
        ).fetchall()
        keys = conn.execute(
            "SELECT organization_id, request_hash FROM idempotency_keys WHERE key = %s",
            ("dup-key",),
        ).fetchall()

    assert {row[0] for row in memberships} == {seed.org_id}
    assert len(keys) == 1
    assert keys[0][0] == seed.org_id
    assert keys[0][1] == "hash-a"

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_worker", uuid.uuid4())
        assert conn.execute("SELECT count(*) FROM organization_memberships").fetchone()[0] == 0


def test_worker_insert_blocked_while_bound_to_wrong_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, seed = seeded_rls_db
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _bind_org(conn, "accord_worker", uuid.uuid4())
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO idempotency_keys "
                "(organization_id, key, request_hash, status, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_id,
                    "worker-cross",
                    "hash-worker-cross",
                    "in_progress",
                    expires_at,
                ),
            )


def test_worker_fail_closed_without_organization_guc(
    seeded_rls_db: tuple[str, SeededOrg],
) -> None:
    database_url, _seed = seeded_rls_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_worker")
        for table in TENANT_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result under accord_worker"
