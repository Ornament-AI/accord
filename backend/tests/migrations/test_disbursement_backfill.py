"""Upgrade coverage for legacy payroll snapshots and component catalogs."""

from __future__ import annotations

import uuid

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

PREVIOUS_REVISION = "f4b7c1d9e205"


def test_disbursement_migrations_backfill_existing_rows(scratch_db: str) -> None:
    up_previous = run_alembic(scratch_db, "upgrade", PREVIOUS_REVISION)
    assert up_previous.returncode == 0, diag("upgrade previous", up_previous)

    org_id = uuid.uuid4()
    period_id = uuid.uuid4()
    run_id = uuid.uuid4()
    version_id = uuid.uuid4()
    employee_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, 'Legacy Org', %s)",
            (org_id, f"legacy-{org_id.hex[:8]}"),
        )
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) VALUES (%s, %s, 'E001')",
            (employee_id, org_id),
        )
        conn.execute(
            "INSERT INTO payroll_periods "
            "(id, organization_id, period_year, period_month) VALUES (%s, %s, 2026, 6)",
            (period_id, org_id),
        )
        conn.execute(
            "INSERT INTO payroll_runs (id, organization_id, period_id) VALUES (%s, %s, %s)",
            (run_id, org_id, period_id),
        )
        conn.execute(
            "INSERT INTO payroll_run_versions "
            "(id, organization_id, run_id, version_number, engine_version, content_hash, "
            "calculated_at, calculated_by, inputs_snapshot, totals) "
            "VALUES (%s, %s, %s, 1, 'accord-engine/1.0.0', %s, now(), %s, "
            "'{}'::jsonb, '{\"net_payable\": \"123.45\"}'::jsonb)",
            (version_id, org_id, run_id, "0" * 64, uuid.uuid4()),
        )
        conn.execute(
            "INSERT INTO payroll_employee_results "
            "(organization_id, run_version_id, employee_id, employee_number, earnings_total, "
            "employer_contribution_total, gross_total, deductions_total, net_payable) "
            "VALUES (%s, %s, %s, 'E001', 150, 0, 150, 26.55, 123.45)",
            (org_id, version_id, employee_id),
        )
        for code, classification in (
            ("NPS_EMPLOYER_TRANSFER", "ag_deduction"),
            ("EPF_EMPLOYER", "employer_contribution"),
            ("EPF_EMPLOYER_TRANSFER", "ag_deduction"),
        ):
            conn.execute(
                "INSERT INTO pay_components (organization_id, code, name, classification) "
                "VALUES (%s, %s, %s, %s)",
                (org_id, code, code, classification),
            )
        conn.commit()

    up_head = run_alembic(scratch_db, "upgrade", "head")
    assert up_head.returncode == 0, diag("upgrade head", up_head)

    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        result_row = conn.execute(
            "SELECT offbill_employer_remittance, disbursement "
            "FROM payroll_employee_results WHERE run_version_id = %s",
            (version_id,),
        ).fetchone()
        totals = conn.execute(
            "SELECT totals FROM payroll_run_versions WHERE id = %s", (version_id,)
        ).fetchone()[0]
        components = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT code, employer_transfer, transfer_of "
                "FROM pay_components WHERE organization_id = %s",
                (org_id,),
            ).fetchall()
        }

    assert result_row is not None
    assert str(result_row[0]) == "0.00"
    assert str(result_row[1]) == "123.45"
    assert totals["offbill_employer_remittance"] == "0.00"
    assert totals["disbursement"] == "123.45"
    assert components["NPS_EMPLOYER_TRANSFER"] == (True, None)
    assert components["EPF_EMPLOYER_TRANSFER"] == (True, "EPF_EMPLOYER")
