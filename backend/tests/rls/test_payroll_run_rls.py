"""Behavioral RLS tests for Phase 4 payroll run persistence tables (ADR 0011).

Isolation proofs use a single organization row: empty/wrong GUC ⇒ 0 rows;
correct GUC ⇒ rows; second organization INSERT fails the singleton unique index.
"""

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
    org_id: uuid.UUID
    employee_id: uuid.UUID
    period_id: uuid.UUID
    run_id: uuid.UUID
    version_id: uuid.UUID
    result_id: uuid.UUID
    line_id: uuid.UUID
    calculated_by: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_payroll_run_data(database_url: str) -> SeededPayrollRunData:
    org_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    period_id = uuid.uuid4()
    run_id = uuid.uuid4()
    version_id = uuid.uuid4()
    result_id = uuid.uuid4()
    line_id = uuid.uuid4()
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
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
            (org_id, "Org A", "org-a"),
        )
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) VALUES "
            "(%s, %s, %s)",
            (employee_id, org_id, "E-001"),
        )
        conn.execute(
            "INSERT INTO payroll_periods "
            "(id, organization_id, period_year, period_month, status) VALUES "
            "(%s, %s, %s, %s, %s)",
            (period_id, org_id, 2026, 7, "open"),
        )
        conn.execute(
            "INSERT INTO payroll_runs "
            "(id, organization_id, period_id, status) VALUES "
            "(%s, %s, %s, %s)",
            (run_id, org_id, period_id, "draft"),
        )
        conn.execute(
            "INSERT INTO payroll_run_versions "
            "(id, organization_id, run_id, version_number, engine_version, "
            "content_hash, calculated_at, calculated_by, inputs_snapshot, totals) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                version_id,
                org_id,
                run_id,
                1,
                "engine-1.0",
                "hash-a",
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
            "deductions_total, net_payable, offbill_employer_remittance, "
            "disbursement) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                result_id,
                org_id,
                version_id,
                employee_id,
                "E-001",
                "1000.00",
                "200.00",
                "1200.00",
                "100.00",
                "900.00",
                "0.00",
                "900.00",
            ),
        )
        conn.execute(
            "INSERT INTO payroll_result_lines "
            "(id, organization_id, employee_result_id, component_code, "
            "classification, calc_kind, amount, sequence, trace) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                line_id,
                org_id,
                result_id,
                "BASIC",
                "earning",
                "fixed_recurring_amount",
                "1000.00",
                1,
                Json(trace),
            ),
        )
        conn.commit()

    return SeededPayrollRunData(
        org_id=org_id,
        employee_id=employee_id,
        period_id=period_id,
        run_id=run_id,
        version_id=version_id,
        result_id=result_id,
        line_id=line_id,
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
            (str(seed.org_id),),
        )
        runs = conn.execute("SELECT organization_id FROM payroll_runs").fetchall()
        lines = conn.execute("SELECT organization_id FROM payroll_result_lines").fetchall()

    assert {row[0] for row in runs} == {seed.org_id}
    assert {row[0] for row in lines} == {seed.org_id}


def test_payroll_run_select_fail_closed_with_wrong_organization_guc(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, _seed = seeded_payroll_run_db
    wrong_org_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(wrong_org_id),),
        )
        for table in RLS_SPOT_CHECK_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected zero rows under wrong GUC"


def test_payroll_run_insert_blocked_while_bound_to_wrong_organization_guc(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, seed = seeded_payroll_run_db
    wrong_org_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(wrong_org_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO payroll_runs "
                "(organization_id, period_id, original_run_id, status) "
                "VALUES (%s, %s, %s, %s)",
                (seed.org_id, seed.period_id, seed.run_id, "draft"),
            )
        conn.rollback()
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(wrong_org_id),),
        )

        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
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


def test_second_organization_insert_fails_singleton_index(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, _seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(UniqueViolation, match="(?i)uq_organizations_singleton"):
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
                (uuid.uuid4(), "Org B", "org-b"),
            )


def test_payroll_run_immutability_triggers(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(psycopg.Error, match="(?i)accord: UPDATE/DELETE forbidden"):
            conn.execute(
                "UPDATE payroll_run_versions SET engine_version = %s WHERE id = %s",
                ("engine-x", seed.version_id),
            )
        conn.rollback()

        with pytest.raises(psycopg.Error, match="(?i)accord: UPDATE/DELETE forbidden"):
            conn.execute(
                "DELETE FROM payroll_run_versions WHERE id = %s",
                (seed.version_id,),
            )
        conn.rollback()

        with pytest.raises(psycopg.Error, match="(?i)accord: UPDATE/DELETE forbidden"):
            conn.execute(
                "UPDATE payroll_result_lines SET amount = %s WHERE id = %s",
                ("999.99", seed.line_id),
            )
        conn.rollback()

        conn.execute("BEGIN")
        conn.execute("SET LOCAL accord.allow_immutable_ddl = 'on'")
        conn.execute(
            "UPDATE payroll_run_versions SET engine_version = %s WHERE id = %s",
            ("engine-updated", seed.version_id),
        )
        conn.commit()

        conn.execute("BEGIN")
        conn.execute("SET LOCAL accord.allow_immutable_ddl = 'on'")
        conn.execute(
            "DELETE FROM payroll_result_lines WHERE id = %s",
            (seed.line_id,),
        )
        conn.commit()


def test_payroll_runs_partial_unique_primary_index(
    seeded_payroll_run_db: tuple[str, SeededPayrollRunData],
) -> None:
    database_url, seed = seeded_payroll_run_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(UniqueViolation):
            conn.execute(
                "INSERT INTO payroll_runs "
                "(organization_id, period_id, status) "
                "VALUES (%s, %s, %s)",
                (seed.org_id, seed.period_id, "draft"),
            )
        conn.rollback()

        conn.execute(
            "INSERT INTO payroll_runs "
            "(organization_id, period_id, original_run_id, status) "
            "VALUES (%s, %s, %s, %s)",
            (seed.org_id, seed.period_id, seed.run_id, "draft"),
        )
        conn.commit()
