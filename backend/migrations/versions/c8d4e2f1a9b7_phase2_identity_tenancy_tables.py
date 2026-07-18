"""Phase 2 identity and tenancy tables.

Revision ID: c8d4e2f1a9b7
Revises: b7e3c1a90f24
Create Date: 2026-07-17

Creates users, organizations, tenant-owned membership/settings/idempotency
tables, and sessions. Enables the ``citext`` extension so ``users.email`` has
case-insensitive uniqueness (``CITEXT`` + unique constraint).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

# revision identifiers, used by Alembic.
revision: str = "c8d4e2f1a9b7"
down_revision: Union[str, None] = "b7e3c1a90f24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apply_forced_rls(table_name: str) -> None:
    """Enable forced RLS for ``accord_app`` and ``accord_worker``.

    ``rls_policy_sql`` returns multiple statements; asyncpg rejects multi-command
    prepared statements, so each statement is executed separately.
    """
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
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workos_user_id", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workos_user_id", name="uq_users_workos_user_id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("workos_organization_id", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        sa.UniqueConstraint(
            "workos_organization_id",
            name="uq_organizations_workos_organization_id",
        ),
    )

    op.create_table(
        "organization_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_organization_id_user_id",
        ),
        sa.CheckConstraint(
            "role IN ("
            "'organization_administrator',"
            "'payroll_preparer',"
            "'payroll_reviewer',"
            "'payroll_approver',"
            "'report_releaser',"
            "'auditor'"
            ")",
            name="ck_organization_memberships_role",
        ),
    )
    _apply_forced_rls("organization_memberships")

    op.create_table(
        "organization_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "locale",
            sa.Text(),
            server_default=sa.text("'en-IN'"),
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.Text(),
            server_default=sa.text("'Asia/Kolkata'"),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.CHAR(length=3),
            server_default=sa.text("'INR'"),
            nullable=False,
        ),
        sa.Column(
            "financial_year_start_month",
            sa.Integer(),
            server_default=sa.text("4"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_organization_settings_organization_id",
        ),
        sa.CheckConstraint(
            "financial_year_start_month BETWEEN 1 AND 12",
            name="ck_organization_settings_financial_year_start_month",
        ),
    )
    _apply_forced_rls("organization_settings")

    op.create_table(
        "idempotency_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.UniqueConstraint(
            "organization_id",
            "key",
            name="uq_idempotency_keys_organization_id_key",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed')",
            name="ck_idempotency_keys_status",
        ),
    )
    _apply_forced_rls("idempotency_keys")

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent_hash", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["active_organization_id"],
            ["organizations.id"],
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_index(
        "ix_sessions_active_id",
        "sessions",
        ["id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_active_id", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("idempotency_keys")
    op.drop_table("organization_settings")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS citext")
