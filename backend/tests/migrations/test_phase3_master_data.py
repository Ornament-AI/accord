"""Phase 3 master-data migration upgrade and downgrade coverage."""

from __future__ import annotations

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

INITIAL_REVISION = "c8d4e2f1a9b7"
HEAD_REVISION = "e2b9d47c1503"

PHASE3_TABLES = (
    "offices",
    "payroll_units",
    "posts",
    "employee_groups",
    "employees",
    "employee_profile_versions",
    "employee_posting_versions",
    "employee_pay_versions",
    "employee_bank_account_versions",
    "pay_components",
    "component_rate_versions",
    "recurring_instructions",
    "recurring_instruction_versions",
    "advance_accounts",
    "advance_installment_versions",
    "accommodation_assignments",
    "accommodation_charge_versions",
    "report_configurations",
)

SELF_MEMBERSHIP_POLICIES = (
    "self_membership_read",
    "self_membership_read_worker",
)


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


def _policy_exists(database_url: str, table_name: str, policy_name: str) -> bool:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        return (
            conn.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = %s AND policyname = %s"
                ")",
                (table_name, policy_name),
            ).fetchone()[0]
            is True
        )


def test_phase3_master_data_upgrade_downgrade(scratch_db: str) -> None:
    assert len(PHASE3_TABLES) == 18

    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after upgrade head", check)

    assert _alembic_version(scratch_db) == HEAD_REVISION
    for table in PHASE3_TABLES:
        assert _table_exists(scratch_db, table), f"expected table {table}"
        enabled, forced = _rls_flags(scratch_db, table)
        assert enabled is True, f"{table}: expected relrowsecurity"
        assert forced is True, f"{table}: expected relforcerowsecurity"

    for policy_name in SELF_MEMBERSHIP_POLICIES:
        assert _policy_exists(scratch_db, "organization_memberships", policy_name), (
            f"expected policy {policy_name}"
        )

    down = run_alembic(scratch_db, "downgrade", INITIAL_REVISION)
    assert down.returncode == 0, diag(f"alembic downgrade {INITIAL_REVISION}", down)

    assert _alembic_version(scratch_db) == INITIAL_REVISION
    for table in PHASE3_TABLES:
        assert not _table_exists(scratch_db, table), f"table {table} should be gone"
    for policy_name in SELF_MEMBERSHIP_POLICIES:
        assert not _policy_exists(scratch_db, "organization_memberships", policy_name), (
            f"policy {policy_name} should be gone"
        )

    # Phase 2 identity tables must still exist after downgrade to INITIAL.
    assert _table_exists(scratch_db, "organizations")
    assert _table_exists(scratch_db, "organization_memberships")

    down_base = run_alembic(scratch_db, "downgrade", "base")
    assert down_base.returncode == 0, diag("alembic downgrade base", down_base)
    assert _alembic_version(scratch_db) is None
