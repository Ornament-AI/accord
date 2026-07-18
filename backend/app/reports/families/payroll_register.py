"""Payroll register report family: Pay Bill and Treasury Face.

Builders read posted run snapshots and emit :class:`~app.reports.base.ReportDTO`
values. Formatters are thin wrappers over the generic JSON / Excel / PDF writers.
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
from app.models.employees import employee_posting_versions, employee_profile_versions
from app.models.identity import Organization
from app.models.org_structure import Post
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.reports import ReportConfiguration
from app.reports.amount_in_words import amount_in_words
from app.reports.base import (
    ColumnKind,
    ReportColumn,
    ReportContext,
    ReportDTO,
    TableSection,
    to_json as base_to_json,
)
from app.reports.excel import to_excel as base_to_excel
from app.reports.pdf import to_pdf as base_to_pdf

# Report type strings for orchestrator registration.
REPORT_TYPE_PAY_BILL = "pay_bill"
REPORT_TYPE_TREASURY_FACE = "treasury_face"

PayBillDTO = ReportDTO
TreasuryFaceDTO = ReportDTO

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")

_EARNING_CODES = (
    "BASIC",
    "DA",
    "HRA",
    "TRANSPORT",
    "OTHER_ALLOWANCE",
)

# Register deduction columns → posted result-line component code(s).
_DEDUCTION_COLUMN_CODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gpf", ("GPF_SUBSCRIPTION",)),
    ("nps_employee", ("NPS_EMPLOYEE",)),
    ("epf_employee", ("EPF_EMPLOYEE",)),
    ("income_tax", ("INCOME_TAX",)),
    ("pt", ("PROFESSIONAL_TAX",)),
    ("gis", ("GIS",)),
    ("hba", ("HBA_INSTALLMENT",)),
    ("accommodation", ("ACCOMMODATION_LICENSE_FEE",)),
    ("transfers", ("NPS_EMPLOYER_TRANSFER", "EPF_EMPLOYER_TRANSFER")),
)

DEFAULT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
PAY_BILL_FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"
TREASURY_FACE_FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"


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

    out: list[dict[str, Any]] = []
    for row in results:
        out.append({"result": row, "lines": lines_by_result.get(row["id"], [])})
    return out


async def _resolve_name_and_designation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> tuple[str, str]:
    # ADR 0005: posted runs pin immutable effective-dated version ids. Resolving
    # name/designation as-of period end is safe because versions referenced by a
    # posted run are never mutated in place — only superseded by a later clip.
    profile = (
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
    name = str(profile["name"]) if profile is not None else ""

    posting = (
        (
            await session.execute(
                select_active_version(
                    employee_posting_versions,
                    header_id=employee_id,
                    organization_id=organization_id,
                    on_date=as_of,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    designation = ""
    if posting is not None:
        post = await session.get(Post, posting["post_id"])
        if post is not None and post.organization_id == organization_id:
            designation = post.designation

    return name, designation


def _line_amount_by_code(lines: list[Any]) -> dict[str, Decimal]:
    amounts: dict[str, Decimal] = {}
    for line in lines:
        code = str(line["component_code"])
        # Informational FOREGONE_HRA is outside register money columns.
        trace = line["trace"] or {}
        if trace.get("classification") == "informational" or code == "FOREGONE_HRA":
            continue
        amounts[code] = amounts.get(code, _ZERO) + _money(line["amount"])
    return amounts


def _sum_codes(amounts: dict[str, Decimal], codes: tuple[str, ...]) -> Decimal:
    total = _ZERO
    for code in codes:
        total += amounts.get(code, _ZERO)
    return total


def _pay_bill_columns() -> tuple[ReportColumn, ...]:
    cols: list[ReportColumn] = [
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="designation", header="Designation", kind=ColumnKind.TEXT),
    ]
    for code in _EARNING_CODES:
        cols.append(ReportColumn(key=code.lower(), header=code, kind=ColumnKind.MONEY))
    cols.append(ReportColumn(key="earnings_total", header="Earnings Total", kind=ColumnKind.MONEY))
    for key, _codes in _DEDUCTION_COLUMN_CODES:
        header = {
            "gpf": "GPF",
            "nps_employee": "NPS Employee",
            "epf_employee": "EPF Employee",
            "income_tax": "Income Tax",
            "pt": "PT",
            "gis": "GIS",
            "hba": "HBA",
            "accommodation": "Accommodation",
            "transfers": "Transfers",
        }[key]
        cols.append(ReportColumn(key=key, header=header, kind=ColumnKind.MONEY))
    cols.append(
        ReportColumn(key="deductions_total", header="Deductions Total", kind=ColumnKind.MONEY)
    )
    cols.append(ReportColumn(key="net_payable", header="Net Payable", kind=ColumnKind.MONEY))
    return tuple(cols)


class PayBillBuilder:
    """Build the Pay Bill register DTO from a posted run snapshot."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> PayBillDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        columns = _pay_bill_columns()
        rows: list[tuple[Any, ...]] = []
        footer_earnings = [_ZERO] * len(_EARNING_CODES)
        footer_earnings_total = _ZERO
        footer_deductions = [_ZERO] * len(_DEDUCTION_COLUMN_CODES)
        footer_deductions_total = _ZERO
        footer_net = _ZERO

        for item in packed:
            result = item["result"]
            amounts = _line_amount_by_code(item["lines"])
            name, designation = await _resolve_name_and_designation(
                session,
                organization_id=ctx.organization_id,
                employee_id=result["employee_id"],
                as_of=as_of,
            )
            earning_vals = [_money(amounts.get(code, _ZERO)) for code in _EARNING_CODES]
            earnings_total = _money(result["earnings_total"])
            deduction_vals = [_sum_codes(amounts, codes) for _key, codes in _DEDUCTION_COLUMN_CODES]
            deductions_total = _money(result["deductions_total"])
            net_payable = _money(result["net_payable"])

            rows.append(
                (
                    str(result["employee_number"]),
                    name,
                    designation,
                    *earning_vals,
                    earnings_total,
                    *deduction_vals,
                    deductions_total,
                    net_payable,
                )
            )

            for idx, val in enumerate(earning_vals):
                footer_earnings[idx] += val
            footer_earnings_total += earnings_total
            for idx, val in enumerate(deduction_vals):
                footer_deductions[idx] += val
            footer_deductions_total += deductions_total
            footer_net += net_payable

        totals: tuple[Any, ...] = (
            "TOTAL",
            None,
            None,
            *(_money(v) for v in footer_earnings),
            _money(footer_earnings_total),
            *(_money(v) for v in footer_deductions),
            _money(footer_deductions_total),
            _money(footer_net),
        )

        net_words = amount_in_words(_money(footer_net))
        snapshot_note = (
            f"engine_version={version['engine_version']}; template_version={ctx.template_version}"
        )

        return ReportDTO(
            report_type=REPORT_TYPE_PAY_BILL,
            template_version=ctx.template_version,
            title="Payroll Register — Pay Bill",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Register",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
                TableSection(
                    title="Amount in words",
                    columns=(
                        ReportColumn(key="label", header="Label", kind=ColumnKind.TEXT),
                        ReportColumn(key="value", header="Value", kind=ColumnKind.TEXT),
                    ),
                    rows=(("Net payable", net_words),),
                ),
                TableSection(
                    title="Rate / rule snapshot",
                    columns=(ReportColumn(key="note", header="Note", kind=ColumnKind.TEXT),),
                    rows=((snapshot_note,),),
                ),
            ),
        )


