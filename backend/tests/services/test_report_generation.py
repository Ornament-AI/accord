"""Service tests for report generation request + execute paths."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.memory import InMemoryJobQueue
from app.models.payroll_runs import PayrollPeriod, PayrollRun
from app.models.platform import ExportArtifact
from app.reports.base import (
    ColumnKind,
    ReportColumn,
    ReportContext,
    ReportDTO,
    ReportRegistry,
    TableSection,
    to_json,
)
from app.services.report_generation import (
    DEFAULT_ENGINE_VERSION,
    DEFAULT_TEMPLATE_VERSION,
    PostedRunNotFoundError,
    ReportTypeNotFoundError,
    RunNotPostedError,
    UnsupportedReportFormatError,
    execute_generate_report,
    request_report,
)
from app.storage.memory import InMemoryObjectStorage
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_membership, seed_organization, seed_user

FAKE_REPORT_TYPE = "fake_pay_bill"
EXCEL_BYTES = b"FAKE-XLSX-BYTES"
PDF_BYTES = b"%PDF-FAKE-REPORT"
CONTENT_TYPES = {
    "json": "application/json",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


class _FakeBuilder:
    async def build(self, session: Any, ctx: ReportContext) -> ReportDTO:
        return ReportDTO(
            report_type=FAKE_REPORT_TYPE,
            template_version=ctx.template_version,
            title="Fake Pay Bill",
            organization_name="Test Org",
            subtitle="Unit test",
            sections=(
                TableSection(
                    title="Register",
                    columns=(
                        ReportColumn(key="employee", header="Employee", kind=ColumnKind.TEXT),
                        ReportColumn(key="gross", header="Gross", kind=ColumnKind.MONEY),
                    ),
                    rows=(("Ada Lovelace", Decimal("100.00")),),
                    totals=(None, Decimal("100.00")),
                ),
            ),
        )


def _fresh_registry() -> ReportRegistry:
    registry = ReportRegistry()
    registry.register(
        FAKE_REPORT_TYPE,
        builder=_FakeBuilder(),
        to_json=to_json,
        to_excel=lambda dto: EXCEL_BYTES,
        to_pdf=lambda dto: PDF_BYTES,
        content_types=CONTENT_TYPES,
        filename_pattern="{report_type}_{posted_run_id}.{ext}",
    )
    return registry


async def _bind(session: AsyncSession, org_id: UUID, user_id: UUID) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_world(session: AsyncSession, *, run_status: str = "posted") -> dict:
    if session.in_transaction():
        await session.rollback()

    org = await seed_organization(session, name="Report Gen Org", slug=f"rg-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"rg_{uuid4().hex[:10]}")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=user.id,
        role="organization_administrator",
    )
    period = PayrollPeriod(
        organization_id=org.id,
        period_year=2026,
        period_month=6,
        status="open",
    )
    session.add(period)
    await session.flush()
    run = PayrollRun(
        organization_id=org.id,
        period_id=period.id,
        status=run_status,
    )
    session.add(run)
    await session.commit()
    await _bind(session, org.id, user.id)
    return {
        "org_id": org.id,
        "user_id": user.id,
        "run_id": run.id,
        "period_id": period.id,
    }


@pytest.mark.asyncio
async def test_request_report_enqueues_with_dedupe_key(session):
    world = await _seed_world(session)
    queue = InMemoryJobQueue()
    registry = _fresh_registry()

    job = await request_report(
        session,
        queue,
        organization_id=world["org_id"],
        report_type=FAKE_REPORT_TYPE,
        posted_run_id=world["run_id"],
        format="excel",
        requested_by=world["user_id"],
        registry=registry,
    )

    expected = f"{FAKE_REPORT_TYPE}:{world['run_id']}:excel:{DEFAULT_TEMPLATE_VERSION}"
    assert job.job_type == "generate_report"
    assert job.dedupe_key == expected
    assert job.payload["report_type"] == FAKE_REPORT_TYPE
    assert job.payload["format"] == "excel"
    assert job.payload["template_version"] == DEFAULT_TEMPLATE_VERSION


@pytest.mark.asyncio
async def test_request_report_dedupe_returns_same_job(session):
    world = await _seed_world(session)
    queue = InMemoryJobQueue()
    registry = _fresh_registry()
    kwargs = dict(
        organization_id=world["org_id"],
        report_type=FAKE_REPORT_TYPE,
        posted_run_id=world["run_id"],
        format="pdf",
        requested_by=world["user_id"],
        registry=registry,
    )

    first = await request_report(session, queue, **kwargs)
    second = await request_report(session, queue, **kwargs)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_request_report_unknown_report_type(session):
    world = await _seed_world(session)
    with pytest.raises(ReportTypeNotFoundError):
        await request_report(
            session,
            InMemoryJobQueue(),
            organization_id=world["org_id"],
            report_type="missing_report",
            posted_run_id=world["run_id"],
            format="json",
            requested_by=world["user_id"],
            registry=_fresh_registry(),
        )


@pytest.mark.asyncio
async def test_request_report_unknown_run(session):
    world = await _seed_world(session)
    with pytest.raises(PostedRunNotFoundError):
        await request_report(
            session,
            InMemoryJobQueue(),
            organization_id=world["org_id"],
            report_type=FAKE_REPORT_TYPE,
            posted_run_id=uuid4(),
            format="json",
            requested_by=world["user_id"],
            registry=_fresh_registry(),
        )


@pytest.mark.asyncio
async def test_request_report_unposted_run(session):
    world = await _seed_world(session, run_status="draft")
    with pytest.raises(RunNotPostedError):
        await request_report(
            session,
            InMemoryJobQueue(),
            organization_id=world["org_id"],
            report_type=FAKE_REPORT_TYPE,
            posted_run_id=world["run_id"],
            format="json",
            requested_by=world["user_id"],
            registry=_fresh_registry(),
        )


@pytest.mark.asyncio
async def test_request_report_unsupported_format(session):
    world = await _seed_world(session)
    registry = ReportRegistry()
    registry.register(
        FAKE_REPORT_TYPE,
        builder=_FakeBuilder(),
        to_json=to_json,
        to_excel=lambda dto: EXCEL_BYTES,
        to_pdf=lambda dto: PDF_BYTES,
        content_types={"json": "application/json"},
        filename_pattern="{report_type}.json",
    )
    with pytest.raises(UnsupportedReportFormatError):
        await request_report(
            session,
            InMemoryJobQueue(),
            organization_id=world["org_id"],
            report_type=FAKE_REPORT_TYPE,
            posted_run_id=world["run_id"],
            format="excel",
            requested_by=world["user_id"],
            registry=registry,
        )


@pytest.mark.asyncio
async def test_execute_generate_report_creates_finalized_artifact(session):
    world = await _seed_world(session)
    queue = InMemoryJobQueue()
    registry = _fresh_registry()
    storage = InMemoryObjectStorage()

    job = await request_report(
        session,
        queue,
        organization_id=world["org_id"],
        report_type=FAKE_REPORT_TYPE,
        posted_run_id=world["run_id"],
        format="excel",
        template_version="v2",
        requested_by=world["user_id"],
        registry=registry,
    )

    await _bind(session, world["org_id"], world["user_id"])
    result = await execute_generate_report(
        session,
        storage,
        job,
        registry=registry,
        engine_version="engine-test-1",
    )
    assert "artifact_id" in result
    assert "reused" not in result or result.get("reused") is not True

    await _bind(session, world["org_id"], world["user_id"])
    artifact_id = UUID(result["artifact_id"])
    artifact = await session.get(ExportArtifact, artifact_id)
    assert artifact is not None
    assert artifact.status == "finalized"
    assert artifact.report_type == FAKE_REPORT_TYPE
    assert artifact.template_version == "v2"
    assert artifact.engine_version == "engine-test-1"
    assert artifact.content_type == CONTENT_TYPES["excel"]
    assert artifact.posted_run_id == world["run_id"]
    assert await storage.get(artifact.object_key) == EXCEL_BYTES


@pytest.mark.asyncio
async def test_execute_generate_report_reuses_finalized_artifact(session):
    world = await _seed_world(session)
    queue = InMemoryJobQueue()
    registry = _fresh_registry()
    storage = InMemoryObjectStorage()

    job = await request_report(
        session,
        queue,
        organization_id=world["org_id"],
        report_type=FAKE_REPORT_TYPE,
        posted_run_id=world["run_id"],
        format="pdf",
        requested_by=world["user_id"],
        registry=registry,
    )

    await _bind(session, world["org_id"], world["user_id"])
    first = await execute_generate_report(
        session,
        storage,
        job,
        registry=registry,
        engine_version=DEFAULT_ENGINE_VERSION,
    )
    await _bind(session, world["org_id"], world["user_id"])
    second = await execute_generate_report(
        session,
        storage,
        job,
        registry=registry,
        engine_version=DEFAULT_ENGINE_VERSION,
    )

    assert first["artifact_id"] == second["artifact_id"]
    assert second.get("reused") is True

    await _bind(session, world["org_id"], world["user_id"])
    rows = (
        (
            await session.execute(
                sa.select(ExportArtifact).where(
                    ExportArtifact.organization_id == world["org_id"],
                    ExportArtifact.report_type == FAKE_REPORT_TYPE,
                    ExportArtifact.posted_run_id == world["run_id"],
                    ExportArtifact.content_type == CONTENT_TYPES["pdf"],
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
