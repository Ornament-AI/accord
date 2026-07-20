"""Remove payroll run types.

Revision ID: c5f1e7a9d204
Revises: a4c8d9e2f310
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f1e7a9d204"
down_revision: str | None = "a4c8d9e2f310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Supplemental runs were never part of the source payroll workflow. Refuse
    # to discard ambiguous duplicate primary runs; an operator must resolve
    # them explicitly before this migration proceeds.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
              FROM payroll_runs
             WHERE original_run_id IS NULL
             GROUP BY organization_id, period_id
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION
              'Cannot remove payroll run types while duplicate primary runs exist';
          END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_payroll_runs_org_period_run_type_regular", table_name="payroll_runs")
    op.drop_constraint("ck_payroll_runs_run_type", "payroll_runs", type_="check")
    op.drop_column("payroll_runs", "run_type")
    op.create_index(
        "ux_payroll_runs_org_period_primary",
        "payroll_runs",
        ["organization_id", "period_id"],
        unique=True,
        postgresql_where=sa.text("original_run_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_payroll_runs_org_period_primary", table_name="payroll_runs")
    op.add_column(
        "payroll_runs",
        sa.Column("run_type", sa.Text(), server_default=sa.text("'regular'"), nullable=False),
    )
    op.execute(
        "UPDATE payroll_runs SET run_type = 'reversal' WHERE original_run_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_payroll_runs_run_type",
        "payroll_runs",
        "run_type IN ('regular','supplemental','reversal')",
    )
    op.create_index(
        "ix_payroll_runs_org_period_run_type_regular",
        "payroll_runs",
        ["organization_id", "period_id", "run_type"],
        unique=True,
        postgresql_where=sa.text("run_type = 'regular'"),
    )
