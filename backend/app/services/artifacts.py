"""Export artifact lifecycle service (ADR 0010).

Consistency protocol: INSERT pending intent → storage.put → finalize
(uploaded → finalized). This module exposes orphan reconciliation and
retention-expiry service functions; no periodic worker handlers or scheduler
are currently wired for them.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AccordError, ConflictError, NotFoundError
from app.models.platform import ExportArtifact
from app.services.audit_events import entity_snapshot, write_access_event
from app.schemas.artifacts import ArtifactListPage, ArtifactResponse
from app.schemas.pagination import page_count, page_offset
from app.storage.protocol import ObjectStorage, ObjectStorageError, build_object_key
from app.tenancy import bind_tenant_context


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
    older_than_minutes: int = 60,
) -> OrphanReconcileCounts:
    """Reconcile stuck ``pending`` artifact rows older than the cutoff.

    If the object exists in storage → finalize (uploaded → finalized).
    If missing → mark ``deleted``.

    This service function is callable directly. A periodic worker handler and
    scheduler have not yet been registered.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    stmt = sa.select(ExportArtifact).where(
        ExportArtifact.status == "pending",
        ExportArtifact.created_at <= cutoff,
    )
    rows = (await session.execute(stmt)).scalars().all()
    finalized = 0
    deleted = 0
    for row in rows:
        if await storage.exists(row.object_key):
            body = await storage.get(row.object_key)
            checksum = hashlib.sha256(body).hexdigest()
            row.status = "uploaded"
            row.checksum_sha256 = checksum
            row.size_bytes = len(body)
            await session.flush()
            row.status = "finalized"
            finalized += 1
        else:
            row.status = "deleted"
            deleted += 1
    await session.commit()
    return OrphanReconcileCounts(finalized=finalized, deleted=deleted)


async def expire_artifacts(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    """Mark finalized artifacts past ``retention_expires_at`` as ``expired``.

    This function only transitions metadata. Object deletion and the worker
    handler/scheduler for expiry remain follow-up work.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    stmt = sa.select(ExportArtifact).where(
        ExportArtifact.status == "finalized",
        ExportArtifact.retention_expires_at.is_not(None),
        ExportArtifact.retention_expires_at <= now,
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        row.status = "expired"
    await session.commit()
    return len(rows)
