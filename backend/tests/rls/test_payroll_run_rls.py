"""Behavioral RLS tests for Phase 4 payroll run persistence tables."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
)

RLS_SPOT_CHECK_TABLES = (
    "payroll_runs",
    "payroll_result_lines",
)


@dataclass(frozen=True)
class SeededPayrollRunData:
    org_a_id: uuid.UUID
    org_b_id: uuid.UUID
    employee_a_id: uuid.UUID
    employee_b_id: uuid.UUID
    period_a_id: uuid.UUID
    period_b_id: uuid.UUID
    run_a_id: uuid.UUID
    run_b_id: uuid.UUID
    version_a_id: uuid.UUID
    version_b_id: uuid.UUID
    result_a_id: uuid.UUID
    result_b_id: uuid.UUID
    line_a_id: uuid.UUID
    line_b_id: uuid.UUID
    calculated_by: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_payroll_run_data(database_url: str) -> SeededPayrollRunData:
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    employee_a_id = uuid.uuid4()
    employee_b_id = uuid.uuid4()
    period_a_id = uuid.uuid4()
    period_b_id = uuid.uuid4()
    run_a_id = uuid.uuid4()
    run_b_id = uuid.uuid4()
    version_a_id = uuid.uuid4()
    version_b_id = uuid.uuid4()
    result_a_id = uuid.uuid4()
    result_b_id = uuid.uuid4()
    line_a_id = uuid.uuid4()
    line_b_id = uuid.uuid4()
    calculated_by = uuid.uuid4()
    calculated_at = datetime.now(timezone.utc)

    inputs_snapshot = {"employees": [{"id": "e1", "inputs": []}]}
    totals = {"earnings": "1000.00", "deductions": "100.00", "net": "900.00"}
    trace = {
        "component": "BASIC",
        "classification": "earning",
        "rounded_value": "1000.00",
    }

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s), (%s, %s, %s)",
            (org_a_id, "Org A", "org-a", org_b_id, "Org B", "org-b"),
        )
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) VALUES "
            "(%s, %s, %s), (%s, %s, %s)",
            (
                employee_a_id,
                org_a_id,
                "E-001",
                employee_b_id,
                org_b_id,
                "E-001",
            ),
        )
        conn.execute(
            "INSERT INTO payroll_periods "
            "(id, organization_id, period_year, period_month, status) VALUES "
            "(%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)",
            (
                period_a_id,
                org_a_id,
                2026,
                7,
                "open",
                period_b_id,
                org_b_id,
                2026,
                7,
                "open",
            ),
        )
        conn.execute(
            "INSERT INTO payroll_runs "
            "(id, organization_id, period_id, run_type, status) VALUES "
            "(%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)",
            (
                run_a_id,
                org_a_id,
                period_a_id,
                "regular",
                "draft",
                run_b_id,
                org_b_id,
                period_b_id,
                "regular",
                "draft",
            ),
        )
        conn.execute(
            "INSERT INTO payroll_run_versions "
            "(id, organization_id, run_id, version_number, engine_version, "
            "content_hash, calculated_at, calculated_by, inputs_snapshot, totals) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s), "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                version_a_id,
                org_a_id,
                run_a_id,
                1,
                "engine-1.0",
                "hash-a",
                calculated_at,
                calculated_by,
                Json(inputs_snapshot),
                Json(totals),
                version_b_id,
                org_b_id,
                run_b_id,
                1,
                "engine-1.0",
                "hash-b",
                calculated_at,
                calculated_by,
                Json(inputs_snapshot),
                Json(totals),
            ),
        )
        conn.execute(
            "INSERT INTO payroll_employee_results "
            "(id, organization_id, run_version_id, employee_id, employee_number, "
            "earnings_total, employer_contribution_total, gross_total, "
            "deductions_total, net_payable) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s), "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                result_a_id,
                org_a_id,
                version_a_id,
                employee_a_id,
                "E-001",
                "1000.00",
                "200.00",
                "1200.00",
                "100.00",
                "900.00",
                result_b_id,
                org_b_id,
                version_b_id,
                employee_b_id,
                "E-001",
                "2000.00",
                "400.00",
                "2400.00",
                "200.00",
                "1800.00",
            ),
        )
        conn.execute(
            "INSERT INTO payroll_result_lines "
            "(id, organization_id, employee_result_id, component_code, "
            "classification, calc_kind, amount, sequence, trace) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s), "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                line_a_id,
                org_a_id,
                result_a_id,
                "BASIC",
                "earning",
                "fixed_recurring_amount",
                "1000.00",
                1,
                Json(trace),
                line_b_id,
                org_b_id,
                result_b_id,
                "BASIC",
                "earning",
                "fixed_recurring_amount",
                "2000.00",
                1,
                Json(trace),
            ),
        )
        conn.commit()

    return SeededPayrollRunData(
        org_a_id=org_a_id,
        org_b_id=org_b_id,
        employee_a_id=employee_a_id,
        employee_b_id=employee_b_id,
        period_a_id=period_a_id,
        period_b_id=period_b_id,
        run_a_id=run_a_id,
        run_b_id=run_b_id,
        version_a_id=version_a_id,
        version_b_id=version_b_id,
        result_a_id=result_a_id,
        result_b_id=result_b_id,
        line_a_id=line_a_id,
        line_b_id=line_b_id,
        calculated_by=calculated_by,
    )


@pytest.fixture
def seeded_payroll_run_db(scratch_db: str) -> tuple[str, SeededPayrollRunData]:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_payroll_run_data(scratch_db)
    return scratch_db, seed


@pytest.mark.parametrize("role", ("accord_app", "accord_worker"))
def test_payroll_run_select_scoped_to_organization_guc(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
    role: str,
) -> None:
    database_url, seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(f"SET ROLE {role}")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        runs = conn.execute("SELECT organization_id FROM payroll_runs").fetchall()
        lines = conn.execute("SELECT organization_id FROM payroll_result_lines").fetchall()

    assert {row[0] for row in runs} == {seed.org_a_id}
    assert {row[0] for row in lines} == {seed.org_a_id}


def test_payroll_run_insert_wrong_organization_blocked(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO payroll_runs "
                "(organization_id, period_id, run_type, status) "
                "VALUES (%s, %s, %s, %s)",
                (seed.org_b_id, seed.period_b_id, "regular", "draft"),
            )
        conn.rollback()
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )

        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO payroll_result_lines "
                "(organization_id, employee_result_id, component_code, "
                "classification, calc_kind, amount, sequence, trace) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    seed.org_b_id,
                    seed.result_b_id,
                    "HRA",
                    "earning",
                    "fixed_recurring_amount",
                    "500.00",
                    2,
                    Json({"component": "HRA"}),
                ),
            )


@pytest.mark.parametrize("role", ("accord_app", "accord_worker"))
def test_payroll_run_select_fail_closed_without_organization_guc(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
    role: str,
) -> None:
    database_url, _seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(f"SET ROLE {role}")
        for table in RLS_SPOT_CHECK_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result"


def test_payroll_run_immutability_triggers(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(psycopg.Error, match="(?i)accord: UPDATE/DELETE forbidden"):
            conn.execute(
                "UPDATE payroll_run_versions SET engine_version = %s WHERE id = %s",
                ("engine-x", seed.version_a_id),
            )
        conn.rollback()

        with pytest.raises(psycopg.Error, match="(?i)accord: UPDATE/DELETE forbidden"):
            conn.execute(
                "DELETE FROM payroll_run_versions WHERE id = %s",
                (seed.version_a_id,),
            )
        conn.rollback()

        with pytest.raises(psycopg.Error, match="(?i)accord: UPDATE/DELETE forbidden"):
            conn.execute(
                "UPDATE payroll_result_lines SET amount = %s WHERE id = %s",
                ("999.99", seed.line_a_id),
            )
        conn.rollback()

        conn.execute("BEGIN")
        conn.execute("SET LOCAL accord.allow_immutable_ddl = 'on'")
        conn.execute(
            "UPDATE payroll_run_versions SET engine_version = %s WHERE id = %s",
            ("engine-updated", seed.version_a_id),
        )
        conn.commit()

        conn.execute("BEGIN")
        conn.execute("SET LOCAL accord.allow_immutable_ddl = 'on'")
        conn.execute(
            "DELETE FROM payroll_result_lines WHERE id = %s",
            (seed.line_a_id,),
        )
        conn.commit()


def test_payroll_runs_partial_unique_regular_index(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(UniqueViolation):
            conn.execute(
                "INSERT INTO payroll_runs "
                "(organization_id, period_id, run_type, status) "
                "VALUES (%s, %s, %s, %s)",
                (seed.org_a_id, seed.period_a_id, "regular", "draft"),
            )
        conn.rollback()

        conn.execute(
            "INSERT INTO payroll_runs "
            "(organization_id, period_id, run_type, status) "
            "VALUES (%s, %s, %s, %s)",
            (seed.org_a_id, seed.period_a_id, "supplemental", "draft"),
        )
        conn.commit()
