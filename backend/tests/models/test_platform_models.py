"""ORM smoke tests for Phase 5 platform tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import select as sqlmodel_select

from app.models.identity import Organization, User
from app.models.payroll_runs import PayrollPeriod, PayrollRun, payroll_run_versions
from app.models.platform import (
    AuditEvent,
    ExportArtifact,
    Job,
    OutboxEvent,
    PayrollApproval,
    WebhookEvent,
)
from tests.migrations.conftest import diag, ensure_accord_roles, run_alembic


async def _bind_org(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.organization_id', :org, true)"),
        {"org": str(org_id)},
    )


@pytest.mark.asyncio
async def test_platform_models_orm_roundtrip(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    version_id = uuid.uuid4()
    calculated_at = datetime.now(timezone.utc)
    object_key = f"{org_id}/{uuid.uuid4()}"

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            org = Organization(
                id=org_id,
                name="Platform Org",
                slug=f"platform-org-{uuid.uuid4().hex[:8]}",
            )
            user = User(
                id=user_id,
                workos_user_id=f"wos_{user_id.hex[:12]}",
                email=f"u-{user_id.hex[:8]}@example.com",
                name="Platform User",
            )
            session.add(org)
            session.add(user)
            await session.flush()

            await _bind_org(session, org_id)

            period = PayrollPeriod(
                organization_id=org_id,
                period_year=2026,
                period_month=7,
                status="open",
            )
            session.add(period)
            await session.flush()

            run = PayrollRun(
                organization_id=org_id,
                period_id=period.id,
                run_type="regular",
                status="draft",
            )
            session.add(run)
            await session.flush()

            await session.execute(
                insert(payroll_run_versions).values(
                    id=version_id,
                    organization_id=org_id,
                    run_id=run.id,
                    version_number=1,
                    engine_version="engine-1.0",
                    content_hash="hash-1",
                    calculated_at=calculated_at,
                    calculated_by=user_id,
                    inputs_snapshot={"employees": []},
                    totals={"net": "0.00"},
                )
            )

            audit = AuditEvent(
                organization_id=org_id,
                actor_user_id=user_id,
                request_id="req-1",
                command="post",
                entity_type="payroll_run",
                entity_id=entity_id,
                summary={"before": {"status": "approved"}, "after": {"status": "posted"}},
            )
            outbox = OutboxEvent(
                organization_id=org_id,
                event_type="payroll_run.posted",
                payload={"run_id": str(run.id)},
            )
            approval = PayrollApproval(
                organization_id=org_id,
                run_id=run.id,
                run_version_id=version_id,
                content_hash="hash-1",
                action="approve",
                actor_user_id=user_id,
                reason="Looks good",
            )
            job = Job(
                organization_id=org_id,
                job_type="export.generate",
                status="queued",
                payload={"report_type": "bank_file"},
                dedupe_key="run-export-1",
                created_by=user_id,
            )
            artifact = ExportArtifact(
                organization_id=org_id,
                posted_run_id=run.id,
                report_type="bank_file",
                template_version="v1",
                engine_version="engine-1.0",
                object_key=object_key,
                checksum_sha256="a" * 64,
                content_type="text/csv",
                size_bytes=128,
                status="pending",
                requested_by=user_id,
            )
            webhook = WebhookEvent(
                provider="workos",
                event_id=f"evt_{uuid.uuid4().hex}",
                event_type="user.updated",
                payload_digest="b" * 64,
            )
            session.add(audit)
            session.add(outbox)
            session.add(approval)
            session.add(job)
            session.add(artifact)
            session.add(webhook)
            await session.commit()

            audit_id = audit.id
            outbox_id = outbox.id
            approval_id = approval.id
            job_id = job.id
            artifact_id = artifact.id
            webhook_id = webhook.id
            webhook_event_id = webhook.event_id

        async with session_factory() as session:
            await _bind_org(session, org_id)

            loaded_audit = (
                await session.execute(sqlmodel_select(AuditEvent).where(AuditEvent.id == audit_id))
            ).scalar_one()
            assert loaded_audit.command == "post"
            assert loaded_audit.summary["after"]["status"] == "posted"

            loaded_outbox = (
                await session.execute(
                    sqlmodel_select(OutboxEvent).where(OutboxEvent.id == outbox_id)
                )
            ).scalar_one()
            assert loaded_outbox.event_type == "payroll_run.posted"
            assert loaded_outbox.attempts == 0

            loaded_approval = (
                await session.execute(
                    sqlmodel_select(PayrollApproval).where(PayrollApproval.id == approval_id)
                )
            ).scalar_one()
            assert loaded_approval.action == "approve"

            loaded_job = (
                await session.execute(sqlmodel_select(Job).where(Job.id == job_id))
            ).scalar_one()
            assert loaded_job.job_type == "export.generate"
            assert loaded_job.last_error is None
            assert loaded_job.max_attempts == 5

            loaded_artifact = (
                await session.execute(
                    sqlmodel_select(ExportArtifact).where(ExportArtifact.id == artifact_id)
                )
            ).scalar_one()
            assert loaded_artifact.object_key == object_key
            assert loaded_artifact.size_bytes == 128

            loaded_webhook = (
                await session.execute(
                    sqlmodel_select(WebhookEvent).where(WebhookEvent.id == webhook_id)
                )
            ).scalar_one()
            assert loaded_webhook.event_id == webhook_event_id
            assert loaded_webhook.provider == "workos"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_events_and_payroll_approvals_are_append_only(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    version_id = uuid.uuid4()
    calculated_at = datetime.now(timezone.utc)

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            session.add(
                Organization(
                    id=org_id,
                    name="Append Org",
                    slug=f"append-org-{uuid.uuid4().hex[:8]}",
                )
            )
            session.add(
                User(
                    id=user_id,
                    workos_user_id=f"wos_{user_id.hex[:12]}",
                    email=f"a-{user_id.hex[:8]}@example.com",
                    name="Append User",
                )
            )
            await session.flush()
            await _bind_org(session, org_id)

            period = PayrollPeriod(
                organization_id=org_id,
                period_year=2026,
                period_month=7,
            )
            session.add(period)
            await session.flush()
            run = PayrollRun(
                organization_id=org_id,
                period_id=period.id,
            )
            session.add(run)
            await session.flush()
            await session.execute(
                insert(payroll_run_versions).values(
                    id=version_id,
                    organization_id=org_id,
                    run_id=run.id,
                    version_number=1,
                    engine_version="engine-1.0",
                    content_hash="hash-1",
                    calculated_at=calculated_at,
                    calculated_by=user_id,
                    inputs_snapshot={},
                    totals={},
                )
            )

            audit = AuditEvent(
                organization_id=org_id,
                command="submit",
                entity_type="payroll_run",
                entity_id=run.id,
                summary={"after": {"status": "submitted"}},
            )
            approval = PayrollApproval(
                organization_id=org_id,
                run_id=run.id,
                run_version_id=version_id,
                content_hash="hash-1",
                action="submit",
                actor_user_id=user_id,
            )
            session.add(audit)
            session.add(approval)
            await session.commit()
            audit_id = audit.id
            approval_id = approval.id

        async with session_factory() as session:
            await _bind_org(session, org_id)
            audit = (
                await session.execute(sqlmodel_select(AuditEvent).where(AuditEvent.id == audit_id))
            ).scalar_one()
            audit.command = "tamper"
            with pytest.raises(IntegrityError, match="(?i)UPDATE/DELETE forbidden"):
                await session.commit()
            await session.rollback()

        async with session_factory() as session:
            await _bind_org(session, org_id)
            audit = (
                await session.execute(sqlmodel_select(AuditEvent).where(AuditEvent.id == audit_id))
            ).scalar_one()
            await session.delete(audit)
            with pytest.raises(IntegrityError, match="(?i)UPDATE/DELETE forbidden"):
                await session.commit()
            await session.rollback()

        async with session_factory() as session:
            await _bind_org(session, org_id)
            approval = (
                await session.execute(
                    sqlmodel_select(PayrollApproval).where(PayrollApproval.id == approval_id)
                )
            ).scalar_one()
            approval.action = "reject"
            with pytest.raises(IntegrityError, match="(?i)UPDATE/DELETE forbidden"):
                await session.commit()
            await session.rollback()

        async with session_factory() as session:
            await _bind_org(session, org_id)
            approval = (
                await session.execute(
                    sqlmodel_select(PayrollApproval).where(PayrollApproval.id == approval_id)
                )
            ).scalar_one()
            await session.delete(approval)
            with pytest.raises(IntegrityError, match="(?i)UPDATE/DELETE forbidden"):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_outbox_events_update_allowed_delete_forbidden(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    org_id = uuid.uuid4()

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            session.add(
                Organization(
                    id=org_id,
                    name="Outbox Org",
                    slug=f"outbox-org-{uuid.uuid4().hex[:8]}",
                )
            )
            await session.flush()
            await _bind_org(session, org_id)
            outbox = OutboxEvent(
                organization_id=org_id,
                event_type="payroll_run.posted",
                payload={"ok": True},
            )
            session.add(outbox)
            await session.commit()
            outbox_id = outbox.id

        async with session_factory() as session:
            await _bind_org(session, org_id)
            outbox = (
                await session.execute(
                    sqlmodel_select(OutboxEvent).where(OutboxEvent.id == outbox_id)
                )
            ).scalar_one()
            outbox.attempts = 1
            outbox.locked_by = "dispatcher-1"
            await session.commit()

        async with session_factory() as session:
            await _bind_org(session, org_id)
            outbox = (
                await session.execute(
                    sqlmodel_select(OutboxEvent).where(OutboxEvent.id == outbox_id)
                )
            ).scalar_one()
            assert outbox.attempts == 1
            assert outbox.locked_by == "dispatcher-1"
            await session.delete(outbox)
            with pytest.raises(IntegrityError, match="(?i)DELETE forbidden"):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_jobs_dedupe_partial_unique_index(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    org_id = uuid.uuid4()

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            session.add(
                Organization(
                    id=org_id,
                    name="Jobs Org",
                    slug=f"jobs-org-{uuid.uuid4().hex[:8]}",
                )
            )
            await session.flush()
            await _bind_org(session, org_id)

            first = Job(
                organization_id=org_id,
                job_type="export.generate",
                status="queued",
                payload={},
                dedupe_key="same-key",
            )
            session.add(first)
            await session.commit()
            first_id = first.id

        async with session_factory() as session:
            await _bind_org(session, org_id)
            session.add(
                Job(
                    organization_id=org_id,
                    job_type="export.generate",
                    status="queued",
                    payload={},
                    dedupe_key="same-key",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            await _bind_org(session, org_id)
            first = (
                await session.execute(sqlmodel_select(Job).where(Job.id == first_id))
            ).scalar_one()
            first.status = "succeeded"
            await session.commit()

        async with session_factory() as session:
            await _bind_org(session, org_id)
            # After terminal status, the same dedupe key may be enqueued again.
            session.add(
                Job(
                    organization_id=org_id,
                    job_type="export.generate",
                    status="queued",
                    payload={},
                    dedupe_key="same-key",
                )
            )
            await session.commit()
            rows = (
                (
                    await session.execute(
                        sqlmodel_select(Job).where(
                            Job.organization_id == org_id,
                            Job.dedupe_key == "same-key",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2
            assert {row.status for row in rows} == {"succeeded", "queued"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_webhook_events_event_id_unique(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            session.add(
                WebhookEvent(
                    event_id="evt_duplicate",
                    event_type="user.updated",
                    payload_digest="c" * 64,
                )
            )
            await session.flush()
            session.add(
                WebhookEvent(
                    event_id="evt_duplicate",
                    event_type="user.updated",
                    payload_digest="d" * 64,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
    finally:
        await engine.dispose()
