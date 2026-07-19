"""Service tests for export artifact lifecycle (ADR 0010)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import AuditEvent, ExportArtifact
from app.services.artifacts import (
    ArtifactStorageError,
    create_artifact,
    expire_artifacts,
    list_artifacts,
    reconcile_orphans,
    stream_download,
)
from app.storage.memory import InMemoryObjectStorage
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_membership, seed_organization, seed_user


async def _bind(session: AsyncSession, org_id, user_id) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_world(session: AsyncSession) -> dict:
    if session.in_transaction():
        await session.rollback()

    org = await seed_organization(session, name="Artifact Org", slug=f"art-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"art_{uuid4().hex[:10]}")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=user.id,
        role="organization_administrator",
    )
    await session.commit()
    await _bind(session, org.id, user.id)
    return {"org_id": org.id, "user_id": user.id}


@pytest.mark.asyncio
async def test_create_artifact_pending_to_finalized_checksum_matches(session):
    world = await _seed_world(session)
    storage = InMemoryObjectStorage()
    content = b"bank-file-bytes-v1"

    artifact = await create_artifact(
        session,
        storage,
        organization_id=world["org_id"],
        report_type="bank_file",
        template_version="v1",
        content=content,
        content_type="text/csv",
        requested_by=world["user_id"],
        engine_version="engine-1.0",
        retention_days=30,
    )

    assert artifact.status == "finalized"
    assert artifact.checksum_sha256 == hashlib.sha256(content).hexdigest()
    assert artifact.size_bytes == len(content)
    assert artifact.object_version is not None
    assert await storage.exists(artifact.object_key)
    assert await storage.get(artifact.object_key) == content


@pytest.mark.asyncio
async def test_create_artifact_storage_failure_leaves_pending(session):
    world = await _seed_world(session)
    storage = InMemoryObjectStorage()
    storage.inject_fault()

    with pytest.raises(ArtifactStorageError):
        await create_artifact(
            session,
            storage,
            organization_id=world["org_id"],
            report_type="bank_file",
            template_version="v1",
            content=b"will-fail",
            content_type="text/csv",
            requested_by=world["user_id"],
        )

    await _bind(session, world["org_id"], world["user_id"])
    rows = (
        (
            await session.execute(
                sa.select(ExportArtifact).where(ExportArtifact.organization_id == world["org_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert not await storage.exists(rows[0].object_key)


@pytest.mark.asyncio
async def test_stream_download_bytes_and_audit(session):
    world = await _seed_world(session)
    storage = InMemoryObjectStorage()
    content = b"exact-download-payload"

    artifact = await create_artifact(
        session,
        storage,
        organization_id=world["org_id"],
        report_type="payslip",
        template_version="v2",
        content=content,
        content_type="application/pdf",
        requested_by=world["user_id"],
    )
    artifact_id = artifact.id
    checksum = artifact.checksum_sha256

    await _bind(session, world["org_id"], world["user_id"])
    download = await stream_download(
        session,
        storage,
        organization_id=world["org_id"],
        artifact_id=artifact_id,
        actor_user_id=world["user_id"],
    )
    chunks: list[bytes] = []
    async for chunk in download.chunks:
        chunks.append(chunk)
    assert b"".join(chunks) == content

    await _bind(session, world["org_id"], world["user_id"])
    audit = (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.organization_id == world["org_id"],
                AuditEvent.command == "artifact.download",
                AuditEvent.entity_type == "export_artifact",
                AuditEvent.entity_id == artifact_id,
            )
        )
    ).scalar_one()
    assert audit.actor_user_id == world["user_id"]
    assert audit.event_kind == "access"
    assert audit.before_state is None
    assert audit.after_state is None
    assert audit.changed_count == 0
    assert audit.metadata_["resource"]["id"] == str(artifact_id)
    assert audit.metadata_["resource"]["object_key"] == artifact.object_key
    assert audit.summary["checksum_sha256"] == checksum


@pytest.mark.asyncio
async def test_reconcile_orphans_finalizes_and_deletes(session):
    world = await _seed_world(session)
    storage = InMemoryObjectStorage()
    old = datetime.now(timezone.utc) - timedelta(hours=2)

    # Pending with object present (upload succeeded, finalize never ran).
    key_ok = f"{world['org_id']}/{uuid4()}"
    body = b"orphan-present"
    await storage.put(key_ok, body, "text/csv")
    present = ExportArtifact(
        organization_id=world["org_id"],
        report_type="bank_file",
        template_version="v1",
        object_key=key_ok,
        checksum_sha256=hashlib.sha256(body).hexdigest(),
        content_type="text/csv",
        size_bytes=len(body),
        status="pending",
        requested_by=world["user_id"],
        created_at=old,
    )
    # Pending with object missing.
    key_missing = f"{world['org_id']}/{uuid4()}"
    missing = ExportArtifact(
        organization_id=world["org_id"],
        report_type="bank_file",
        template_version="v1",
        object_key=key_missing,
        checksum_sha256="b" * 64,
        content_type="text/csv",
        size_bytes=1,
        status="pending",
        requested_by=world["user_id"],
        created_at=old,
    )
    session.add_all([present, missing])
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    counts = await reconcile_orphans(session, storage, older_than_minutes=60)
    assert counts.finalized == 1
    assert counts.deleted == 1

    await _bind(session, world["org_id"], world["user_id"])
    present_row = await session.get(ExportArtifact, present.id)
    missing_row = await session.get(ExportArtifact, missing.id)
    assert present_row is not None and present_row.status == "finalized"
    assert missing_row is not None and missing_row.status == "deleted"


@pytest.mark.asyncio
async def test_expire_artifacts_past_retention(session):
    world = await _seed_world(session)
    storage = InMemoryObjectStorage()
    artifact = await create_artifact(
        session,
        storage,
        organization_id=world["org_id"],
        report_type="bank_file",
        template_version="v1",
        content=b"expire-me",
        content_type="text/csv",
        requested_by=world["user_id"],
        retention_days=1,
    )
    artifact_id = artifact.id

    await _bind(session, world["org_id"], world["user_id"])
    row = await session.get(ExportArtifact, artifact_id)
    assert row is not None
    row.retention_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    n = await expire_artifacts(session, now=datetime.now(timezone.utc))
    assert n == 1

    await _bind(session, world["org_id"], world["user_id"])
    expired = await session.get(ExportArtifact, artifact_id)
    assert expired is not None and expired.status == "expired"


@pytest.mark.asyncio
async def test_list_artifacts_filters(session):
    world = await _seed_world(session)
    storage = InMemoryObjectStorage()

    a = await create_artifact(
        session,
        storage,
        organization_id=world["org_id"],
        report_type="bank_file",
        template_version="v1",
        content=b"one",
        content_type="text/csv",
        requested_by=world["user_id"],
    )
    a_id = a.id
    await create_artifact(
        session,
        storage,
        organization_id=world["org_id"],
        report_type="payslip",
        template_version="v1",
        content=b"two",
        content_type="application/pdf",
        requested_by=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    # Force one pending for status filter.
    pending = ExportArtifact(
        organization_id=world["org_id"],
        report_type="bank_file",
        template_version="v9",
        object_key=f"{world['org_id']}/{uuid4()}",
        checksum_sha256="c" * 64,
        content_type="text/csv",
        size_bytes=0,
        status="pending",
        requested_by=world["user_id"],
    )
    session.add(pending)
    await session.flush()
    pending_id = pending.id
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    by_type = await list_artifacts(
        session,
        organization_id=world["org_id"],
        report_type="bank_file",
    )
    assert by_type.total == 2
    assert all(item.report_type == "bank_file" for item in by_type.items)

    by_status = await list_artifacts(
        session,
        organization_id=world["org_id"],
        status="finalized",
    )
    assert by_status.total == 2
    assert {item.id for item in by_status.items} >= {a_id}

    by_pending = await list_artifacts(
        session,
        organization_id=world["org_id"],
        status="pending",
    )
    assert by_pending.total == 1
    assert by_pending.items[0].id == pending_id
