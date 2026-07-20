"""API tests for report generation routes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.reports import router as reports_router
from app.auth.capabilities import ROLE_CAPABILITIES
from app.jobs.handlers import configure_generate_report
from app.jobs.memory import InMemoryJobQueue
from app.main import create_app
from app.models.payroll_runs import PayrollPeriod, PayrollRun
from app.reports.base import (
    ColumnKind,
    ReportColumn,
    ReportContext,
    ReportDTO,
    ReportRegistry,
    TableSection,
    to_json,
)
from app.services.report_generation import execute_generate_report
from app.storage.memory import InMemoryObjectStorage
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import seed_membership, seed_organization, seed_user

FAKE_REPORT_TYPE = "fake_api_report"
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
            title="API Fake Report",
            organization_name="API Org",
            subtitle="Test",
            sections=(
                TableSection(
                    title="Rows",
                    columns=(
                        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
                        ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                    ),
                    rows=(("Test", Decimal("1.00")),),
                ),
            ),
        )


def _fresh_registry() -> ReportRegistry:
    registry = ReportRegistry()
    registry.register(
        FAKE_REPORT_TYPE,
        builder=_FakeBuilder(),
        to_json=to_json,
        to_excel=lambda dto: b"API-XLSX",
        to_pdf=lambda dto: b"%PDF-API",
        content_types=CONTENT_TYPES,
        filename_pattern="{report_type}_{posted_run_id}.{ext}",
    )
    return registry


def _reports_app(
    *,
    registry: ReportRegistry,
    queue: InMemoryJobQueue,
    storage: InMemoryObjectStorage,
):
    application = create_app()
    application.include_router(reports_router, prefix="/api")
    application.state.auth_ready = True
    application.state.report_registry = registry
    application.state.job_queue = queue
    application.state.object_storage = storage
    configure_generate_report(storage=storage, registry=registry)
    return application


@pytest_asyncio.fixture
async def storage():
    return InMemoryObjectStorage()


@pytest_asyncio.fixture
async def registry():
    return _fresh_registry()


@pytest_asyncio.fixture
async def queue():
    return InMemoryJobQueue()


@pytest_asyncio.fixture
async def client(dev_settings, storage, registry, queue):
    application = _reports_app(registry=registry, queue=queue, storage=storage)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_world(session, dev_settings, client, *, slug: str | None = None):
    org = await seed_organization(
        session,
        name="Reports API Org",
        slug=slug or f"rep-api-{uuid4().hex[:10]}",
    )
    admin = await seed_user(session, name="Org Admin")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=admin.id,
        role="organization_administrator",
    )
    await session.commit()
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=admin.id,
        active_organization_id=org.id,
    )
    apply_session_cookie(client, cookie)
    return org, admin


async def _bind(session: AsyncSession, org_id, user_id) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_run(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    status: str = "posted",
) -> UUID:
    await _bind(session, org_id, user_id)
    period = PayrollPeriod(
        organization_id=org_id,
        period_year=2026,
        period_month=6,
        status="open",
    )
    session.add(period)
    await session.flush()
    run = PayrollRun(
        organization_id=org_id,
        period_id=period.id,
        status=status,
    )
    session.add(run)
    await session.commit()
    return run.id


@pytest.mark.asyncio
async def test_list_reports_returns_fake_type_and_formats(client, session, dev_settings, registry):
    await _admin_world(session, dev_settings, client)
    resp = await client.get("/api/reports")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["report_type"] == FAKE_REPORT_TYPE
    assert set(item["formats"]) == set(CONTENT_TYPES.keys())
    assert item["product_sheet"] is False


@pytest.mark.asyncio
async def test_preview_report_returns_json(client, session, dev_settings, registry):
    org, admin = await _admin_world(session, dev_settings, client)
    run_id = await _seed_run(session, org_id=org.id, user_id=admin.id, status="posted")

    resp = await client.get(
        f"/api/reports/{FAKE_REPORT_TYPE}/preview",
        params={"posted_run_id": str(run_id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["report_type"] == FAKE_REPORT_TYPE
    assert body["title"] == "API Fake Report"
    assert isinstance(body["sections"], list)
    assert body["sections"][0]["title"] == "Rows"


@pytest.mark.asyncio
async def test_export_reports_enqueues_consolidated_job(
    client, session, dev_settings, registry, queue, monkeypatch
):
    from app.services import report_generation as rg

    monkeypatch.setattr(rg, "PRODUCT_REPORT_SHEETS", (FAKE_REPORT_TYPE,))
    monkeypatch.setattr(
        rg,
        "PRODUCT_REPORT_SHEET_TITLES",
        {FAKE_REPORT_TYPE: "Fake API Report"},
    )

    org, admin = await _admin_world(session, dev_settings, client)
    run_id = await _seed_run(session, org_id=org.id, user_id=admin.id, status="posted")

    resp = await client.post("/api/reports/export", json={"posted_run_id": str(run_id)})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    job_id = UUID(body["job_id"])
    assert body["status"] == "queued"
    job = queue._jobs[job_id]
    assert job.job_type == rg.JOB_TYPE_CONSOLIDATED_XLSX
    assert str(run_id) in (job.dedupe_key or "")
    assert FAKE_REPORT_TYPE in registry


@pytest.mark.asyncio
async def test_generate_then_job_status_with_artifact(
    client, session, dev_settings, registry, queue, storage
):
    org, admin = await _admin_world(session, dev_settings, client)
    run_id = await _seed_run(session, org_id=org.id, user_id=admin.id, status="posted")

    resp = await client.post(
        "/api/reports/generate",
        json={
            "report_type": FAKE_REPORT_TYPE,
            "posted_run_id": str(run_id),
            "format": "json",
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    job_id = UUID(body["job_id"])
    assert body["status"] == "queued"

    job = queue._jobs[job_id]
    await _bind(session, org.id, admin.id)
    result = await execute_generate_report(
        session,
        storage,
        job,
        registry=registry,
    )
    claimed = await queue.claim("api-test-worker", job_types=["generate_report"])
    assert claimed is not None
    assert claimed.id == job_id
    await queue.complete(job_id, "api-test-worker", result)

    status_resp = await client.get(f"/api/reports/jobs/{job_id}")
    assert status_resp.status_code == 200, status_resp.text
    status_body = status_resp.json()
    assert status_body["job_id"] == str(job_id)
    assert status_body["status"] == "succeeded"
    assert status_body["result"]["artifact_id"] == result["artifact_id"]
    assert status_body["last_error"] is None


@pytest.mark.asyncio
async def test_generate_unknown_report_type_404(client, session, dev_settings):
    org, admin = await _admin_world(session, dev_settings, client)
    run_id = await _seed_run(session, org_id=org.id, user_id=admin.id)

    resp = await client.post(
        "/api/reports/generate",
        json={
            "report_type": "does_not_exist",
            "posted_run_id": str(run_id),
            "format": "pdf",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_unposted_run_409(client, session, dev_settings):
    org, admin = await _admin_world(session, dev_settings, client)
    run_id = await _seed_run(session, org_id=org.id, user_id=admin.id, status="draft")

    resp = await client.post(
        "/api/reports/generate",
        json={
            "report_type": FAKE_REPORT_TYPE,
            "posted_run_id": str(run_id),
            "format": "excel",
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_capability_gate_403(client, session, dev_settings, monkeypatch):
    org, admin = await _admin_world(session, dev_settings, client)
    monkeypatch.setitem(
        ROLE_CAPABILITIES,
        "organization_administrator",
        ROLE_CAPABILITIES["organization_administrator"] - frozenset({"generate_reports"}),
    )
    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=admin.id,
            active_organization_id=org.id,
        ),
    )
    resp = await client.get("/api/reports")
    assert resp.status_code == 403
