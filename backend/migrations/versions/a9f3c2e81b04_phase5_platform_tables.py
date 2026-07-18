"""Phase 5 platform tables.

Revision ID: a9f3c2e81b04
Revises: 021faa7dd776
Create Date: 2026-07-18

Creates audit_events, outbox_events, payroll_approvals, jobs, export_artifacts,
and webhook_events (ADR-0008 / ADR-0009 / ADR-0010). Applies forced RLS
(accord_app + accord_worker) on tenant-owned tables 1–5. Attaches append-only
triggers (reusing ``accord_forbid_update_delete``) and a DELETE-only guard
(``accord_forbid_delete``) on outbox_events. Applies ADR-0009 GRANT/REVOKE on
audit_events and outbox_events. ``webhook_events`` is global with no RLS.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

# revision identifiers, used by Alembic.
revision: str = "a9f3c2e81b04"
down_revision: Union[str, None] = "021faa7dd776"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = (
    "audit_events",
    "payroll_approvals",
)


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


def _apply_audit_outbox_privileges() -> None:
    """ADR-0009: narrow DML on audit (append-only) and outbox (no DELETE)."""
    op.execute("REVOKE ALL ON TABLE audit_events FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON TABLE audit_events TO accord_app, accord_worker")
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM accord_app, accord_worker"
    )

    op.execute("REVOKE ALL ON TABLE outbox_events FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE outbox_events TO accord_app, accord_worker")
    op.execute("REVOKE DELETE, TRUNCATE ON TABLE outbox_events FROM accord_app, accord_worker")


def _attach_append_only_triggers() -> None:
    """Reuse ``accord_forbid_update_delete`` from Phase 4 (do not recreate)."""
    for table_name in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_forbid_update_delete
              BEFORE UPDATE OR DELETE ON {table_name}
              FOR EACH ROW
              EXECUTE FUNCTION accord_forbid_update_delete();
            """
        )


def _create_outbox_delete_guard() -> None:
    """Forbid DELETE on outbox_events; UPDATE remains allowed for dispatch."""
    op.execute(
        """
        -- Escape hatch matches accord_forbid_update_delete:
        -- SET LOCAL accord.allow_immutable_ddl = 'on' inside a controlled txn.
        CREATE OR REPLACE FUNCTION accord_forbid_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $func$
        BEGIN
          IF current_setting('accord.allow_immutable_ddl', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION
            'accord: DELETE forbidden on table %',
            TG_TABLE_NAME
            USING ERRCODE = 'integrity_constraint_violation';
        END;
        $func$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_outbox_events_forbid_delete
          BEFORE DELETE ON outbox_events
          FOR EACH ROW
          EXECUTE FUNCTION accord_forbid_delete();
        """
    )


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("audit_events")
    # Column order matches ADR/task intent; Postgres can scan B-tree backward
    # for created_at DESC consumers without encoding DESC in the index DDL
    # (keeps alembic check aligned with SQLModel metadata).
    op.create_index(
        "ix_audit_events_org_entity_created_at",
        "audit_events",
        ["organization_id", "entity_type", "entity_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_org_created_at",
        "audit_events",
        ["organization_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("outbox_events")
    op.create_index(
        "ix_outbox_events_unprocessed",
        "outbox_events",
        ["organization_id", "occurred_at"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    op.create_table(
        "payroll_approvals",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("run_version_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "action IN ('submit','withdraw','approve','reject','post','reverse')",
            name="ck_payroll_approvals_action",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["payroll_runs.id"]),
        sa.ForeignKeyConstraint(["run_version_id"], ["payroll_run_versions.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("payroll_approvals")

    op.create_table(
        "jobs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','dead_letter','cancelled')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("jobs")
    op.create_index(
        "jobs_org_type_dedupe_inflight_uidx",
        "jobs",
        ["organization_id", "job_type", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running') AND dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_jobs_status_available_at",
        "jobs",
        ["status", "available_at"],
        unique=False,
        postgresql_include=["organization_id"],
    )

    op.create_table(
        "export_artifacts",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
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
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("posted_run_id", sa.UUID(), nullable=True),
        sa.Column("report_type", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_version", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','uploaded','finalized','expired','deleted')",
            name="ck_export_artifacts_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["posted_run_id"], ["payroll_runs.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_export_artifacts_object_key"),
    )
    _apply_forced_rls("export_artifacts")

    op.create_table(
        "webhook_events",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.Text(),
            server_default=sa.text("'workos'"),
            nullable=False,
        ),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_digest", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_webhook_events_event_id"),
    )

    _apply_audit_outbox_privileges()
    _attach_append_only_triggers()
    _create_outbox_delete_guard()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_outbox_events_forbid_delete ON outbox_events")
    for table_name in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_forbid_update_delete ON {table_name}")
    # Do NOT drop accord_forbid_update_delete — owned by Phase 4 (021faa7dd776).
    op.execute("DROP FUNCTION IF EXISTS accord_forbid_delete()")

    op.drop_table("webhook_events")
    op.drop_table("export_artifacts")
    op.drop_index("ix_jobs_status_available_at", table_name="jobs")
    op.drop_index("jobs_org_type_dedupe_inflight_uidx", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("payroll_approvals")
    op.drop_index("ix_outbox_events_unprocessed", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_events_org_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_org_entity_created_at", table_name="audit_events")
    op.drop_table("audit_events")
