"""Upgrade coverage for canonical pay-bill export metadata."""

from __future__ import annotations

import uuid

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

PREVIOUS_REVISION = "f2a7c9d4e601"


def test_canonical_export_metadata_upgrade_preserves_rows_and_backfills_catalog(
    scratch_db: str,
) -> None:
    up_previous = run_alembic(scratch_db, "upgrade", PREVIOUS_REVISION)
    assert up_previous.returncode == 0, diag("upgrade previous", up_previous)

    org_id = uuid.uuid4()
    post_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    office_id = uuid.uuid4()
    posting_version_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, 'Legacy Org', %s)",
            (org_id, f"legacy-{org_id.hex[:8]}"),
        )
        conn.execute(
            'INSERT INTO posts (id, organization_id, designation, "class") '
            "VALUES (%s, %s, 'Accountant', 'Class III')",
            (post_id, org_id),
        )
        conn.execute(
            "INSERT INTO offices (id, organization_id, name, jurisdiction) "
            "VALUES (%s, %s, 'Head Office', 'mumbai')",
            (office_id, org_id),
        )
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) "
            "VALUES (%s, %s, 'LEGACY-1')",
            (employee_id, org_id),
        )
        conn.execute(
            "INSERT INTO employee_posting_versions "
            "(id, organization_id, header_id, validity, office_id, post_id, created_by) "
            "VALUES (%s, %s, %s, daterange('2026-01-01', NULL, '[)'), %s, %s, %s)",
            (posting_version_id, org_id, employee_id, office_id, post_id, actor_id),
        )
        conn.execute(
            "INSERT INTO pay_components "
            "(organization_id, code, name, classification, is_standard) "
            "VALUES (%s, 'CUSTOM', 'Custom', 'earning', false)",
            (org_id,),
        )
        conn.execute(
            "INSERT INTO pay_components "
            "(organization_id, code, name, classification, is_standard) "
            "VALUES (%s, 'BASIC', 'Basic Pay', 'earning', true), "
            "(%s, 'INCOME_TAX', 'Income Tax', 'treasury_deduction', true)",
            (org_id, org_id),
        )
        conn.commit()

    up_head = run_alembic(scratch_db, "upgrade", "head")
    assert up_head.returncode == 0, diag("upgrade head", up_head)

    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        post = conn.execute(
            "SELECT sanctioned_strength, vacant_count, pay_scale, display_order, "
            "pay_bill_heading "
            "FROM posts WHERE id = %s",
            (post_id,),
        ).fetchone()
        columns = dict(
            conn.execute(
                "SELECT code, register_column FROM pay_components "
                "WHERE organization_id = %s AND code IN ('BASIC', 'INCOME_TAX', 'CUSTOM')",
                (org_id,),
            ).fetchall()
        )
        pay_bill_post_id = conn.execute(
            "SELECT pay_bill_post_id FROM employee_posting_versions WHERE id = %s",
            (posting_version_id,),
        ).fetchone()[0]
        pay_bill_fk = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'fk_employee_posting_versions_org_pay_bill_post'"
        ).fetchone()[0]

    assert post == (None, None, None, None, None)
    assert pay_bill_post_id == post_id
    assert "FOREIGN KEY (organization_id, pay_bill_post_id)" in pay_bill_fk
    assert "REFERENCES posts(organization_id, id)" in pay_bill_fk
    assert columns == {
        "BASIC": "basic_pay",
        "CUSTOM": None,
        "INCOME_TAX": "income_tax",
    }
