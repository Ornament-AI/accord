"""Remove unused payroll_units catalog and posting FK.

Revision ID: a0d4f8b2c615
Revises: f9c2b4e6a813
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

revision: str = "a0d4f8b2c615"
down_revision: Union[str, None] = "f9c2b4e6a813"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apply_forced_rls(table_name: str) -> None:
    for role, policy_name in (
        ("accord_app", "tenant_isolation"),
        ("accord_worker", "tenant_isolation_worker"),
    ):
        sql = rls_policy_sql(table_name, role=role, policy_name=policy_name)
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                op.execute(statement)


def upgrade() -> None:
    op.drop_constraint(
        "employee_posting_versions_payroll_unit_id_fkey",
        "employee_posting_versions",
        type_="foreignkey",
    )
    op.drop_column("employee_posting_versions", "payroll_unit_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payroll_units")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_worker ON payroll_units")
    op.execute("ALTER TABLE payroll_units NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payroll_units DISABLE ROW LEVEL SECURITY")
    op.drop_table("payroll_units")


def downgrade() -> None:
    op.create_table(
        "payroll_units",
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
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("payroll_units")

    op.add_column(
        "employee_posting_versions",
        sa.Column("payroll_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "employee_posting_versions_payroll_unit_id_fkey",
        "employee_posting_versions",
        "payroll_units",
        ["payroll_unit_id"],
        ["id"],
    )
