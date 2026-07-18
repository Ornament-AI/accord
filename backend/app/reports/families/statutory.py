"""Statutory remittance schedules: Income Tax, Professional Tax, and GIS.

Builders read posted run snapshots only and emit :class:`~app.reports.base.ReportDTO`
values. Amounts come from ``payroll_result_lines`` / ``payroll_employee_results``;
identity (name, PAN) is resolved from the employee profile version effective at
period month-end — the same pinned effective-dated pattern used by other report
families (ADR 0005). Versions referenced by a posted run are never mutated in
place.

**PAN policy (Income Tax schedule):** statutory schedules submitted to tax
authorities carry the **full unmasked PAN** by design. Artifact access control
(audited downloads per ADR 0009 / ADR 0010) is the protection layer — this
module intentionally does not mask PAN values.

No hardcoded statutory rates: Professional Tax and GIS amounts are the posted
line amounts. Any PT slab note is display-only, derived from those posted
amounts (never used for computation).
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.effective import select_active_version
from app.models.employees import employee_profile_versions
from app.models.identity import Organization
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.reports.base import (
    ColumnKind,
    ReportColumn,
    ReportContext,
    ReportDTO,
    ReportRegistry,
    TableSection,
    to_json as base_to_json,
)
from app.reports.excel import to_excel as base_to_excel
from app.reports.formatting import format_inr
from app.reports.pdf import to_pdf as base_to_pdf

REPORT_TYPE_INCOME_TAX = "income_tax_schedule"
REPORT_TYPE_PROFESSIONAL_TAX = "professional_tax_schedule"
REPORT_TYPE_GIS = "gis_schedule"

IncomeTaxScheduleDTO = ReportDTO
ProfessionalTaxScheduleDTO = ReportDTO
GisScheduleDTO = ReportDTO

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")

_INCOME_TAX = "INCOME_TAX"
_PROFESSIONAL_TAX = "PROFESSIONAL_TAX"
_GIS = "GIS"

DEFAULT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _period_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


async def _require_posted_run(
    session: AsyncSession,
    ctx: ReportContext,
) -> tuple[PayrollRun, Any, PayrollPeriod, Organization]:
    run = await session.get(PayrollRun, ctx.posted_run_id)
    if run is None or run.organization_id != ctx.organization_id:
        raise NotFoundError("Payroll run not found.")
    if run.status != "posted":
        raise ConflictError(
            f"Payroll run must be posted to generate reports; found {run.status!r}.",
            details={"run_id": str(run.id), "status": run.status},
        )
    if run.current_version_id is None:
        raise ConflictError("Posted payroll run has no current_version_id.")

    version = (
        (
            await session.execute(
                sa.select(payroll_run_versions).where(
                    payroll_run_versions.c.id == run.current_version_id,
                    payroll_run_versions.c.organization_id == ctx.organization_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise ConflictError("Posted payroll run version not found.")

    period = await session.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != ctx.organization_id:
        raise NotFoundError("Payroll period not found.")

    org = await session.get(Organization, ctx.organization_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    return run, version, period, org


async def _load_result_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
    run_version_id: UUID,
) -> list[dict[str, Any]]:
    results = (
        (
            await session.execute(
                sa.select(payroll_employee_results)
                .where(
                    payroll_employee_results.c.organization_id == organization_id,
                    payroll_employee_results.c.run_version_id == run_version_id,
                )
                .order_by(payroll_employee_results.c.employee_number)
            )
        )
        .mappings()
        .all()
    )
    if not results:
        return []

    result_ids = [row["id"] for row in results]
    lines = (
        (
            await session.execute(
                sa.select(payroll_result_lines)
                .where(
                    payroll_result_lines.c.organization_id == organization_id,
                    payroll_result_lines.c.employee_result_id.in_(result_ids),
                )
                .order_by(
                    payroll_result_lines.c.employee_result_id,
                    payroll_result_lines.c.sequence,
                )
            )
        )
        .mappings()
        .all()
    )
    lines_by_result: dict[UUID, list[Any]] = {rid: [] for rid in result_ids}
    for line in lines:
        lines_by_result[line["employee_result_id"]].append(line)

    return [{"result": row, "lines": lines_by_result.get(row["id"], [])} for row in results]


def _line_amount_for_code(lines: list[Any], code: str) -> Decimal | None:
    """Return summed posted amount for ``code``, or None when no line exists."""
    total = _ZERO
    found = False
    for line in lines:
        if str(line["component_code"]) != code:
            continue
        found = True
        total += _money(line["amount"])
    if not found:
        return None
    return _money(total)


async def _resolve_profile(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> dict[str, Any] | None:
    # Posted runs pin immutable effective-dated version ids (ADR 0005). Resolving
    # identity fields as-of period end is safe: versions are never mutated in place.
    return (
        (
            await session.execute(
                select_active_version(
                    employee_profile_versions,
                    header_id=employee_id,
                    organization_id=organization_id,
                    on_date=as_of,
                )
            )
        )
        .mappings()
        .one_or_none()
    )


def _pt_slab_note(amounts: list[Decimal], liable_count: int) -> str:
    """Display-only note from distinct posted PT amounts (not used for computation)."""
    unique = sorted({_money(a) for a in amounts})
    if not unique:
        return f"Professional tax slab note: no posted amounts; liable employees: {liable_count}."
    amounts_display = ", ".join(format_inr(a) for a in unique)
    return (
        f"Professional tax slab note (display only, from posted line amounts): "
        f"{amounts_display}; liable employees: {liable_count}."
    )


def _income_tax_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="pan", header="PAN", kind=ColumnKind.TEXT),
        ReportColumn(key="gross", header="Gross", kind=ColumnKind.MONEY),
        ReportColumn(key="income_tax", header="Income Tax", kind=ColumnKind.MONEY),
    )


def _professional_tax_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="professional_tax", header="Professional Tax", kind=ColumnKind.MONEY),
    )


def _gis_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="gis", header="GIS", kind=ColumnKind.MONEY),
    )


class IncomeTaxScheduleBuilder:
    """Build the Income Tax / TDS remittance schedule from a posted run.

    Emits the full unmasked PAN for each row (see module docstring PAN policy).
    """

    async def build(self, session: AsyncSession, ctx: ReportContext) -> IncomeTaxScheduleDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _income_tax_columns()
        rows: list[tuple[Any, ...]] = []
        tax_total = _ZERO

        for item in packed:
            result = item["result"]
            tax = _line_amount_for_code(item["lines"], _INCOME_TAX)
            if tax is None:
                continue
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            # Full PAN — masking is intentionally not applied (tax-authority schedule).
            pan = str(profile["pan"] or "") if profile is not None else ""
            gross = _money(result["gross_total"])
            rows.append(
                (
                    str(result["employee_number"]),
                    name,
                    pan,
                    gross,
                    tax,
                )
            )
            tax_total += tax

        totals: tuple[Any, ...] = ("TOTAL", None, None, None, _money(tax_total))

        return ReportDTO(
            report_type=REPORT_TYPE_INCOME_TAX,
            template_version=ctx.template_version,
            title="Income Tax schedule",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Income Tax",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
        )


class ProfessionalTaxScheduleBuilder:
    """Build the Professional Tax remittance schedule from a posted run.

    Row amounts are the actual posted ``PROFESSIONAL_TAX`` line values — never a
    hardcoded slab rate. The slab note section is display-only.
    """

    async def build(self, session: AsyncSession, ctx: ReportContext) -> ProfessionalTaxScheduleDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _professional_tax_columns()
        rows: list[tuple[Any, ...]] = []
        pt_total = _ZERO
        posted_amounts: list[Decimal] = []

        for item in packed:
            result = item["result"]
            pt = _line_amount_for_code(item["lines"], _PROFESSIONAL_TAX)
            if pt is None:
                continue
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            rows.append((str(result["employee_number"]), name, pt))
            pt_total += pt
            posted_amounts.append(pt)

        liable_count = len(rows)
        totals: tuple[Any, ...] = ("TOTAL", None, _money(pt_total))
        slab_note = _pt_slab_note(posted_amounts, liable_count)

        return ReportDTO(
            report_type=REPORT_TYPE_PROFESSIONAL_TAX,
            template_version=ctx.template_version,
            title="Professional Tax schedule",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Professional Tax",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
                TableSection(
                    title="Slab note",
                    columns=(ReportColumn(key="note", header="Note", kind=ColumnKind.TEXT),),
                    rows=((slab_note,),),
                ),
            ),
        )


class GisScheduleBuilder:
    """Build the GIS remittance schedule from a posted run (mixed slab amounts)."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> GisScheduleDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _gis_columns()
        rows: list[tuple[Any, ...]] = []
        gis_total = _ZERO

        for item in packed:
            result = item["result"]
            gis = _line_amount_for_code(item["lines"], _GIS)
            if gis is None:
                continue
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            rows.append((str(result["employee_number"]), name, gis))
            gis_total += gis

        totals: tuple[Any, ...] = ("TOTAL", None, _money(gis_total))

        return ReportDTO(
            report_type=REPORT_TYPE_GIS,
            template_version=ctx.template_version,
            title="GIS schedule",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="GIS",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
        )


