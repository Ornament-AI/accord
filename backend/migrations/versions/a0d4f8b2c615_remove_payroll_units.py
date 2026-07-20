"""Remove unused payroll_units catalog and posting FK.

Revision ID: a0d4f8b2c615
Revises: f9c2b4e6a813
Create Date: 2026-07-19
"""

from __future__ import annotations

import os
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


LEGACY_DROP_ENV = "ACCORD_ALLOW_LEGACY_DROP"


def _preflight_legacy_guard() -> None:
    """Refuse to discard real payroll-unit data unless explicitly overridden.

    ``employee_posting_versions.payroll_unit_id`` was originally NOT NULL, so
    any posting rows represent real assignments. Set
    ``ACCORD_ALLOW_LEGACY_DROP=1`` to proceed after taking a verified backup
    (see docs/operations.md, "Destructive migrations").
    """
    conn = op.get_bind()
    units = int(conn.execute(sa.text("SELECT COUNT(*) FROM payroll_units")).scalar() or 0)
    refs = int(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM employee_posting_versions WHERE payroll_unit_id IS NOT NULL"
            )
        ).scalar()
        or 0
    )
    if units == 0 and refs == 0:
        return
    if os.environ.get(LEGACY_DROP_ENV) == "1":
        print(
            f"[a0d4f8b2c615] {LEGACY_DROP_ENV}=1 set: irreversibly discarding "
            f"{units} payroll_units row(s) and {refs} posting assignment(s)."
        )
        return
    raise RuntimeError(
        f"Refusing to drop payroll_units: {units} row(s) and {refs} posting "
        "assignment(s) exist and would be irreversibly discarded. Take a "
        "verified backup (see docs/operations.md), then re-run with "
        f"{LEGACY_DROP_ENV}=1 to proceed."
    )


def upgrade() -> None:
    _preflight_legacy_guard()
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
    # Original contract: employee_posting_versions.payroll_unit_id was NOT NULL.
    # With posting rows present we cannot invent assignments, so refuse and
    # direct operators to the pre-migration backup instead of downgrading to a
    # structurally unfaithful (nullable) column.
    conn = op.get_bind()
    posting_rows = int(
        conn.execute(sa.text("SELECT COUNT(*) FROM employee_posting_versions")).scalar() or 0
    )
    if posting_rows > 0:
        raise RuntimeError(
            "Cannot faithfully downgrade a0d4f8b2c615: "
            f"{posting_rows} employee_posting_versions row(s) exist but their "
            "payroll unit assignments were discarded on upgrade (the column was "
            "originally NOT NULL). Restore the pre-migration backup instead."
        )
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

    # Safe because the guard above ensures employee_posting_versions is empty;
    # NOT NULL restores the original schema contract exactly.
    op.add_column(
        "employee_posting_versions",
        sa.Column("payroll_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "employee_posting_versions_payroll_unit_id_fkey",
        "employee_posting_versions",
        "payroll_units",
        ["payroll_unit_id"],
        ["id"],
    )
