"""Posture hardening: alembic_version revoke, outbox dead-letter columns, FK indexes.

Runtime roles must not rewrite alembic_version (a compromised role could
re-run or skip migrations). Outbox rows that exhaust retries get a
``dead_lettered_at`` marker instead of looping forever, plus ``last_error``
for operator triage. FK/index coverage closes the audit's unindexed-FK
gaps on hot paths.

Revision ID: g3h4i5j6k7l8
Revises: d7f1a3b5c902
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g3h4i5j6k7l8"
down_revision: str | None = "d7f1a3b5c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLES = ("accord_app", "accord_worker")


def upgrade() -> None:
    # Migration bookkeeping is migrator-owned; strip every runtime privilege
    # (SELECT included — version_num reveals the applied-revision set).
    for role in RUNTIME_ROLES:
        op.execute(f"REVOKE ALL ON TABLE alembic_version FROM {role}")

    op.add_column(
        "outbox_events",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Dead-lettered rows never re-enter the claimable set (see
    # services/outbox.claim_batch). Index keeps live-claim scans hot.
    op.create_index(
        "ix_outbox_events_claimable",
        "outbox_events",
        ["occurred_at"],
        postgresql_where=sa.text("processed_at IS NULL AND dead_lettered_at IS NULL"),
    )

    # FK / tenant-scan indexes the audit flagged (IF NOT EXISTS for hosts that
    # created equivalents manually). audit_events/outbox_events org-only scans
    # are already leftmost-covered by their composite indexes — no additions.
    for table, cols, name in (
        ("payroll_run_versions", ["run_id"], "ix_payroll_run_versions_run_id"),
        (
            "payroll_employee_results",
            ["run_version_id"],
            "ix_payroll_employee_results_run_version_id",
        ),
        (
            "payroll_result_lines",
            ["employee_result_id"],
            "ix_payroll_result_lines_employee_result_id",
        ),
        ("payroll_approvals", ["run_id"], "ix_payroll_approvals_run_id"),
        ("payroll_run_inputs", ["run_id"], "ix_payroll_run_inputs_run_id"),
        ("idempotency_keys", ["expires_at"], "ix_idempotency_keys_expires_at"),
        ("organization_memberships", ["user_id"], "ix_organization_memberships_user_id"),
        ("export_artifacts", ["posted_run_id"], "ix_export_artifacts_posted_run_id"),
    ):
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({', '.join(cols)})")


def downgrade() -> None:
    for name in (
        "ix_export_artifacts_posted_run_id",
        "ix_organization_memberships_user_id",
        "ix_idempotency_keys_expires_at",
        "ix_payroll_run_inputs_run_id",
        "ix_payroll_approvals_run_id",
        "ix_payroll_result_lines_employee_result_id",
        "ix_payroll_employee_results_run_version_id",
        "ix_payroll_run_versions_run_id",
        "ix_outbox_events_claimable",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.drop_column("outbox_events", "dead_lettered_at")
    op.drop_column("outbox_events", "last_error")
    # Restore the default-privileges grant (create_roles.sql: DML, not ALL).
    for role in RUNTIME_ROLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE alembic_version TO {role}")