income_tax_builder = IncomeTaxScheduleBuilder()
professional_tax_builder = ProfessionalTaxScheduleBuilder()
gis_builder = GisScheduleBuilder()


def _dto_for_pdf(dto: ReportDTO) -> ReportDTO:
    """Fold ``section.totals`` into rows for PDF rendering.

    The generic ``pdf.to_pdf`` path currently omits ``widths`` when drawing the
    totals row (TypeError). Until that writer is fixed, PDF formatters append
    the totals tuple as a final body row so schedule footers still print.
    """
    sections: list[TableSection] = []
    for section in dto.sections:
        if section.totals is None:
            sections.append(section)
            continue
        sections.append(
            TableSection(
                title=section.title,
                columns=section.columns,
                rows=(*section.rows, section.totals),
                totals=None,
            )
        )
    return ReportDTO(
        report_type=dto.report_type,
        template_version=dto.template_version,
        title=dto.title,
        organization_name=dto.organization_name,
        subtitle=dto.subtitle,
        sections=tuple(sections),
    )


def statutory_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def statutory_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def statutory_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(_dto_for_pdf(dto))


def register(registry: ReportRegistry) -> None:
    """Register Income Tax, Professional Tax, and GIS schedules on ``registry``."""
    for report_type, builder in (
        (REPORT_TYPE_INCOME_TAX, income_tax_builder),
        (REPORT_TYPE_PROFESSIONAL_TAX, professional_tax_builder),
        (REPORT_TYPE_GIS, gis_builder),
    ):
        registry.register(
            report_type,
            builder=builder,
            to_json=statutory_to_json,
            to_excel=statutory_to_excel,
            to_pdf=statutory_to_pdf,
            content_types=DEFAULT_CONTENT_TYPES,
            filename_pattern=FILENAME_PATTERN,
        )
