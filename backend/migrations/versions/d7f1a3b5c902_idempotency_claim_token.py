"""Idempotency claim token for conditional terminal writes.

Revision ID: d7f1a3b5c902
Revises: c3d9e5f2a714
Create Date: 2026-09-24

A stale ``in_progress`` row is reclaimable after ``_CLAIM_STALE_AFTER`` —
necessary when a claimant crashed mid-command, but unsafe when the command is
legitimately slow: the second claimant re-executes and the first's terminal
write can clobber its result. ``claim_token`` is minted per claim; terminal
writes are conditioned on it, so a displaced claimant's late write no-ops.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "d7f1a3b5c902"
down_revision: str | None = "c3d9e5f2a714"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "idempotency_keys",
        sa.Column("claim_token", PG_UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("idempotency_keys", "claim_token")
