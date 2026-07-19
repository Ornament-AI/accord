"""Extend audit history with immutable structured event details.

Revision ID: e6a8c4d2f901
Revises: f4b7c1d9e205
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6a8c4d2f901"
down_revision: str | None = "f4b7c1d9e205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("event_kind", sa.Text(), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("actor_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("audit_events", sa.Column("entity_label", sa.Text(), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("audit_events", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("changed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_audit_events_event_kind",
        "audit_events",
        "event_kind IS NULL OR event_kind IN ('mutation','access')",
    )
    op.create_index(
        "ix_audit_events_org_request_id",
        "audit_events",
        ["organization_id", "request_id"],
        unique=False,
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_org_request_id", table_name="audit_events")
    op.drop_constraint("ck_audit_events_event_kind", "audit_events", type_="check")
    op.drop_column("audit_events", "changed_count")
    op.drop_column("audit_events", "idempotency_key")
    op.drop_column("audit_events", "metadata")
    op.drop_column("audit_events", "after_state")
    op.drop_column("audit_events", "before_state")
    op.drop_column("audit_events", "entity_label")
    op.drop_column("audit_events", "actor_snapshot")
    op.drop_column("audit_events", "event_kind")
