"""Add the editable employee roster for payroll runs.

Revision ID: a4c8d9e2f310
Revises: e2b9d47c1503
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.base import rls_policy_sql

revision: str = "a4c8d9e2f310"
down_revision: str | None = "e2b9d47c1503"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _apply_forced_rls(table_name: str) -> None:
    for role, policy_name in (
        ("accord_app", "tenant_isolation"),
        ("accord_worker", "tenant_isolation_worker"),
    ):
        for statement in rls_policy_sql(table_name, role=role, policy_name=policy_name).split(";"):
            if statement.strip():
                op.execute(statement.strip())


def upgrade() -> None:
    op.add_column(
        "payroll_runs",
        sa.Column(
            "roster_initialized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_table(
        "payroll_run_employees",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("payable_days", sa.Numeric(5, 2), nullable=False),
        sa.Column("da_percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("da_difference", sa.Numeric(12, 2), nullable=True),
        sa.Column("hra_percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("transport_amount", sa.Numeric(12, 2), nullable=True),
        sa.CheckConstraint(
            "payable_days >= 0 AND payable_days <= 31",
            name="ck_payroll_run_employees_payable_days",
        ),
        sa.CheckConstraint(
            "da_percent IS NULL OR (da_percent >= 0 AND da_percent <= 1000)",
            name="ck_payroll_run_employees_da_percent",
        ),
        sa.CheckConstraint(
            "hra_percent IS NULL OR (hra_percent >= 0 AND hra_percent <= 1000)",
            name="ck_payroll_run_employees_hra_percent",
        ),
        sa.CheckConstraint(
            "transport_amount IS NULL OR transport_amount >= 0",
            name="ck_payroll_run_employees_transport_amount",
        ),
        # da_difference is intentionally signed: it is a gross adjustment that
        # may recover overpaid dearness allowance from a prior period.
        sa.CheckConstraint(
            "da_difference IS NULL OR (da_difference >= -99999999.99 AND da_difference <= 99999999.99)",
            name="ck_payroll_run_employees_da_difference",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["payroll_runs.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "run_id",
            "employee_id",
            name="uq_payroll_run_employees_org_run_employee",
        ),
    )
    # The composite unique (org, run, employee) cannot serve employee-only
    # FK lookups (e.g. employee deletion); index employee_id directly.
    op.create_index(
        "ix_payroll_run_employees_employee_id",
        "payroll_run_employees",
        ["employee_id"],
    )
    _apply_forced_rls("payroll_run_employees")


def downgrade() -> None:
    op.drop_table("payroll_run_employees")
    op.drop_column("payroll_runs", "roster_initialized")
