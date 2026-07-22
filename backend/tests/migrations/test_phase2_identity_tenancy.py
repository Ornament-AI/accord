"""Phase 2 identity/tenancy migration upgrade and downgrade coverage."""

from __future__ import annotations

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

INITIAL_REVISION = "b7e3c1a90f24"
HEAD_REVISION = "a7d3e5f9b102"

IDENTITY_TABLES = (
    "users",
    "organizations",
    "organization_memberships",
    "organization_settings",
    "idempotency_keys",
    "sessions",
)
TENANT_RLS_TABLES = (
    "organization_memberships",
    "organization_settings",
    "idempotency_keys",
)
NON_RLS_TABLES = ("users", "organizations", "sessions")


def _alembic_version(database_url: str) -> str | None:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        exists = conn.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        ).fetchone()[0]
        if not exists:
            return None
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else row[0]


def _extension_exists(database_url: str, name: str) -> bool:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        return (
            conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = %s)",
                (name,),
            ).fetchone()[0]
            is True
        )


def _table_exists(database_url: str, table_name: str) -> bool:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        return (
            conn.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = %s"
                ")",
                (table_name,),
            ).fetchone()[0]
            is True
        )


def _rls_flags(database_url: str, table_name: str) -> tuple[bool, bool]:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        row = conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity "
            "FROM pg_class "
            "WHERE relname = %s AND relnamespace = "
            "(SELECT oid FROM pg_namespace WHERE nspname = 'public')",
            (table_name,),
        ).fetchone()
    assert row is not None, f"table {table_name!r} missing"
    return bool(row[0]), bool(row[1])


def test_phase2_identity_tenancy_upgrade_downgrade(scratch_db: str) -> None:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after upgrade head", check)

    assert _alembic_version(scratch_db) == HEAD_REVISION
    for table in IDENTITY_TABLES:
        assert _table_exists(scratch_db, table), f"expected table {table}"
    for table in TENANT_RLS_TABLES:
        enabled, forced = _rls_flags(scratch_db, table)
        assert enabled is True, f"{table}: expected relrowsecurity"
        assert forced is True, f"{table}: expected relforcerowsecurity"

    for table in NON_RLS_TABLES:
        enabled, forced = _rls_flags(scratch_db, table)
        assert enabled is False, f"{table}: unexpected relrowsecurity"
        assert forced is False, f"{table}: unexpected relforcerowsecurity"

    down = run_alembic(scratch_db, "downgrade", INITIAL_REVISION)
    assert down.returncode == 0, diag(f"alembic downgrade {INITIAL_REVISION}", down)

    assert _alembic_version(scratch_db) == INITIAL_REVISION
    for table in IDENTITY_TABLES:
        assert not _table_exists(scratch_db, table), f"table {table} should be gone"
    assert not _extension_exists(scratch_db, "citext")
    assert _extension_exists(scratch_db, "btree_gist")

    down_base = run_alembic(scratch_db, "downgrade", "base")
    assert down_base.returncode == 0, diag("alembic downgrade base", down_base)
    assert _alembic_version(scratch_db) is None
