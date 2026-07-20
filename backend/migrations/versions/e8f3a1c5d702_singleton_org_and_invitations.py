"""Singleton organization index and organization_invitations (ADR 0011).

Revision ID: e8f3a1c5d702
Revises: d7a2e4f6b809
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

revision: str = "e8f3a1c5d702"
down_revision: Union[str, None] = "d7a2e4f6b809"
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
    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT COUNT(*) FROM organizations")).scalar()
    if count is not None and int(count) > 1:
        raise RuntimeError(
            f"Refusing to create singleton organization index: found {count} "
            "organizations rows. Prune to a single organization first. "
            "For local e2e databases named accord_e2e/accord_test, use "
            "scripts/reset_e2e_db.sh --i-understand-this-deletes-data "
            "(prints the exact target and refuses other DB names). "
            "Otherwise delete or merge extra organizations with ops SQL, then re-run upgrade."
        )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_singleton "
        "ON organizations ((true))"
    )

    op.create_table(
        "organization_invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "role IN ("
            "'organization_administrator',"
            "'payroll_preparer',"
            "'payroll_reviewer',"
            "'payroll_approver',"
            "'report_releaser',"
            "'auditor'"
            ")",
            name="ck_organization_invitations_role",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_organization_invitations_org_email_pending "
        "ON organization_invitations (organization_id, email) "
        "WHERE accepted_at IS NULL AND revoked_at IS NULL"
    )
    _apply_forced_rls("organization_invitations")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organization_invitations")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_worker ON organization_invitations")
    op.execute("ALTER TABLE organization_invitations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organization_invitations DISABLE ROW LEVEL SECURITY")
    op.drop_table("organization_invitations")
    op.execute("DROP INDEX IF EXISTS uq_organizations_singleton")
