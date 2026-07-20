"""Remove synthetic codes from offices and payroll units.

Revision ID: d7a2e4f6b809
Revises: c5f1e7a9d204
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a2e4f6b809"
down_revision: str | None = "c5f1e7a9d204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_offices_organization_id_code", "offices", type_="unique")
    op.drop_column("offices", "code")
    op.drop_constraint(
        "uq_payroll_units_organization_id_code",
        "payroll_units",
        type_="unique",
    )
    op.drop_column("payroll_units", "code")


def downgrade() -> None:
    op.add_column("offices", sa.Column("code", sa.Text(), nullable=True))
    op.execute("UPDATE offices SET code = 'OFFICE-' || id::text")
    op.alter_column("offices", "code", nullable=False)
    op.create_unique_constraint(
        "uq_offices_organization_id_code",
        "offices",
        ["organization_id", "code"],
    )

    op.add_column("payroll_units", sa.Column("code", sa.Text(), nullable=True))
    op.execute("UPDATE payroll_units SET code = 'PAYROLL-UNIT-' || id::text")
    op.alter_column("payroll_units", "code", nullable=False)
    op.create_unique_constraint(
        "uq_payroll_units_organization_id_code",
        "payroll_units",
        ["organization_id", "code"],
    )
