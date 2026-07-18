"""Allow employee identity dates and Sevarth ID to be unknown.

Revision ID: f4b7c1d9e205
Revises: b33a3a7b5f84
Create Date: 2026-07-18

Legacy payroll sources do not always contain DOB, DOJ, or a Sevarth ID. Those
values must remain unknown instead of being replaced with fabricated data.
"""

from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "f4b7c1d9e205"
down_revision: Union[str, None] = "b33a3a7b5f84"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.alter_column("employee_profile_versions", "sevarth_id", nullable=True)
    op.alter_column("employee_profile_versions", "date_of_birth", nullable=True)
    op.alter_column("employee_profile_versions", "date_of_joining", nullable=True)
    op.alter_column("employee_pay_versions", "pay_matrix_level", nullable=True)
    op.alter_column("employee_bank_account_versions", "branch", nullable=True)
    op.drop_constraint(
        "ck_employee_profile_versions_gpf_jurisdiction_regime",
        "employee_profile_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_employee_profile_versions_gpf_jurisdiction_regime",
        "employee_profile_versions",
        "retirement_regime = 'gpf' OR gpf_jurisdiction IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_employee_profile_versions_gpf_jurisdiction_regime",
        "employee_profile_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_employee_profile_versions_gpf_jurisdiction_regime",
        "employee_profile_versions",
        "(retirement_regime = 'gpf' AND gpf_jurisdiction IS NOT NULL) OR "
        "(retirement_regime <> 'gpf' AND gpf_jurisdiction IS NULL)",
    )
    op.alter_column("employee_bank_account_versions", "branch", nullable=False)
    op.alter_column("employee_pay_versions", "pay_matrix_level", nullable=False)
    op.alter_column("employee_profile_versions", "date_of_joining", nullable=False)
    op.alter_column("employee_profile_versions", "date_of_birth", nullable=False)
    op.alter_column("employee_profile_versions", "sevarth_id", nullable=False)
