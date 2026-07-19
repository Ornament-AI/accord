"""Phase 5 platform tables: audit, outbox, approvals, jobs, artifacts, webhooks.

Tenant-owned tables (1–5) use forced RLS via the migration. ``webhook_events``
is global (like ``sessions``) with no RLS. Append-only tables attach the
existing ``accord_forbid_update_delete`` trigger; ``outbox_events`` allows
UPDATE for dispatch bookkeeping but forbids DELETE via ``accord_forbid_delete``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlmodel import Field

from app.models.base import (
    OrganizationOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)
from app.models.identity import (
    _created_at_field,
    _id_field,
    _organization_id_field,
    _updated_at_field,
)


class AuditEvent(UUIDPrimaryKeyMixin, OrganizationOwnedMixin, table=True):
    """Append-only audit trail row (ADR 0009)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        # B-tree supports backward scans; omit DESC ops so alembic check stays clean.
        Index(
            "ix_audit_events_org_entity_created_at",
            "organization_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index(
            "ix_audit_events_org_created_at",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_audit_events_org_request_id",
            "organization_id",
            "request_id",
            postgresql_where=text("request_id IS NOT NULL"),
        ),
        CheckConstraint(
            "event_kind IS NULL OR event_kind IN ('mutation','access')",
            name="ck_audit_events_event_kind",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    actor_user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=True,
        ),
    )
    request_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    command: str = Field(sa_column=Column(Text, nullable=False))
    entity_type: str = Field(sa_column=Column(Text, nullable=False))
    entity_id: uuid.UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), nullable=False),
    )
    event_kind: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    actor_snapshot: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    entity_label: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    before_state: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    after_state: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    idempotency_key: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    changed_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    # Retained for compatibility with immutable legacy rows and older consumers.
    summary: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
    )


class OutboxEvent(UUIDPrimaryKeyMixin, OrganizationOwnedMixin, table=True):
    """Transactional outbox row; UPDATE allowed, DELETE forbidden (ADR 0009)."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_unprocessed",
            "organization_id",
            "occurred_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

    id: uuid.UUID = _id_field()
    organization_id: uuid.UUID = _organization_id_field()
    event_type: str = Field(sa_column=Column(Text, nullable=False))
    payload: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
    )
    occurred_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    attempts: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
        ),
    )
    locked_by: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    locked_until: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class PayrollApproval(UUIDPrimaryKeyMixin, OrganizationOwnedMixin, table=True):
    """Append-only payroll workflow approval / action event (ADR 0008).

    Maker/checker (approver ≠ submitter) is a cross-row rule enforced in the
    service layer, not as a database CHECK on this table.
    """

    __tablename__ = "payroll_approvals"
    __table_args__ = (
        CheckConstraint(
            "action IN ('submit','withdraw','approve','reject','post','reverse')",
            name="ck_payroll_approvals_action",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    run_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payroll_runs.id"),
            nullable=False,
        ),
    )
    run_version_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payroll_run_versions.id"),
            nullable=False,
        ),
    )
    content_hash: str = Field(sa_column=Column(Text, nullable=False))
    action: str = Field(sa_column=Column(Text, nullable=False))
    actor_user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
        ),
    )
    reason: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )


class Job(UUIDPrimaryKeyMixin, OrganizationOwnedMixin, table=True):
    """Durable job queue row; column names match ``app.jobs.protocol.Job``."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','dead_letter','cancelled')",
            name="ck_jobs_status",
        ),
        Index(
            "jobs_org_type_dedupe_inflight_uidx",
            "organization_id",
            "job_type",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('queued','running') AND dedupe_key IS NOT NULL"),
        ),
        Index(
            "ix_jobs_status_available_at",
            "status",
            "available_at",
            postgresql_include=["organization_id"],
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    job_type: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(
        default="queued",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'queued'"),
        ),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    result: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    dedupe_key: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    attempt_count: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
        ),
    )
    max_attempts: int = Field(
        default=5,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("5"),
        ),
    )
    available_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    lease_owner: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    lease_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    heartbeat_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    cancel_requested: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    started_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_error: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    created_by: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=True,
        ),
    )


class ExportArtifact(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Export artifact metadata for object-storage-backed downloads (ADR 0010)."""

    __tablename__ = "export_artifacts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','uploaded','finalized','expired','deleted')",
            name="ck_export_artifacts_status",
        ),
        UniqueConstraint("object_key", name="uq_export_artifacts_object_key"),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    posted_run_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payroll_runs.id"),
            nullable=True,
        ),
    )
    report_type: str = Field(sa_column=Column(Text, nullable=False))
    template_version: str = Field(sa_column=Column(Text, nullable=False))
    engine_version: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    object_key: str = Field(sa_column=Column(Text, nullable=False))
    checksum_sha256: str = Field(sa_column=Column(Text, nullable=False))
    content_type: str = Field(sa_column=Column(Text, nullable=False))
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    object_version: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    status: str = Field(
        default="pending",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'pending'"),
        ),
    )
    requested_by: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
        ),
    )
    retention_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class WebhookEvent(UUIDPrimaryKeyMixin, table=True):
    """Global durable webhook dedup (not tenant-owned; no RLS)."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_webhook_events_event_id"),)

    id: uuid.UUID = _id_field()
    provider: str = Field(
        default="workos",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'workos'"),
        ),
    )
    event_id: str = Field(sa_column=Column(Text, nullable=False))
    event_type: str = Field(sa_column=Column(Text, nullable=False))
    received_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    payload_digest: str = Field(sa_column=Column(Text, nullable=False))


# Re-export typing helper for callers that annotate JSON payloads.
AnyDict = dict[str, Any]
