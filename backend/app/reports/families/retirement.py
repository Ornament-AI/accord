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

from decimal import Decimal
from typing import Any, Literal

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

REPORT_TYPE_GPF_MUMBAI = "gpf_mumbai_schedule"
REPORT_TYPE_GPF_NAGPUR = "gpf_nagpur_schedule"
REPORT_TYPE_NPS = "nps_contribution_schedule"

GpfJurisdiction = Literal["mumbai", "nagpur"]

GpfMumbaiScheduleDTO = ReportDTO
GpfNagpurScheduleDTO = ReportDTO
NpsContributionScheduleDTO = ReportDTO


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

FILENAME_PATTERN = DEFAULT_FILENAME_PATTERN


def _line_amounts(lines: list[Any]) -> dict[str, Decimal]:
    amounts: dict[str, Decimal] = {}
    for line in lines:
        code = str(line["component_code"])
        amounts[code] = amounts.get(code, ZERO) + money(line["amount"])
    return amounts


def _gpf_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    columns = [
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
    ]
    if canonical:
        columns.append(ReportColumn(key="designation", header="Designation", kind=ColumnKind.TEXT))
        columns.append(ReportColumn(key="basic_pay", header="Basic Pay", kind=ColumnKind.MONEY))
    columns.extend(
        (
            ReportColumn(key="gpf_account_number", header="GPF Account No.", kind=ColumnKind.TEXT),
            ReportColumn(key="subscription", header="GPF Subscription", kind=ColumnKind.MONEY),
            ReportColumn(
                key="advance_recovery", header="GPF Advance Recovery", kind=ColumnKind.MONEY
            ),
        )
    )
    return tuple(columns)


def _nps_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    if canonical:
        return (
            ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
            ReportColumn(key="pension_account", header="Pension Account No.", kind=ColumnKind.TEXT),
            ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
            ReportColumn(key="sevarth_id", header="Sevarth ID", kind=ColumnKind.TEXT),
            ReportColumn(key="pran", header="PRAN", kind=ColumnKind.TEXT),
            ReportColumn(key="month", header="Month", kind=ColumnKind.TEXT),
            ReportColumn(key="basic_pay", header="Basic Pay", kind=ColumnKind.MONEY),
            ReportColumn(key="dearness_allowance", header="DA", kind=ColumnKind.MONEY),
            ReportColumn(
                key="employee_contribution", header="Employee Contribution", kind=ColumnKind.MONEY
            ),
            ReportColumn(
                key="employer_contribution", header="Employer Contribution", kind=ColumnKind.MONEY
            ),
            ReportColumn(key="remarks", header="Remarks", kind=ColumnKind.TEXT),
        )
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
        columns = _gpf_columns(canonical=canonical)
        rows: list[tuple[Any, ...]] = []
        total_subscription = ZERO
        total_advance = ZERO

        for item in packed:
            result = item["result"]
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
            if profile is None:
                continue
            if str(profile["retirement_regime"]) != "gpf":
                continue
            if str(profile["gpf_jurisdiction"] or "") != self.jurisdiction:
                continue

            amounts = _line_amounts(item["lines"])
            subscription = money(amounts.get(_GPF_SUBSCRIPTION, ZERO))
            advance = money(amounts.get(_GPF_ADVANCE, ZERO))
            account = str(profile["gpf_account_number"] or "")
            name = str(profile["name"] or "")

            row: tuple[Any, ...] = (str(result["employee_number"]), name)
            if canonical:
                row += (
                    str(profile.get("designation") or ""),
                    money(amounts.get("BASIC", ZERO)),
                )
            rows.append(row + (account, subscription, advance))
            total_subscription += subscription
            total_advance += advance

        totals: tuple[Any, ...] = (
            ("TOTAL",)
            + (None,) * (len(columns) - 3)
            + (
                money(total_subscription),
                money(total_advance),
            )
        )

        return ReportDTO(
            report_type=self.report_type,
            template_version=ctx.template_version,
            title=_GPF_TITLES[self.jurisdiction],
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
            subtitle=period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title=_GPF_SECTION_TITLES[self.jurisdiction],
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
            metadata=(
                {
                    "report_profile": dict(snapshot.get("report_profile") or {}),
                    "run_metadata": dict(snapshot.get("run_metadata") or {}),
                }
                if snapshot is not None and canonical
                else {}
            ),
        )


class NpsContributionScheduleBuilder:
    """Build the NPS contribution schedule (NPS employees only; EPF excluded)."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> ReportDTO:
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
        columns = _nps_columns(canonical=canonical)
        rows: list[tuple[Any, ...]] = []
        total_employee = ZERO
        total_employer = ZERO
        total_combined = ZERO

        for item in packed:
            result = item["result"]
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
            if profile is None:
                continue
            # Explicit regime gate: EPF (and GPF) must never appear on this schedule.
            if str(profile["retirement_regime"]) != "nps":
                continue

            amounts = _line_amounts(item["lines"])
            employee_amt = money(amounts.get(_NPS_EMPLOYEE, ZERO))
            employer_amt = money(amounts.get(_NPS_EMPLOYER, ZERO))
            row_total = money(employee_amt + employer_amt)
            pran = str(profile["pran"] or "")
            name = str(profile["name"] or "")

            if canonical:
                rows.append(
                    (
                        str(result["employee_number"]),
                        str(profile.get("pension_account") or ""),
                        name,
                        str(profile.get("sevarth_id") or ""),
                        pran,
                        period_label(period.period_year, period.period_month),
                        money(amounts.get("BASIC", ZERO)),
                        money(amounts.get("DA", ZERO)),
                        employee_amt,
                        employer_amt,
                        str(profile.get("payroll_export_remark") or ""),
                    )
                )
            else:
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
            ("TOTAL",) + (None,) * 7 + (money(total_employee), money(total_employer), None)
            if canonical
            else (
                "TOTAL",
                None,
                None,
                money(total_employee),
                money(total_employer),
                money(total_combined),
            )
        )

        return ReportDTO(
            report_type=REPORT_TYPE_NPS,
            template_version=ctx.template_version,
            title="NPS contribution schedule",
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
            subtitle=period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="NPS Contributions",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
            metadata=(
                {
                    "report_profile": dict(snapshot.get("report_profile") or {}),
                    "run_metadata": dict(snapshot.get("run_metadata") or {}),
                }
                if snapshot is not None and canonical
                else {}
            ),
        )


gpf_mumbai_builder = GpfScheduleBuilder("mumbai")
gpf_nagpur_builder = GpfScheduleBuilder("nagpur")
nps_contribution_builder = NpsContributionScheduleBuilder()


def retirement_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def retirement_to_excel(dto: ReportDTO) -> bytes:
    if dto.template_version == "v3":
        from app.reports.canonical_schedules import REPORT_SHEET_NAMES, canonical_schedule_to_excel

        if dto.report_type in REPORT_SHEET_NAMES:
            return canonical_schedule_to_excel(dto)
    return base_to_excel(dto)


def retirement_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(dto)


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
