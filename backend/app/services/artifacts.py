"""Export artifact lifecycle service (ADR 0010).

Consistency protocol: INSERT pending intent → storage.put → finalize
(uploaded → finalized). This module exposes org-scoped orphan reconciliation
and retention-expiry service functions; the ``artifacts.maintenance`` worker
job (``app.jobs.handlers``) runs them hourly per organization.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AccordError, ConflictError, NotFoundError
from app.models.platform import ExportArtifact
from app.services.audit_events import entity_snapshot, write_access_event, write_mutation_event
from app.services.outbox import emit_event
from app.schemas.artifacts import ArtifactListPage, ArtifactResponse
from app.schemas.pagination import page_count, page_offset
from app.storage.protocol import (
    ChecksumMismatch,
    ObjectStorage,
    ObjectStorageError,
    build_object_key,
)
from app.tenancy import bind_tenant_context

logger = structlog.get_logger(__name__)


class ArtifactNotFoundError(NotFoundError):
    error_code = "artifact_not_found"

    def __init__(self, message: str = "Export artifact not found."):
        super().__init__(message)


class ArtifactNotFinalizedError(ConflictError):
    error_code = "artifact_not_finalized"

    def __init__(self, message: str = "Export artifact is not finalized."):
        super().__init__(message)


class ArtifactExpiredError(AccordError):
    status_code = 410
    error_code = "artifact_expired"

    def __init__(self, message: str = "Export artifact has expired."):
        super().__init__(message)


class ArtifactStorageError(AccordError):
    """Storage put failed after the pending intent row was committed."""

    status_code = 503
    error_code = "artifact_storage_error"

    def __init__(self, message: str = "Object storage upload failed.", details: dict | None = None):
        super().__init__(message, details=details)


@dataclass(frozen=True, slots=True)
class OrphanReconcileCounts:
    finalized: int
    deleted: int
    # Rows whose stored object bytes no longer match the recorded checksum —
    # left ``pending`` for investigation, never finalized or deleted here.
    checksum_mismatch: int = 0


@dataclass(frozen=True, slots=True)
class ArtifactDownload:
    """Metadata plus async body chunks for ``StreamingResponse``."""

    artifact: ExportArtifact
    chunks: AsyncIterator[bytes]


async def _rebind_tenant(
    session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
) -> None:
    """Begin a transaction and re-bind SET LOCAL GUCs after a prior commit."""
    if not session.in_transaction():
        await session.begin()
    await bind_tenant_context(
        session,
        organization_id=organization_id,
        user_id=user_id,
    )


async def create_artifact(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    organization_id: UUID,
    report_type: str,
    template_version: str,
    content: bytes,
    content_type: str,
    requested_by: UUID,
    posted_run_id: UUID | None = None,
    variant_key: str | None = None,
    engine_version: str | None = None,
    retention_days: int | None = None,
) -> ExportArtifact:
    """Create an artifact via pending → upload → finalized (ADR 0010 §6).

    Checksum and size are computed up front so the pending INSERT satisfies
    NOT NULL columns. On storage failure the row remains ``pending`` (orphan
    candidate) and ``ArtifactStorageError`` is raised.
    """
    checksum = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)
    object_key = build_object_key(organization_id)
    retention_expires_at: datetime | None = None
    if retention_days is not None:
        retention_expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

    await _rebind_tenant(
        session,
        organization_id=organization_id,
        user_id=requested_by,
    )
    artifact = ExportArtifact(
        organization_id=organization_id,
        posted_run_id=posted_run_id,
        report_type=report_type,
        variant_key=variant_key,
        template_version=template_version,
        engine_version=engine_version,
        object_key=object_key,
        checksum_sha256=checksum,
        content_type=content_type,
        size_bytes=size_bytes,
        status="pending",
        requested_by=requested_by,
        retention_expires_at=retention_expires_at,
    )
    session.add(artifact)
    await session.commit()
    artifact_id = artifact.id

    try:
        meta = await storage.put(
            object_key,
            content,
            content_type,
            expected_checksum_sha256=checksum,
        )
    except ObjectStorageError as exc:
        raise ArtifactStorageError(
            "Object storage upload failed; artifact left pending for reconciliation.",
            details={"artifact_id": str(artifact_id), "object_key": object_key},
        ) from exc

    await _rebind_tenant(
        session,
        organization_id=organization_id,
        user_id=requested_by,
    )
    row = await session.get(ExportArtifact, artifact_id)
    if row is None:
        raise ArtifactNotFoundError("Export artifact disappeared after upload.")
    row.status = "uploaded"
    row.checksum_sha256 = meta.checksum_sha256
    row.size_bytes = meta.size_bytes
    row.content_type = meta.content_type
    row.object_version = meta.object_version
    await session.flush()
    row.status = "finalized"
    await session.commit()
    return row


async def resume_artifact_upload(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    artifact: ExportArtifact,
    content: bytes,
    content_type: str,
) -> ExportArtifact:
    """Resume a ``pending``/``uploaded`` intent row from a failed attempt.

    Retries reuse the same row and ``object_key`` so one logical artifact
    keeps a single storage object across job retries (M-data-12).

    Report bytes are not byte-stable across regenerations (workbook/zip
    metadata embeds timestamps), so the stored checksum is only binding when
    it describes a confirmed object:

    - ``uploaded``: the earlier ``put`` succeeded. If the object still exists
      under that key, it already carries the recorded checksum — skip the
      rewrite and finalize. If the object vanished, fall through to a fresh
      upload and adopt the regenerated checksum.
    - ``pending``: ``put`` never completed, so no confirmed object exists for
      the key; the regenerated bytes' checksum is adopted and enforced on
      upload. If bytes still happen to match, nothing changes.
    """
    expected_checksum = artifact.checksum_sha256
    if artifact.status == "uploaded":
        if await storage.exists(artifact.object_key):
            await _rebind_tenant(
                session,
                organization_id=artifact.organization_id,
                user_id=artifact.requested_by,
            )
            artifact.status = "finalized"
            await session.commit()
            return artifact
        expected_checksum = None
    else:
        expected_checksum = None

    if expected_checksum is None:
        expected_checksum = hashlib.sha256(content).hexdigest()
        artifact.checksum_sha256 = expected_checksum
        artifact.size_bytes = len(content)

    try:
        meta = await storage.put(
            artifact.object_key,
            content,
            content_type,
            expected_checksum_sha256=expected_checksum,
        )
    except ChecksumMismatch:
        # Regenerated bytes diverged from a checksum we just adopted — a bug,
        # not an integrity violation; propagate so last_error names it.
        raise
    except ObjectStorageError as exc:
        raise ArtifactStorageError(
            "Object storage upload failed; artifact left pending for reconciliation.",
            details={"artifact_id": str(artifact.id), "object_key": artifact.object_key},
        ) from exc

    await _rebind_tenant(
        session,
        organization_id=artifact.organization_id,
        user_id=artifact.requested_by,
    )
    artifact.status = "uploaded"
    artifact.checksum_sha256 = meta.checksum_sha256
    artifact.size_bytes = meta.size_bytes
    artifact.content_type = meta.content_type
    artifact.object_version = meta.object_version
    await session.flush()
    artifact.status = "finalized"
    await session.commit()
    return artifact


async def get_artifact(
    session: AsyncSession,
    *,
    organization_id: UUID,
    artifact_id: UUID,
) -> ExportArtifact:
    """Return an org-scoped artifact or raise ``ArtifactNotFoundError`` (404)."""
    stmt = sa.select(ExportArtifact).where(
        ExportArtifact.organization_id == organization_id,
        ExportArtifact.id == artifact_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise ArtifactNotFoundError()
    return row


async def list_artifacts(
    session: AsyncSession,
    *,
    organization_id: UUID,
    report_type: str | None = None,
    posted_run_id: UUID | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ArtifactListPage:
    """List artifacts for an org with optional filters, newest-first."""
    offset = page_offset(page=page, page_size=page_size)
    base = sa.select(ExportArtifact).where(ExportArtifact.organization_id == organization_id)
    if report_type is not None:
        base = base.where(ExportArtifact.report_type == report_type)
    if posted_run_id is not None:
        base = base.where(ExportArtifact.posted_run_id == posted_run_id)
    if status is not None:
        base = base.where(ExportArtifact.status == status)

    count_stmt = sa.select(sa.func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    page_stmt = (
        base.order_by(ExportArtifact.created_at.desc(), ExportArtifact.id.desc())
        .limit(page_size)
        .offset(offset)
    )
    rows = (await session.execute(page_stmt)).scalars().all()
    return ArtifactListPage(
        items=[ArtifactResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=page_count(total=total, page_size=page_size),
    )


def _assert_downloadable(artifact: ExportArtifact, *, now: datetime) -> None:
    if artifact.status == "expired":
        raise ArtifactExpiredError()
    if artifact.status in {"pending", "uploaded"}:
        raise ArtifactNotFinalizedError()
    if artifact.status != "finalized":
        # deleted / unknown — present as not found (RLS-style)
        raise ArtifactNotFoundError()
    if artifact.retention_expires_at is not None and artifact.retention_expires_at <= now:
        raise ArtifactExpiredError()


async def stream_download(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    organization_id: UUID,
    artifact_id: UUID,
    actor_user_id: UUID,
) -> ArtifactDownload:
    """Authorize download, audit ``artifact.download``, return stream chunks.

    The audit row is inserted in the same transaction as the access check;
    the transaction is committed before bytes are streamed.
    """
    now = datetime.now(timezone.utc)
    artifact = await get_artifact(
        session,
        organization_id=organization_id,
        artifact_id=artifact_id,
    )
    _assert_downloadable(artifact, now=now)

    await write_access_event(
        session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        command="artifact.download",
        entity_type="export_artifact",
        entity_id=artifact.id,
        entity_label=artifact.report_type.replace("_", " ").title(),
        resource_state=entity_snapshot(artifact),
        metadata={"accessed_at": now.isoformat()},
        summary={
            "report_type": artifact.report_type,
            "template_version": artifact.template_version,
            "checksum_sha256": artifact.checksum_sha256,
            "size_bytes": artifact.size_bytes,
            "content_type": artifact.content_type,
        },
    )
    await session.commit()

    return ArtifactDownload(
        artifact=artifact,
        chunks=storage.stream(artifact.object_key),
    )


async def reconcile_orphans(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    organization_id: UUID,
    older_than_minutes: int = 60,
) -> OrphanReconcileCounts:
    """Reconcile this org's stuck ``pending`` artifact rows older than the cutoff.

    - Object exists and its body SHA-256 matches the stored checksum →
      finalize (``uploaded`` → ``finalized``).
    - Object missing → mark ``deleted``.
    - Object exists but the checksum diverges → leave ``pending`` and count
      under ``checksum_mismatch`` (never finalize over divergent bytes).
    - ``ObjectStorageError`` (e.g. ``StorageUnavailable`` from a bucket
      outage) propagates and rolls the whole batch back — an outage must not
      mass-mark rows ``deleted`` (M-data-12/13).

    Scheduled via the ``artifacts.maintenance`` worker job; also callable
    directly with an org-bound session.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    stmt = sa.select(ExportArtifact).where(
        ExportArtifact.organization_id == organization_id,
        ExportArtifact.status == "pending",
        ExportArtifact.created_at <= cutoff,
    )
    rows = (await session.execute(stmt)).scalars().all()
    finalized = 0
    deleted = 0
    checksum_mismatch = 0
    for row in rows:
        if not await storage.exists(row.object_key):
            row.status = "deleted"
            deleted += 1
            continue
        body = await storage.get(row.object_key)
        checksum = hashlib.sha256(body).hexdigest()
        if checksum != row.checksum_sha256:
            logger.warning(
                "artifact_checksum_mismatch",
                artifact_id=str(row.id),
                organization_id=str(organization_id),
                object_key=row.object_key,
            )
            checksum_mismatch += 1
            continue
        row.status = "uploaded"
        row.size_bytes = len(body)
        await session.flush()
        row.status = "finalized"
        finalized += 1
    await session.commit()
    return OrphanReconcileCounts(
        finalized=finalized,
        deleted=deleted,
        checksum_mismatch=checksum_mismatch,
    )


