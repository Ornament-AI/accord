"""Remove configurable organization settings.

Revision ID: d1c7a2e9f4b6
Revises: f4b7c1d9e205
Create Date: 2026-07-18

Accord is an India-only payroll application. Locale, timezone, currency, and
financial-year conventions are product invariants rather than tenant data, so
the settings table and its mutable API have been retired.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

revision: str = "d1c7a2e9f4b6"
down_revision: Union[str, None] = "f4b7c1d9e205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apply_forced_rls(table_name: str) -> None:
    for role, policy_name in (
        ("accord_app", "tenant_isolation"),
        ("accord_worker", "tenant_isolation_worker"),
    ):
        sql = rls_policy_sql(table_name, role=role, policy_name=policy_name)
        for statement in sql.split(";"):
            if statement := statement.strip():
                op.execute(statement)


def upgrade() -> None:
    op.drop_table("organization_settings")


def downgrade() -> None:
    op.create_table(
        "organization_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locale", sa.Text(), server_default=sa.text("'en-IN'"), nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_organization_settings_organization_id",
        ),
        sa.CheckConstraint(
            "financial_year_start_month BETWEEN 1 AND 12",
            name="ck_organization_settings_financial_year_start_month",
        ),
    )
    op.execute(
        sa.text("INSERT INTO organization_settings (organization_id) SELECT id FROM organizations")
    )
    _apply_forced_rls("organization_settings")
