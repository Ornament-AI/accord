"""Add roster CHECK bounds and employee_id index to payroll_run_employees.

Revision ID: b2e7f4a1c093
Revises: a0d4f8b2c615
Create Date: 2026-07-20

These objects were originally (incorrectly) folded into the already-merged
``a4c8d9e2f310`` roster migration. Environments that had applied ``a4c8d9e2f310``
before that edit would never receive the new constraints/index, so they are
promoted here into a standalone forward migration.

Adds:
* ``ck_payroll_run_employees_transport_amount`` — transport amount is non-negative.
* ``ck_payroll_run_employees_da_difference`` — da_difference stays signed (it may
  recover overpaid dearness allowance from a prior period) but is bounded.
* ``ix_payroll_run_employees_employee_id`` — the composite unique
  (org, run, employee) cannot serve employee-only FK lookups (e.g. employee
  deletion), so employee_id is indexed directly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b2e7f4a1c093"
down_revision: str | None = "a0d4f8b2c615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "payroll_run_employees"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_payroll_run_employees_transport_amount",
        _TABLE,
        "transport_amount IS NULL OR transport_amount >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_run_employees_da_difference",
        _TABLE,
        "da_difference IS NULL OR (da_difference >= -99999999.99 AND da_difference <= 99999999.99)",
    )
    op.create_index(
        "ix_payroll_run_employees_employee_id",
        _TABLE,
        ["employee_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_run_employees_employee_id", table_name=_TABLE)
    op.drop_constraint(
        "ck_payroll_run_employees_da_difference",
        _TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_run_employees_transport_amount",
        _TABLE,
        type_="check",
    )