async def expire_artifacts(
    session: AsyncSession,
    *,
    organization_id: UUID,
    now: datetime,
) -> int:
    """Mark this org's finalized artifacts past ``retention_expires_at`` ``expired``.

    Metadata-only transition — the storage object is not deleted here. Each
    expiry writes an ``export_artifact.expire`` audit mutation and an
    ``artifact.purged`` outbox event in the same transaction (ADR 0009 §6).
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    stmt = sa.select(ExportArtifact).where(
        ExportArtifact.organization_id == organization_id,
        ExportArtifact.status == "finalized",
        ExportArtifact.retention_expires_at.is_not(None),
        ExportArtifact.retention_expires_at <= now,
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        before = entity_snapshot(row)
        row.status = "expired"
        await write_mutation_event(
            session,
            organization_id=organization_id,
            actor_user_id=None,
            command="export_artifact.expire",
            entity_type="export_artifact",
            entity_id=row.id,
            entity_label=row.report_type.replace("_", " ").title(),
            before_state=before,
            after_state=entity_snapshot(row),
            summary={
                "report_type": row.report_type,
                "retention_expires_at": row.retention_expires_at,
            },
            metadata={"expired_at": now.isoformat()},
        )
        await emit_event(
            session,
            organization_id=organization_id,
            event_type="artifact.purged",
            payload={
                "organization_id": str(organization_id),
                "artifact_id": str(row.id),
                "object_key": row.object_key,
                "report_type": row.report_type,
            },
        )
    await session.commit()
    return len(rows)