class TreasuryFaceBuilder:
    """Build the Treasury Face summary DTO from a posted run snapshot."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> TreasuryFaceDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )

        earnings_total = _ZERO
        employer_share = _ZERO
        ag_deductions = _ZERO
        treasury_deductions = _ZERO
        external_recoveries = _ZERO
        net_payable = _ZERO

        for item in packed:
            result = item["result"]
            earnings_total += _money(result["earnings_total"])
            employer_share += _money(result["employer_contribution_total"])
            net_payable += _money(result["net_payable"])
            for line in item["lines"]:
                code = str(line["component_code"])
                trace = line["trace"] or {}
                if trace.get("classification") == "informational" or code == "FOREGONE_HRA":
                    continue
                classification = str(line["classification"])
                amount = _money(line["amount"])
                if classification == "ag_deduction":
                    ag_deductions += amount
                elif classification == "treasury_deduction":
                    treasury_deductions += amount
                elif classification == "external_recovery":
                    external_recoveries += amount

        gross_bill = _money(earnings_total + employer_share)
        total_deductions = _money(ag_deductions + treasury_deductions + external_recoveries)
        employer_share = _money(employer_share)
        net_payable = _money(net_payable)
        ag_deductions = _money(ag_deductions)
        treasury_deductions = _money(treasury_deductions)
        external_recoveries = _money(external_recoveries)

        signatory_rows = await _load_signatory_rows(session, organization_id=ctx.organization_id)

        return ReportDTO(
            report_type=REPORT_TYPE_TREASURY_FACE,
            template_version=ctx.template_version,
            title="Payroll Register — Treasury Face",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Treasury Face Summary",
                    columns=(
                        ReportColumn(key="particulars", header="Particulars", kind=ColumnKind.TEXT),
                        ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                    ),
                    rows=(
                        ("Gross bill", gross_bill),
                        ("AG deductions", ag_deductions),
                        ("Treasury deductions", treasury_deductions),
                        ("External recoveries", external_recoveries),
                        ("Total deductions", total_deductions),
                        ("Employer share", employer_share),
                        ("Net payable", net_payable),
                    ),
                ),
                TableSection(
                    title="Amount in words",
                    columns=(
                        ReportColumn(key="label", header="Label", kind=ColumnKind.TEXT),
                        ReportColumn(key="value", header="Value", kind=ColumnKind.TEXT),
                    ),
                    rows=(
                        ("Gross bill", amount_in_words(gross_bill)),
                        ("Net payable", amount_in_words(net_payable)),
                    ),
                ),
                TableSection(
                    title="Signatories",
                    columns=(
                        ReportColumn(key="role", header="Role", kind=ColumnKind.TEXT),
                        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
                    ),
                    rows=signatory_rows,
                ),
            ),
        )


async def _load_signatory_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> tuple[tuple[Any, ...], ...]:
    row = (
        await session.execute(
            sa.select(ReportConfiguration).where(
                ReportConfiguration.organization_id == organization_id,
                ReportConfiguration.key == "signatories",
            )
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return ()
    out: list[tuple[Any, ...]] = []
    for key, item in row.value.items():
        if isinstance(item, dict):
            role = str(item.get("role") or key)
            name = str(item.get("name") or "")
            out.append((role, name))
        else:
            out.append((str(key), str(item)))
    return tuple(out)


# Module-level builder instances for registry wiring.
pay_bill_builder = PayBillBuilder()
treasury_face_builder = TreasuryFaceBuilder()


def pay_bill_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def pay_bill_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def pay_bill_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(dto)


def treasury_face_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def treasury_face_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def treasury_face_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(dto)
