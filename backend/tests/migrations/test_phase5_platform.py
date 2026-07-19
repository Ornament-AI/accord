"""Phase 5 platform tables migration upgrade and downgrade coverage."""

from __future__ import annotations

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

INITIAL_REVISION = "021faa7dd776"
HEAD_REVISION = "f4b7c1d9e205"

PHASE5_TABLES = (
    "audit_events",
    "outbox_events",
    "payroll_approvals",
    "jobs",
    "export_artifacts",
    "webhook_events",
)

TENANT_RLS_TABLES = (
    "audit_events",
    "outbox_events",
    "payroll_approvals",
    "jobs",
    "export_artifacts",
)

APPEND_ONLY_TRIGGERS = (
    "trg_audit_events_forbid_update_delete",
    "trg_payroll_approvals_forbid_update_delete",
)

OUTBOX_DELETE_TRIGGER = "trg_outbox_events_forbid_delete"


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


def test_phase5_platform_upgrade_downgrade(scratch_db: str) -> None:
    assert len(PHASE5_TABLES) == 6

    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after upgrade head", check)

    assert _alembic_version(scratch_db) == HEAD_REVISION
    for table in PHASE5_TABLES:
        assert _table_exists(scratch_db, table), f"expected table {table}"

    for table in TENANT_RLS_TABLES:
        enabled, forced = _rls_flags(scratch_db, table)
        assert enabled is True, f"{table}: expected relrowsecurity"
        assert forced is True, f"{table}: expected relforcerowsecurity"

    # webhook_events is global — no RLS.
    enabled, forced = _rls_flags(scratch_db, "webhook_events")
    assert enabled is False, "webhook_events: expected no RLS"
    assert forced is False, "webhook_events: expected no FORCE RLS"

    assert _function_exists(scratch_db, "accord_forbid_update_delete")
    assert _function_exists(scratch_db, "accord_forbid_delete")
    for trigger_name in APPEND_ONLY_TRIGGERS:
        assert _trigger_exists(scratch_db, trigger_name), f"expected trigger {trigger_name}"
    assert _trigger_exists(scratch_db, OUTBOX_DELETE_TRIGGER)

    down = run_alembic(scratch_db, "downgrade", INITIAL_REVISION)
    assert down.returncode == 0, diag(f"alembic downgrade {INITIAL_REVISION}", down)

    assert _alembic_version(scratch_db) == INITIAL_REVISION
    for table in PHASE5_TABLES:
        assert not _table_exists(scratch_db, table), f"table {table} should be gone"
    assert not _function_exists(scratch_db, "accord_forbid_delete")
    # Phase 4 owns this function — must survive Phase 5 downgrade.
    assert _function_exists(scratch_db, "accord_forbid_update_delete")
    for trigger_name in APPEND_ONLY_TRIGGERS:
        assert not _trigger_exists(scratch_db, trigger_name), (
            f"trigger {trigger_name} should be gone"
        )
    assert not _trigger_exists(scratch_db, OUTBOX_DELETE_TRIGGER)

    # Phase 4 tables must still exist after downgrade to INITIAL.
    assert _table_exists(scratch_db, "payroll_runs")
    assert _table_exists(scratch_db, "payroll_run_versions")

    up2 = run_alembic(scratch_db, "upgrade", "head")
    assert up2.returncode == 0, diag("alembic re-upgrade head", up2)
    assert _alembic_version(scratch_db) == HEAD_REVISION
    for table in PHASE5_TABLES:
        assert _table_exists(scratch_db, table), f"expected table {table} after round-trip"

    check2 = run_alembic(scratch_db, "check")
    assert check2.returncode == 0, diag("alembic check after round-trip", check2)
