"""Grant-level backstop for immutable financial tables (ADR-0009).

Verifies that UPDATE/DELETE remain denied for ``accord_app`` even when the
``accord.allow_immutable_ddl`` trigger escape hatch is enabled, proving the
REVOKE is distinct from the ``accord_forbid_update_delete`` trigger.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.types.json import Json

from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
)
from tests.rls.test_payroll_run_rls import SeededPayrollRunData, _seed_payroll_run_data


def _grant_full_table_dml(database_url: str) -> None:
    """Simulate create_roles.sql default privileges (full DML present)."""
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_audit_event(database_url: str, org_id: uuid.UUID) -> uuid.UUID:
    audit_id = uuid.uuid4()
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO audit_events "
            "(id, organization_id, command, entity_type, entity_id, summary) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                audit_id,
                org_id,
                "post",
                "payroll_run",
                uuid.uuid4(),
                Json({"after": {"status": "posted"}}),
            ),
        )
        conn.commit()
    return audit_id


def _set_app_role(conn: psycopg.Connection, org_id: uuid.UUID) -> None:
    conn.execute("SET ROLE accord_app")
    conn.execute(
        "SELECT set_config('app.organization_id', %s, false)",
        (str(org_id),),
    )


@pytest.fixture
def immutable_grants_db(scratch_db: str) -> tuple[str, SeededPayrollRunData, uuid.UUID]:
    # Critical ordering: stop before the revoke migration, simulate default
    # privileges, then upgrade so the new REVOKE genuinely removes grants.
    up_prev = run_alembic(scratch_db, "upgrade", "a9f3c2e81b04")
    assert up_prev.returncode == 0, diag("alembic upgrade a9f3c2e81b04", up_prev)

    ensure_accord_roles(database_url=scratch_db)
    _grant_full_table_dml(scratch_db)

    up_head = run_alembic(scratch_db, "upgrade", "head")
    assert up_head.returncode == 0, diag("alembic upgrade head", up_head)

    seed = _seed_payroll_run_data(scratch_db)
    audit_id = _seed_audit_event(scratch_db, seed.org_id)
    return scratch_db, seed, audit_id


def test_immutable_tables_deny_update_delete_despite_trigger_escape(
    immutable_grants_db: tuple[str, SeededPayrollRunData, uuid.UUID],
) -> None:
    database_url, seed, audit_id = immutable_grants_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        _set_app_role(conn, seed.org_id)

        # (a) UPDATE denied even with trigger escape hatch enabled.
        conn.execute("BEGIN")
        conn.execute("SET LOCAL accord.allow_immutable_ddl = 'on'")
        with pytest.raises(psycopg.Error, match="(?i)permission denied"):
            conn.execute(
                "UPDATE payroll_result_lines SET amount = %s WHERE id = %s",
                ("999.99", seed.line_id),
            )
        conn.rollback()
        _set_app_role(conn, seed.org_id)

        # (b) DELETE denied even with trigger escape hatch enabled.
        conn.execute("BEGIN")
        conn.execute("SET LOCAL accord.allow_immutable_ddl = 'on'")
        with pytest.raises(psycopg.Error, match="(?i)permission denied"):
            conn.execute(
                "DELETE FROM payroll_result_lines WHERE id = %s",
                (seed.line_id,),
            )
        conn.rollback()
        _set_app_role(conn, seed.org_id)

        # (c) audit_events UPDATE/DELETE denied (grant backstop re-asserted).
        with pytest.raises(psycopg.Error, match="(?i)permission denied"):
            conn.execute(
                "UPDATE audit_events SET command = %s WHERE id = %s",
                ("tamper", audit_id),
            )
        conn.rollback()
        _set_app_role(conn, seed.org_id)

        with pytest.raises(psycopg.Error, match="(?i)permission denied"):
            conn.execute("DELETE FROM audit_events WHERE id = %s", (audit_id,))
        conn.rollback()
        _set_app_role(conn, seed.org_id)

        # (d) SELECT still works within org.
        lines = conn.execute(
            "SELECT id FROM payroll_result_lines WHERE id = %s",
            (seed.line_id,),
        ).fetchall()
        audits = conn.execute(
            "SELECT id FROM audit_events WHERE id = %s",
            (audit_id,),
        ).fetchall()
        assert {row[0] for row in lines} == {seed.line_id}
        assert {row[0] for row in audits} == {audit_id}

        # (e) INSERT still works (insert-then-immutable).
        conn.execute(
            "INSERT INTO payroll_result_lines "
            "(organization_id, employee_result_id, component_code, "
            "classification, calc_kind, amount, sequence, trace) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                seed.org_id,
                seed.result_id,
                "HRA",
                "earning",
                "fixed_recurring_amount",
                "500.00",
                2,
                Json({"component": "HRA"}),
            ),
        )
        conn.execute(
            "INSERT INTO audit_events "
            "(organization_id, command, entity_type, entity_id, summary) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                seed.org_id,
                "calculate",
                "payroll_run",
                seed.run_id,
                Json({"after": {"status": "calculated"}}),
            ),
        )
        conn.commit()
