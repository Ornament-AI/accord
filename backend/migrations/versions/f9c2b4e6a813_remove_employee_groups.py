"""Remove unused employee_groups catalog and posting FK.

Revision ID: f9c2b4e6a813
Revises: e8f3a1c5d702
Create Date: 2026-07-19
"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

revision: str = "f9c2b4e6a813"
down_revision: Union[str, None] = "e8f3a1c5d702"
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
    """Refuse to discard real employee-group data unless explicitly overridden.

    Set ``ACCORD_ALLOW_LEGACY_DROP=1`` to proceed after taking a verified
    backup (see docs/operations.md, "Destructive migrations").
    """
    conn = op.get_bind()
    groups = int(conn.execute(sa.text("SELECT COUNT(*) FROM employee_groups")).scalar() or 0)
    refs = int(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM employee_posting_versions WHERE employee_group_id IS NOT NULL"
            )
        ).scalar()
        or 0
    )
    if groups == 0 and refs == 0:
        return
    if os.environ.get(LEGACY_DROP_ENV) == "1":
        print(
            f"[f9c2b4e6a813] {LEGACY_DROP_ENV}=1 set: irreversibly discarding "
            f"{groups} employee_groups row(s) and {refs} posting reference(s)."
        )
        return
    raise RuntimeError(
        f"Refusing to drop employee_groups: {groups} row(s) and {refs} posting "
        "reference(s) exist and would be irreversibly discarded. Take a verified "
        "backup (see docs/operations.md), then re-run with "
        f"{LEGACY_DROP_ENV}=1 to proceed."
    )


def upgrade() -> None:
    _preflight_legacy_guard()
    op.drop_constraint(
        "employee_posting_versions_employee_group_id_fkey",
        "employee_posting_versions",
        type_="foreignkey",
    )
    op.drop_column("employee_posting_versions", "employee_group_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON employee_groups")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_worker ON employee_groups")
    op.execute("ALTER TABLE employee_groups NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_groups DISABLE ROW LEVEL SECURITY")
    op.drop_table("employee_groups")


def downgrade() -> None:
    op.create_table(
        "employee_groups",
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
        sa.Column("code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_employee_groups_organization_id_code",
        ),
    )
    _apply_forced_rls("employee_groups")

    op.add_column(
        "employee_posting_versions",
        sa.Column("employee_group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "employee_posting_versions_employee_group_id_fkey",
        "employee_posting_versions",
        "employee_groups",
        ["employee_group_id"],
        ["id"],
    )
