"""Payment report family: Bank/RTGS advice and per-employee payslips.

Builders read posted run snapshots and emit :class:`~app.reports.base.ReportDTO`
values (aliased as :data:`BankAdviceDTO` / :data:`PayslipBundleDTO`).

Bank advice rows include **full** bank account numbers and IFSC codes. Artifact
access control (ADR 0010 downloads / audit) is the protection layer — this
report intentionally does not mask payment credentials.

Payslip Excel export is intentionally skipped; use JSON preview or PDF
(one page per employee via the generic tabular renderer).
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.effective import effective_on, select_active_version
from app.models.employees import (
    employee_bank_account_versions,
    employee_posting_versions,
    employee_profile_versions,
)
from app.models.identity import Organization
from app.models.org_structure import Post
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.reports.amount_in_words import amount_in_words
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
from app.schemas.employees import mask_value

# Report type strings for orchestrator registration.
REPORT_TYPE_BANK_ADVICE = "bank_rtgs_advice"
REPORT_TYPE_PAYSLIPS = "payslips"

BankAdviceDTO = ReportDTO
PayslipBundleDTO = ReportDTO

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")

DEFAULT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
BANK_ADVICE_FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"
PAYSLIPS_FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"

_DEDUCTION_CLASSIFICATIONS = frozenset({"ag_deduction", "treasury_deduction", "external_recovery"})


class MissingPrimarySalaryAccountError(ValidationError):
    """Paid employees missing or ambiguous primary salary bank account as-of period end."""

    error_code = "missing_primary_salary_account"

    def __init__(self, employee_numbers: list[str]) -> None:
        ordered = sorted(employee_numbers)
        self.employee_numbers = tuple(ordered)
        super().__init__(
            "Paid employees missing or ambiguous primary salary bank account: "
            + ", ".join(ordered),
            details={"employee_numbers": ordered},
        )


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


async def _resolve_profile(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> Any | None:
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


async def _resolve_designation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> str:
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
    if posting is None:
        return ""
    post = await session.get(Post, posting["post_id"])
    if post is None or post.organization_id != organization_id:
        return ""
    return post.designation


async def _resolve_primary_salary_accounts(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_ids: list[UUID],
    as_of: date,
) -> dict[UUID, Any]:
    """Return exactly one primary salary account per employee id.

    Raises :class:`MissingPrimarySalaryAccountError` when any employee has zero
    or more than one primary salary account effective on ``as_of``.
    """
    if not employee_ids:
        return {}

    rows = (
        (
            await session.execute(
                sa.select(employee_bank_account_versions).where(
                    employee_bank_account_versions.c.organization_id == organization_id,
                    employee_bank_account_versions.c.header_id.in_(employee_ids),
                    effective_on(employee_bank_account_versions.c.validity, as_of),
                    employee_bank_account_versions.c.is_primary_salary.is_(True),
                )
            )
        )
        .mappings()
        .all()
    )

    by_employee: dict[UUID, list[Any]] = {eid: [] for eid in employee_ids}
    for row in rows:
        by_employee[row["header_id"]].append(row)

    # Employee numbers are resolved by the caller after this helper; we only
    # know UUIDs here. Callers map UUIDs → employee_number for the typed error.
    ambiguous_or_missing = [eid for eid, accounts in by_employee.items() if len(accounts) != 1]
    if ambiguous_or_missing:
        raise _PrimaryAccountLookupError(ambiguous_or_missing)

    return {eid: accounts[0] for eid, accounts in by_employee.items()}


class _PrimaryAccountLookupError(Exception):
    """Internal signal carrying employee UUIDs with bad primary-account cardinality."""

    def __init__(self, employee_ids: list[UUID]) -> None:
        self.employee_ids = employee_ids
        super().__init__("primary salary account cardinality error")


def _bank_advice_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="account_number", header="Account Number", kind=ColumnKind.TEXT),
        ReportColumn(key="ifsc", header="IFSC", kind=ColumnKind.TEXT),
        ReportColumn(key="net_payable", header="Net Payable", kind=ColumnKind.MONEY),
    )


def _payslip_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="line_kind", header="Kind", kind=ColumnKind.TEXT),
        ReportColumn(key="code", header="Code / Field", kind=ColumnKind.TEXT),
        ReportColumn(key="detail", header="Detail", kind=ColumnKind.TEXT),
        ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
    )


def _posted_net_payable(version: Any) -> Decimal:
    totals = version["totals"] or {}
    if "net_payable" not in totals:
        raise ConflictError("Posted run version totals missing net_payable.")
    return _money(totals["net_payable"])


class BankAdviceBuilder:
    """Build Bank/RTGS advice DTO: one credit row per paid employee (net > 0).

    Full account numbers are required for payment instructions; do not mask.
    Artifact access control is the protection layer for these credentials.
    """

    async def build(self, session: AsyncSession, ctx: ReportContext) -> BankAdviceDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )

        paid = [item for item in packed if _money(item["result"]["net_payable"]) > _ZERO]

        employee_ids = [item["result"]["employee_id"] for item in paid]
        number_by_id = {
            item["result"]["employee_id"]: str(item["result"]["employee_number"]) for item in paid
        }

        try:
            accounts = await _resolve_primary_salary_accounts(
                session,
                organization_id=ctx.organization_id,
                employee_ids=employee_ids,
                as_of=as_of,
            )
        except _PrimaryAccountLookupError as exc:
            raise MissingPrimarySalaryAccountError(
                [number_by_id[eid] for eid in exc.employee_ids if eid in number_by_id]
                or [str(eid) for eid in exc.employee_ids]
            ) from exc

        columns = _bank_advice_columns()
        rows: list[tuple[Any, ...]] = []
        advice_total = _ZERO

        for item in paid:
            result = item["result"]
            employee_id = result["employee_id"]
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=employee_id,
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            account = accounts[employee_id]
            net = _money(result["net_payable"])
            advice_total += net
            rows.append(
                (
                    str(result["employee_number"]),
                    name,
                    str(account["account_number"]),
                    str(account["ifsc"]),
                    net,
                )
            )

        advice_total = _money(advice_total)
        posted_net = _posted_net_payable(version)
        # Defense in depth: advice credits must equal the posted run net payable.
        # Raise (not assert) so the invariant holds even under `python -O`.
        if advice_total != posted_net:
            raise ConflictError(
                f"bank advice total {advice_total} != posted net payable {posted_net}"
            )

        totals: tuple[Any, ...] = (
            "TOTAL",
            None,
            None,
            None,
            advice_total,
        )

        return ReportDTO(
            report_type=REPORT_TYPE_BANK_ADVICE,
            template_version=ctx.template_version,
            title="Bank / RTGS Advice",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Payment credits",
                    columns=columns,
                    rows=tuple(rows),
                    totals=totals,
                ),
            ),
        )


def _line_kind_for_payslip(line: Any) -> str:
    code = str(line["component_code"])
    trace = line["trace"] or {}
    if code == "FOREGONE_HRA" or trace.get("classification") == "informational":
        return "informational"
    classification = str(line["classification"])
    if classification == "earning":
        return "earning"
    if classification == "employer_contribution":
        return "employer_contribution"
    if classification in _DEDUCTION_CLASSIFICATIONS:
        return "deduction"
    return classification


class PayslipBundleBuilder:
    """Build a payslip bundle DTO with one section (PDF page) per employee."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> PayslipBundleDTO:
        _run, version, period, org = await _require_posted_run(session, ctx)
        as_of = _month_end(period.period_year, period.period_month)
        packed = await _load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )

        columns = _payslip_columns()
        sections: list[TableSection] = []

        for item in packed:
            result = item["result"]
            employee_id = result["employee_id"]
            employee_number = str(result["employee_number"])
            profile = await _resolve_profile(
                session,
                organization_id=ctx.organization_id,
                employee_id=employee_id,
                as_of=as_of,
            )
            name = str(profile["name"]) if profile is not None else ""
            tax_regime = str(profile["retirement_regime"]) if profile is not None else ""
            pan_masked = mask_value(profile["pan"] if profile is not None else None)
            pran_masked = mask_value(profile["pran"] if profile is not None else None)
            designation = await _resolve_designation(
                session,
                organization_id=ctx.organization_id,
                employee_id=employee_id,
                as_of=as_of,
            )
            net = _money(result["net_payable"])
            words = amount_in_words(net)

            rows: list[tuple[Any, ...]] = [
                ("identity", "employee_number", employee_number, None),
                ("identity", "name", name, None),
                ("identity", "designation", designation, None),
                ("identity", "tax_regime", tax_regime, None),
                ("identity", "pan", pan_masked or "", None),
                ("identity", "pran", pran_masked or "", None),
            ]
            for line in item["lines"]:
                kind = _line_kind_for_payslip(line)
                rows.append(
                    (
                        kind,
                        str(line["component_code"]),
                        str(line["classification"]),
                        _money(line["amount"]),
                    )
                )
            rows.append(("net", "net_payable", "Net payable", net))
            rows.append(("net", "amount_in_words", words, None))

            sections.append(
                TableSection(
                    title=f"Payslip — {employee_number}",
                    columns=columns,
                    rows=tuple(rows),
                )
            )

        return ReportDTO(
            report_type=REPORT_TYPE_PAYSLIPS,
            template_version=ctx.template_version,
            title="Payslips",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=tuple(sections),
        )


