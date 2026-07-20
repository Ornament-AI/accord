"""Ensure audit_events structured-history columns exist.

Revision ID: c9f2e4a8b013
Revises: b2e7f4a1c093
Create Date: 2026-07-20

``e6a8c4d2f901`` owns the canonical DDL for structured audit history. Some
local/dev databases reached later revisions (through ``b2e7f4a1c093``) without
those columns — Alembic then reported head while ``/api/audit-events`` failed
with ``UndefinedColumnError`` on ``event_kind`` / ``actor_snapshot``.

This forward migration backfills any missing objects idempotently so already-at-
head environments recover on the next ``alembic upgrade head``. Fresh installs
that already applied ``e6a8c4d2f901`` take the no-op path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "c9f2e4a8b013"
down_revision: str | None = "b2e7f4a1c093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "audit_events"


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns(_TABLE)}
    existing_indexes = {index["name"] for index in inspect(bind).get_indexes(_TABLE)}
    existing_checks = {
        constraint["name"] for constraint in inspect(bind).get_check_constraints(_TABLE)
    }

    if "event_kind" not in existing_columns:
        op.add_column(_TABLE, sa.Column("event_kind", sa.Text(), nullable=True))
    if "actor_snapshot" not in existing_columns:
        op.add_column(
            _TABLE,
            sa.Column("actor_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "entity_label" not in existing_columns:
        op.add_column(_TABLE, sa.Column("entity_label", sa.Text(), nullable=True))
    if "before_state" not in existing_columns:
        op.add_column(
            _TABLE,
            sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "after_state" not in existing_columns:
        op.add_column(
            _TABLE,
            sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "metadata" not in existing_columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )
    if "idempotency_key" not in existing_columns:
        op.add_column(_TABLE, sa.Column("idempotency_key", sa.Text(), nullable=True))
    if "changed_count" not in existing_columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "changed_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )

    if "ck_audit_events_event_kind" not in existing_checks:
        op.create_check_constraint(
            "ck_audit_events_event_kind",
            _TABLE,
            "event_kind IS NULL OR event_kind IN ('mutation','access')",
        )
    if "ix_audit_events_org_request_id" not in existing_indexes:
        op.create_index(
            "ix_audit_events_org_request_id",
            _TABLE,
            ["organization_id", "request_id"],
            unique=False,
            postgresql_where=sa.text("request_id IS NOT NULL"),
        )


def downgrade() -> None:
    # Canonical drop path remains ``e6a8c4d2f901``; this revision only backfills.
    pass
