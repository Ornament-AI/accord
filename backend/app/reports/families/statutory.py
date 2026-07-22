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
from app.reports.snapshots import load_report_snapshot

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


def _v3_metadata(snapshot: dict[str, Any] | None, *, canonical: bool) -> dict[str, Any]:
    if snapshot is None or not canonical:
        return {}
    return {
        "report_profile": dict(snapshot.get("report_profile") or {}),
        "run_metadata": dict(snapshot.get("run_metadata") or {}),
    }


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


def _income_tax_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    if canonical:
        return (
            ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
            ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
            ReportColumn(key="designation", header="Designation", kind=ColumnKind.TEXT),
            ReportColumn(key="pan", header="PAN", kind=ColumnKind.TEXT),
            ReportColumn(key="financial_year", header="Financial Year", kind=ColumnKind.TEXT),
            ReportColumn(key="income_tax", header="Income Tax", kind=ColumnKind.MONEY),
        )
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="pan", header="PAN", kind=ColumnKind.TEXT),
        ReportColumn(key="gross", header="Gross", kind=ColumnKind.MONEY),
        ReportColumn(key="income_tax", header="Income Tax", kind=ColumnKind.MONEY),
    )


def _professional_tax_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    columns = [
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
    ]
    if canonical:
        columns.append(ReportColumn(key="designation", header="Designation", kind=ColumnKind.TEXT))
    columns.append(
        ReportColumn(key="professional_tax", header="Professional Tax", kind=ColumnKind.MONEY),
    )
    return tuple(columns)


def _gis_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    columns = [
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
    ]
    if canonical:
        columns.append(ReportColumn(key="designation", header="Designation", kind=ColumnKind.TEXT))
    columns.append(
        ReportColumn(key="gis", header="GIS", kind=ColumnKind.MONEY),
    )
    return tuple(columns)


def _financial_year(year: int, month: int) -> str:
    start = year if month >= 4 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


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
        snapshot = (
            await load_report_snapshot(
                session,
                organization_id=ctx.organization_id,
                run_version_id=version["id"],
            )
            if ctx.template_version in {"v2", "v3"}
            else None
        )
        identities = snapshot.get("employee_identity") or {} if snapshot is not None else {}
        canonical = ctx.template_version == "v3"
        columns = _income_tax_columns(canonical=canonical)
        rows: list[tuple[Any, ...]] = []
        tax_total = ZERO

        for item in packed:
            result = item["result"]
            tax = _line_amount_for_code(item["lines"], _INCOME_TAX)
            if tax is None:
                continue
            profile = (
                identities.get(str(result["employee_id"]))
                if snapshot is not None
                else await resolve_profile_as_of(
                    session,
                    organization_id=ctx.organization_id,
                    employee_id=result["employee_id"],
                    as_of=as_of,
                )
            )
            name = str(profile["name"]) if profile is not None else ""
            # Full PAN — masking is intentionally not applied (tax-authority schedule).
            pan = str(profile["pan"] or "") if profile is not None else ""
            if canonical:
                rows.append(
                    (
                        str(result["employee_number"]),
                        name,
                        str(profile.get("designation") or "") if profile is not None else "",
                        pan,
                        _financial_year(period.period_year, period.period_month),
                        tax,
                    )
                )
            else:
                rows.append(
                    (
                        str(result["employee_number"]),
                        name,
                        pan,
                        money(result["gross_total"]),
                        tax,
                    )
                )
            tax_total += tax

        totals: tuple[Any, ...] = ("TOTAL",) + (None,) * (len(columns) - 2) + (money(tax_total),)

        return ReportDTO(
            report_type=REPORT_TYPE_INCOME_TAX,
            template_version=ctx.template_version,
            title="Income Tax schedule",
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
            subtitle=period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Income Tax",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
            metadata=_v3_metadata(snapshot, canonical=canonical),
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
        snapshot = (
            await load_report_snapshot(
                session,
                organization_id=ctx.organization_id,
                run_version_id=version["id"],
            )
            if ctx.template_version in {"v2", "v3"}
            else None
        )
        identities = snapshot.get("employee_identity") or {} if snapshot is not None else {}
        canonical = ctx.template_version == "v3"
        columns = _professional_tax_columns(canonical=canonical)
        rows: list[tuple[Any, ...]] = []
        pt_total = ZERO
        posted_amounts: list[Decimal] = []

        for item in packed:
            result = item["result"]
            pt = _line_amount_for_code(item["lines"], _PROFESSIONAL_TAX)
            if pt is None:
                continue
            profile = (
                identities.get(str(result["employee_id"]))
                if snapshot is not None
                else await resolve_profile_as_of(
                    session,
                    organization_id=ctx.organization_id,
                    employee_id=result["employee_id"],
                    as_of=as_of,
                )
            )
            name = str(profile["name"]) if profile is not None else ""
            row: tuple[Any, ...] = (str(result["employee_number"]), name)
            if canonical:
                row += (str(profile.get("designation") or "") if profile is not None else "",)
            rows.append(row + (pt,))
            pt_total += pt
            posted_amounts.append(pt)

        liable_count = len(rows)
        totals: tuple[Any, ...] = ("TOTAL",) + (None,) * (len(columns) - 2) + (money(pt_total),)
        slab_note = _pt_slab_note(posted_amounts, liable_count)

        return ReportDTO(
            report_type=REPORT_TYPE_PROFESSIONAL_TAX,
            template_version=ctx.template_version,
            title="Professional Tax schedule",
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
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
            metadata=_v3_metadata(snapshot, canonical=canonical),
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
        snapshot = (
            await load_report_snapshot(
                session,
                organization_id=ctx.organization_id,
                run_version_id=version["id"],
            )
            if ctx.template_version in {"v2", "v3"}
            else None
        )
        identities = snapshot.get("employee_identity") or {} if snapshot is not None else {}
        canonical = ctx.template_version == "v3"
        columns = _gis_columns(canonical=canonical)
        rows: list[tuple[Any, ...]] = []
        gis_total = ZERO

        for item in packed:
            result = item["result"]
            gis = _line_amount_for_code(item["lines"], _GIS)
            if gis is None:
                continue
            profile = (
                identities.get(str(result["employee_id"]))
                if snapshot is not None
                else await resolve_profile_as_of(
                    session,
                    organization_id=ctx.organization_id,
                    employee_id=result["employee_id"],
                    as_of=as_of,
                )
            )
            name = str(profile["name"]) if profile is not None else ""
            row: tuple[Any, ...] = (str(result["employee_number"]), name)
            if canonical:
                row += (str(profile.get("designation") or "") if profile is not None else "",)
            rows.append(row + (gis,))
            gis_total += gis

        totals: tuple[Any, ...] = ("TOTAL",) + (None,) * (len(columns) - 2) + (money(gis_total),)

        return ReportDTO(
            report_type=REPORT_TYPE_GIS,
            template_version=ctx.template_version,
            title="GIS schedule",
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
            subtitle=period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="GIS",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
            metadata=_v3_metadata(snapshot, canonical=canonical),
        )


income_tax_builder = IncomeTaxScheduleBuilder()
professional_tax_builder = ProfessionalTaxScheduleBuilder()
gis_builder = GisScheduleBuilder()


def statutory_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def statutory_to_excel(dto: ReportDTO) -> bytes:
    if dto.template_version == "v3":
        from app.reports.canonical_schedules import REPORT_SHEET_NAMES, canonical_schedule_to_excel

        if dto.report_type in REPORT_SHEET_NAMES:
            return canonical_schedule_to_excel(dto)
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
