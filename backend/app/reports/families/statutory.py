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

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.reports.posted_run import (
    DEFAULT_CONTENT_TYPES,
    DEFAULT_FILENAME_PATTERN,
    ZERO,
    load_result_rows,
    money,
    month_end,
    period_label,
    require_posted_run,
    resolve_profile_as_of,
)

REPORT_TYPE_INCOME_TAX = "income_tax_schedule"
REPORT_TYPE_PROFESSIONAL_TAX = "professional_tax_schedule"
REPORT_TYPE_GIS = "gis_schedule"

IncomeTaxScheduleDTO = ReportDTO
ProfessionalTaxScheduleDTO = ReportDTO
GisScheduleDTO = ReportDTO


_INCOME_TAX = "INCOME_TAX"
_PROFESSIONAL_TAX = "PROFESSIONAL_TAX"
_GIS = "GIS"

FILENAME_PATTERN = DEFAULT_FILENAME_PATTERN


def _line_amount_for_code(lines: list[Any], code: str) -> Decimal | None:
    """Return summed posted amount for ``code``, or None when no line exists."""
    total = ZERO
    found = False
    for line in lines:
        if str(line["component_code"]) != code:
            continue
        found = True
        total += money(line["amount"])
    if not found:
        return None
    return money(total)


def _pt_slab_note(amounts: list[Decimal], liable_count: int) -> str:
    """Display-only note from distinct posted PT amounts (not used for computation)."""
    unique = sorted({money(a) for a in amounts})
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
        _run, version, period, org = await require_posted_run(session, ctx)
        as_of = month_end(period.period_year, period.period_month)
        packed = await load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _income_tax_columns()
        rows: list[tuple[Any, ...]] = []
        tax_total = ZERO

        for item in packed:
            result = item["result"]
            tax = _line_amount_for_code(item["lines"], _INCOME_TAX)
            if tax is None:
                continue
            profile = await resolve_profile_as_of(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            # Full PAN — masking is intentionally not applied (tax-authority schedule).
            pan = str(profile["pan"] or "") if profile is not None else ""
            gross = money(result["gross_total"])
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

        totals: tuple[Any, ...] = ("TOTAL", None, None, None, money(tax_total))

        return ReportDTO(
            report_type=REPORT_TYPE_INCOME_TAX,
            template_version=ctx.template_version,
            title="Income Tax schedule",
            organization_name=org.name,
            subtitle=period_label(period.period_year, period.period_month),
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
        _run, version, period, org = await require_posted_run(session, ctx)
        as_of = month_end(period.period_year, period.period_month)
        packed = await load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _professional_tax_columns()
        rows: list[tuple[Any, ...]] = []
        pt_total = ZERO
        posted_amounts: list[Decimal] = []

        for item in packed:
            result = item["result"]
            pt = _line_amount_for_code(item["lines"], _PROFESSIONAL_TAX)
            if pt is None:
                continue
            profile = await resolve_profile_as_of(
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
        totals: tuple[Any, ...] = ("TOTAL", None, money(pt_total))
        slab_note = _pt_slab_note(posted_amounts, liable_count)

        return ReportDTO(
            report_type=REPORT_TYPE_PROFESSIONAL_TAX,
            template_version=ctx.template_version,
            title="Professional Tax schedule",
            organization_name=org.name,
            subtitle=period_label(period.period_year, period.period_month),
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
        _run, version, period, org = await require_posted_run(session, ctx)
        as_of = month_end(period.period_year, period.period_month)
        packed = await load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _gis_columns()
        rows: list[tuple[Any, ...]] = []
        gis_total = ZERO

        for item in packed:
            result = item["result"]
            gis = _line_amount_for_code(item["lines"], _GIS)
            if gis is None:
                continue
            profile = await resolve_profile_as_of(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            rows.append((str(result["employee_number"]), name, gis))
            gis_total += gis

        totals: tuple[Any, ...] = ("TOTAL", None, money(gis_total))

        return ReportDTO(
            report_type=REPORT_TYPE_GIS,
            template_version=ctx.template_version,
            title="GIS schedule",
            organization_name=org.name,
            subtitle=period_label(period.period_year, period.period_month),
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


def statutory_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def statutory_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def statutory_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(dto)


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