# Module-level builder instances for registry wiring.
bank_advice_builder = BankAdviceBuilder()
payslip_bundle_builder = PayslipBundleBuilder()


def bank_advice_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def bank_advice_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def bank_advice_to_pdf(dto: ReportDTO) -> bytes:
    """PDF is supported via the generic renderer (catalog lists PDF for bank advice)."""
    return base_to_pdf(dto)


def payslip_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def payslip_to_excel(dto: ReportDTO) -> bytes:
    # Excel for payslips is intentionally skipped — multi-page payslip bundles
    # are delivered as PDF (one page per employee) or JSON preview.
    raise NotImplementedError(
        "Excel export for payslips is intentionally skipped; use PDF or JSON preview."
    )


def payslip_to_pdf(dto: ReportDTO) -> bytes:
    """One PDF page per employee section via the generic tabular renderer."""
    return base_to_pdf(dto)


def register_payment_reports(registry: ReportRegistry) -> None:
    """Register bank advice and payslip builders/formatters on ``registry``."""
    registry.register(
        REPORT_TYPE_BANK_ADVICE,
        builder=bank_advice_builder,
        to_json=bank_advice_to_json,
        to_excel=bank_advice_to_excel,
        to_pdf=bank_advice_to_pdf,
        content_types=DEFAULT_CONTENT_TYPES,
        filename_pattern=BANK_ADVICE_FILENAME_PATTERN,
    )
    registry.register(
        REPORT_TYPE_PAYSLIPS,
        builder=payslip_bundle_builder,
        to_json=payslip_to_json,
        to_excel=payslip_to_excel,
        to_pdf=payslip_to_pdf,
        content_types=DEFAULT_CONTENT_TYPES,
        filename_pattern=PAYSLIPS_FILENAME_PATTERN,
    )
