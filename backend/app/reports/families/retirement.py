"""Retirement remittance schedules: GPF (Mumbai / Nagpur) and NPS.

GPF Mumbai and GPF Nagpur are separate report kinds and must never be merged
into one schedule artifact (docs/report-specs/report-catalog.md).

NPS contribution schedule lists NPS/DCPS employees only (keyed by PRAN) and
must never include EPF members or EPF amounts.

EPF schedule is intentionally OUT OF SCOPE this release: EPF employee and
employer amounts remain on Pay Bill / payslip / employer-share lines rather
than a dedicated remittance schedule.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Literal
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
from app.reports.pdf import to_pdf as base_to_pdf

REPORT_TYPE_GPF_MUMBAI = "gpf_mumbai_schedule"
REPORT_TYPE_GPF_NAGPUR = "gpf_nagpur_schedule"
REPORT_TYPE_NPS = "nps_contribution_schedule"

GpfJurisdiction = Literal["mumbai", "nagpur"]

GpfMumbaiScheduleDTO = ReportDTO
GpfNagpurScheduleDTO = ReportDTO
NpsContributionScheduleDTO = ReportDTO

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")

_GPF_SUBSCRIPTION = "GPF_SUBSCRIPTION"
_GPF_ADVANCE = "GPF_ADVANCE_INSTALLMENT"
_NPS_EMPLOYEE = "NPS_EMPLOYEE"
_NPS_EMPLOYER = "NPS_EMPLOYER_TRANSFER"

_GPF_TITLES: dict[GpfJurisdiction, str] = {
    "mumbai": "GPF — Mumbai schedule",
    "nagpur": "GPF — Nagpur schedule",
}
_GPF_SECTION_TITLES: dict[GpfJurisdiction, str] = {
    "mumbai": "GPF Mumbai",
    "nagpur": "GPF Nagpur",
}
_GPF_REPORT_TYPES: dict[GpfJurisdiction, str] = {
    "mumbai": REPORT_TYPE_GPF_MUMBAI,
    "nagpur": REPORT_TYPE_GPF_NAGPUR,
}

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


def _line_amounts(lines: list[Any]) -> dict[str, Decimal]:
    amounts: dict[str, Decimal] = {}
    for line in lines:
        code = str(line["component_code"])
        amounts[code] = amounts.get(code, _ZERO) + _money(line["amount"])
    return amounts


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


def _gpf_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="gpf_account_number", header="GPF Account No.", kind=ColumnKind.TEXT),
        ReportColumn(key="subscription", header="GPF Subscription", kind=ColumnKind.MONEY),
        ReportColumn(key="advance_recovery", header="GPF Advance Recovery", kind=ColumnKind.MONEY),
    )


def _nps_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="pran", header="PRAN", kind=ColumnKind.TEXT),
        ReportColumn(
            key="employee_contribution", header="Employee Contribution", kind=ColumnKind.MONEY
        ),
        ReportColumn(
            key="employer_contribution", header="Employer Contribution", kind=ColumnKind.MONEY
        ),
        ReportColumn(key="total", header="Total", kind=ColumnKind.MONEY),
    )


class GpfScheduleBuilder:
    """Build a jurisdiction-scoped GPF remittance schedule from a posted run."""

    def __init__(self, jurisdiction: GpfJurisdiction) -> None:
        if jurisdiction not in _GPF_REPORT_TYPES:
            raise ValueError(f"unsupported GPF jurisdiction: {jurisdiction!r}")
        self.jurisdiction: GpfJurisdiction = jurisdiction
        self.report_type = _GPF_REPORT_TYPES[jurisdiction]

    async def build(self, session: AsyncSession, ctx: ReportContext) -> ReportDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _gpf_columns()
        rows: list[tuple[Any, ...]] = []
        total_subscription = _ZERO
        total_advance = _ZERO

        for item in packed:
            result = item["result"]
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            if profile is None:
                continue
            if str(profile["retirement_regime"]) != "gpf":
                continue
            if str(profile["gpf_jurisdiction"] or "") != self.jurisdiction:
                continue

            amounts = _line_amounts(item["lines"])
            subscription = _money(amounts.get(_GPF_SUBSCRIPTION, _ZERO))
            advance = _money(amounts.get(_GPF_ADVANCE, _ZERO))
            account = str(profile["gpf_account_number"] or "")
            name = str(profile["name"] or "")

            rows.append(
                (
                    str(result["employee_number"]),
                    name,
                    account,
                    subscription,
                    advance,
                )
            )
            total_subscription += subscription
            total_advance += advance

        totals: tuple[Any, ...] = (
            "TOTAL",
            None,
            None,
            _money(total_subscription),
            _money(total_advance),
        )

        return ReportDTO(
            report_type=self.report_type,
            template_version=ctx.template_version,
            title=_GPF_TITLES[self.jurisdiction],
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title=_GPF_SECTION_TITLES[self.jurisdiction],
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
        )


class NpsContributionScheduleBuilder:
    """Build the NPS contribution schedule (NPS employees only; EPF excluded)."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> ReportDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _nps_columns()
        rows: list[tuple[Any, ...]] = []
        total_employee = _ZERO
        total_employer = _ZERO
        total_combined = _ZERO

        for item in packed:
            result = item["result"]
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            if profile is None:
                continue
            # Explicit regime gate: EPF (and GPF) must never appear on this schedule.
            if str(profile["retirement_regime"]) != "nps":
                continue

            amounts = _line_amounts(item["lines"])
            employee_amt = _money(amounts.get(_NPS_EMPLOYEE, _ZERO))
            employer_amt = _money(amounts.get(_NPS_EMPLOYER, _ZERO))
            row_total = _money(employee_amt + employer_amt)
            pran = str(profile["pran"] or "")
            name = str(profile["name"] or "")

            rows.append(
                (
                    str(result["employee_number"]),
                    name,
                    pran,
                    employee_amt,
                    employer_amt,
                    row_total,
                )
            )
            total_employee += employee_amt
            total_employer += employer_amt
            total_combined += row_total

        totals: tuple[Any, ...] = (
            "TOTAL",
            None,
            None,
            _money(total_employee),
            _money(total_employer),
            _money(total_combined),
        )

        return ReportDTO(
            report_type=REPORT_TYPE_NPS,
            template_version=ctx.template_version,
            title="NPS contribution schedule",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="NPS Contributions",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
        )


gpf_mumbai_builder = GpfScheduleBuilder("mumbai")
gpf_nagpur_builder = GpfScheduleBuilder("nagpur")
nps_contribution_builder = NpsContributionScheduleBuilder()


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


def retirement_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def retirement_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def retirement_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(_dto_for_pdf(dto))


def register_retirement_reports(registry: ReportRegistry) -> None:
    """Register GPF Mumbai, GPF Nagpur, and NPS schedules on ``registry``."""
    for report_type, builder in (
        (REPORT_TYPE_GPF_MUMBAI, gpf_mumbai_builder),
        (REPORT_TYPE_GPF_NAGPUR, gpf_nagpur_builder),
        (REPORT_TYPE_NPS, nps_contribution_builder),
    ):
        registry.register(
            report_type,
            builder=builder,
            to_json=retirement_to_json,
            to_excel=retirement_to_excel,
            to_pdf=retirement_to_pdf,
            content_types=DEFAULT_CONTENT_TYPES,
            filename_pattern=FILENAME_PATTERN,
        )
