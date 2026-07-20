"""Allowlist consistency + consolidated ZIP export for product report sheets."""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from openpyxl import load_workbook
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
from app.reports.registry_setup import (
    PRODUCT_REPORT_SHEET_TITLES,
    PRODUCT_REPORT_SHEETS,
    build_report_registry,
)
from app.services.report_generation import (
    DEFAULT_TEMPLATE_VERSION,
    execute_consolidated_xlsx,
    list_registered_reports,
    manifest_hash,
    product_sheet_manifest,
    request_consolidated_export,
)
from app.storage.memory import InMemoryObjectStorage
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_membership, seed_organization, seed_user

CONTENT_TYPES = {
    "json": "application/json",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


class _FakeBuilder:
    async def build(self, session: Any, ctx: ReportContext) -> ReportDTO:
        return ReportDTO(
            report_type="placeholder",
            template_version=ctx.template_version,
            title="Sheet",
            organization_name="Org",
            subtitle="June 2026",
            sections=(
                TableSection(
                    title="Rows",
                    columns=(
                        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
                        ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                    ),
                    rows=(("Ada", Decimal("1.00")),),
                ),
            ),
        )


def _minimal_dto(report_type: str) -> ReportDTO:
    return ReportDTO(
        report_type=report_type,
        template_version=DEFAULT_TEMPLATE_VERSION,
        title=PRODUCT_REPORT_SHEET_TITLES.get(report_type, report_type),
        organization_name="Test Org",
        subtitle="June 2026",
        sections=(
            TableSection(
                title="Rows",
                columns=(
                    ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
                    ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                ),
                rows=(("Ada", Decimal("1.00")),),
                totals=(None, Decimal("1.00")),
            ),
        ),
    )


def _product_fake_registry() -> ReportRegistry:
    registry = ReportRegistry()
    builder = _FakeBuilder()
    for report_type in PRODUCT_REPORT_SHEETS:
        registry.register(
            report_type,
            builder=builder,
            to_json=to_json,
            to_excel=lambda dto: b"PK\x03\x04fake-xlsx",
            to_pdf=lambda dto: b"%PDF-fake",
            content_types=CONTENT_TYPES,
            filename_pattern="{report_type}_{posted_run_id}.{ext}",
        )
    return registry


async def _bind(session: AsyncSession, org_id: UUID, user_id: UUID) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_posted_run(session: AsyncSession) -> dict[str, UUID]:
    if session.in_transaction():
        await session.rollback()
    org = await seed_organization(session, name="Product Sheets Org", slug=f"ps-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"ps_{uuid4().hex[:10]}")
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
        status="posted",
    )
    session.add(run)
    await session.commit()
    await _bind(session, org.id, user.id)
    return {"organization_id": org.id, "user_id": user.id, "posted_run_id": run.id}


def test_product_report_sheets_allowlist_consistency() -> None:
    registry = build_report_registry()
    assert len(PRODUCT_REPORT_SHEETS) == 18
    assert "payslips" in PRODUCT_REPORT_SHEETS
    assert "advance_schedule" not in PRODUCT_REPORT_SHEETS
    # Generic custom variant infrastructure stays outside the fixed workbook pack.
    assert "advance_schedule" in registry

    for report_type in PRODUCT_REPORT_SHEETS:
        assert report_type in registry, f"{report_type} not registered"
        assert report_type in PRODUCT_REPORT_SHEET_TITLES
        registration = registry.get(report_type)
        assert "excel" in registration.formatters.content_types
        assert "xlsx" not in registration.formatters.content_types


def test_family_content_types_use_excel_key() -> None:
    registry = build_report_registry()
    for report_type, registration in registry._entries.items():  # noqa: SLF001
        keys = set(registration.formatters.content_types)
        assert "xlsx" not in keys, report_type
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if mime in registration.formatters.content_types.values():
            assert "excel" in keys, report_type


def test_product_sheets_to_excel_callable() -> None:
    """Each allowlisted sheet's to_excel accepts a minimal DTO without raising."""
    registry = build_report_registry()
    for report_type in PRODUCT_REPORT_SHEETS:
        registration = registry.get(report_type)
        xlsx = registration.formatters.to_excel(_minimal_dto(report_type))
        assert isinstance(xlsx, (bytes, bytearray))
        assert xlsx[:2] == b"PK"
        wb = load_workbook(io.BytesIO(xlsx))
        assert wb.sheetnames


def test_list_reports_marks_product_sheets() -> None:
    registry = build_report_registry()
    items = {item.report_type: item for item in list_registered_reports(registry)}
    product = [rt for rt, item in items.items() if item.product_sheet]
    assert sorted(product) == sorted(PRODUCT_REPORT_SHEETS)
    assert items["payslips"].product_sheet is True
    assert items["advance_schedule"].product_sheet is False
    assert items["pay_bill"].title == "Pay Bill"
    assert "excel" in items["pay_bill"].formats


@pytest.mark.asyncio
async def test_consolidated_export_zip_has_eighteen_entries(session) -> None:
    world = await _seed_posted_run(session)
    registry = _product_fake_registry()
    storage = InMemoryObjectStorage()
    queue = InMemoryJobQueue()

    job = await request_consolidated_export(
        session,
        queue,
        organization_id=world["organization_id"],
        posted_run_id=world["posted_run_id"],
        requested_by=world["user_id"],
        registry=registry,
    )
    assert job.job_type == "consolidated_xlsx"
    assert job.dedupe_key.startswith(f"consolidated_xlsx:{world['posted_run_id']}:")
    expected_hash = manifest_hash(product_sheet_manifest(template_version=DEFAULT_TEMPLATE_VERSION))
    assert job.dedupe_key == f"consolidated_xlsx:{world['posted_run_id']}:{expected_hash}"

    result = await execute_consolidated_xlsx(
        session,
        storage,
        job,
        registry=registry,
    )
    assert result["artifact_id"]
    assert result["manifest_hash"] == expected_hash
    assert "June 2026" in result["filename"]
    assert result["filename"].endswith(".zip")

    artifact = await session.get(ExportArtifact, UUID(result["artifact_id"]))
    assert artifact is not None
    assert artifact.content_type == "application/zip"
    assert artifact.report_type == "consolidated_xlsx"

    blob = await storage.get(artifact.object_key)
    with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
        names = sorted(archive.namelist())
    assert len(names) == 18
    assert any("payslip" in n.lower() for n in names)
    assert any("advance" in n.lower() for n in names)
    for title in PRODUCT_REPORT_SHEET_TITLES.values():
        assert any(name.startswith(f"{title} - ") and name.endswith(".xlsx") for name in names)

    reused = await execute_consolidated_xlsx(
        session,
        storage,
        job,
        registry=registry,
    )
    assert reused["reused"] is True
    assert reused["artifact_id"] == result["artifact_id"]
