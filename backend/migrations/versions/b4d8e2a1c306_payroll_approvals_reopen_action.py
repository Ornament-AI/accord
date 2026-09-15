"""Allow 'reopen' in payroll_approvals action check.

Revision ID: b4d8e2a1c306
Revises: a7d3e5f9b102
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b4d8e2a1c306"
down_revision: str | None = "a7d3e5f9b102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "action IN ('submit','withdraw','approve','reject','post','reverse')"
)
_NEW = (
    "action IN ('submit','withdraw','approve','reject','post','reverse','reopen')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_payroll_approvals_action", "payroll_approvals", type_="check"
    )
    op.create_check_constraint(
        "ck_payroll_approvals_action", "payroll_approvals", _NEW
    )


def downgrade() -> None:
    # If 'reopen' approval rows exist the restored constraint will fail —
    # intentionally loud rather than silently destroying audit history.
    op.drop_constraint(
        "ck_payroll_approvals_action", "payroll_approvals", type_="check"
    )
    op.create_check_constraint(
        "ck_payroll_approvals_action", "payroll_approvals", _OLD
    )
