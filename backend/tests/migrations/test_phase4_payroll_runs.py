"""Phase 4 payroll run persistence migration upgrade and downgrade coverage."""

from __future__ import annotations

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

INITIAL_REVISION = "2f397740f38a"
HEAD_REVISION = "e6a8c4d2f901"

PHASE4_TABLES = (
    "payroll_periods",
    "payroll_runs",
    "payroll_run_inputs",
    "payroll_run_versions",
    "payroll_employee_results",
    "payroll_result_lines",
)

IMMUTABLE_TRIGGERS = (
    "trg_payroll_run_versions_forbid_update_delete",
    "trg_payroll_employee_results_forbid_update_delete",
    "trg_payroll_result_lines_forbid_update_delete",
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


def _function_exists(database_url: str, function_name: str) -> bool:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        return (
            conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = %s)",
                (function_name,),
            ).fetchone()[0]
            is True
        )


def _trigger_exists(database_url: str, trigger_name: str) -> bool:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        return (
            conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = %s AND NOT tgisinternal)",
                (trigger_name,),
            ).fetchone()[0]
            is True
        )


def test_phase4_payroll_runs_upgrade_downgrade(scratch_db: str) -> None:
    assert len(PHASE4_TABLES) == 6

    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after upgrade head", check)

    assert _alembic_version(scratch_db) == HEAD_REVISION
    for table in PHASE4_TABLES:
        assert _table_exists(scratch_db, table), f"expected table {table}"
        enabled, forced = _rls_flags(scratch_db, table)
        assert enabled is True, f"{table}: expected relrowsecurity"
        assert forced is True, f"{table}: expected relforcerowsecurity"

    assert _function_exists(scratch_db, "accord_forbid_update_delete")
    for trigger_name in IMMUTABLE_TRIGGERS:
        assert _trigger_exists(scratch_db, trigger_name), f"expected trigger {trigger_name}"

    down = run_alembic(scratch_db, "downgrade", INITIAL_REVISION)
    assert down.returncode == 0, diag(f"alembic downgrade {INITIAL_REVISION}", down)

    assert _alembic_version(scratch_db) == INITIAL_REVISION
    for table in PHASE4_TABLES:
        assert not _table_exists(scratch_db, table), f"table {table} should be gone"
    assert not _function_exists(scratch_db, "accord_forbid_update_delete")
    for trigger_name in IMMUTABLE_TRIGGERS:
        assert not _trigger_exists(scratch_db, trigger_name), (
            f"trigger {trigger_name} should be gone"
        )

    # Phase 3 tables must still exist after downgrade to INITIAL.
    assert _table_exists(scratch_db, "organizations")
    assert _table_exists(scratch_db, "employees")

    up2 = run_alembic(scratch_db, "upgrade", "head")
    assert up2.returncode == 0, diag("alembic re-upgrade head", up2)
    assert _alembic_version(scratch_db) == HEAD_REVISION
    for table in PHASE4_TABLES:
        assert _table_exists(scratch_db, table), f"expected table {table} after round-trip"

    check2 = run_alembic(scratch_db, "check")
    assert check2.returncode == 0, diag("alembic check after round-trip", check2)
