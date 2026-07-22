"""Payment report family: Bank/RTGS advice and per-employee payslips.

Builders read posted run snapshots and emit :class:`~app.reports.base.ReportDTO`
values (aliased as :data:`BankAdviceDTO` / :data:`PayslipBundleDTO`).

Bank advice rows include **full** bank account numbers and IFSC codes. Artifact
access control (ADR 0010 downloads / audit) is the protection layer — this
report intentionally does not mask payment credentials.

Payslip Excel uses one worksheet per employee; PDF uses one page per employee.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.effective import effective_on, select_active_version
from app.models.employees import (
    employee_bank_account_versions,
    employee_posting_versions,
)
from app.models.org_structure import Post
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
from app.reports.snapshots import load_report_snapshot
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
from app.schemas.employees import mask_value

# Report type strings for orchestrator registration.
REPORT_TYPE_BANK_ADVICE = "bank_rtgs_advice"
REPORT_TYPE_PAYSLIPS = "payslips"

BankAdviceDTO = ReportDTO
PayslipBundleDTO = ReportDTO


PAYSLIP_CONTENT_TYPES = DEFAULT_CONTENT_TYPES
BANK_ADVICE_FILENAME_PATTERN = DEFAULT_FILENAME_PATTERN
PAYSLIPS_FILENAME_PATTERN = DEFAULT_FILENAME_PATTERN

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


def _bank_advice_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    columns = [
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
    ]
    if canonical:
        columns.extend(
            (
                ReportColumn(key="bank_name", header="Bank Name", kind=ColumnKind.TEXT),
                ReportColumn(key="bank_branch", header="Branch", kind=ColumnKind.TEXT),
            )
        )
    columns.extend(
        (
            ReportColumn(key="account_number", header="Account Number", kind=ColumnKind.TEXT),
            ReportColumn(key="ifsc", header="IFSC", kind=ColumnKind.TEXT),
            ReportColumn(key="disbursement", header="Amount Credited", kind=ColumnKind.MONEY),
        )
    )
    return tuple(columns)


def _payslip_columns(*, canonical: bool = False) -> tuple[ReportColumn, ...]:
    columns = [
        ReportColumn(key="line_kind", header="Kind", kind=ColumnKind.TEXT),
        ReportColumn(key="code", header="Code / Field", kind=ColumnKind.TEXT),
        ReportColumn(key="detail", header="Detail", kind=ColumnKind.TEXT),
        ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
    ]
    if canonical:
        columns.append(
            ReportColumn(
                key="employer_transfer",
                header="Employer Transfer",
                kind=ColumnKind.TEXT,
            )
        )
    return tuple(columns)


def _posted_net_payable(version: Any) -> Decimal:
    totals = version["totals"] or {}
    if "net_payable" not in totals:
        raise ConflictError("Posted run version totals missing net_payable.")
    return money(totals["net_payable"])


def _posted_disbursement(version: Any) -> Decimal:
    """Employee disbursement for a posted run version.

    This is what employees are actually credited, and it is **not** the same as
    ``net_payable``: off-bill NPS employer is deducted from the treasury-face net
    without a matching gross addition, so ``disbursement = net_payable +
    offbill_employer_remittance``. Department sign-off 18 Jul 2026; see the
    "Resolved" section of docs/payroll-domain.md.
    """
    totals = version["totals"] or {}
    if "disbursement" not in totals:
        raise ConflictError("Posted run version totals missing disbursement.")
    return money(totals["disbursement"])


class BankAdviceBuilder:
    """Build Bank/RTGS advice DTO: one credit row per paid employee (net > 0).

    Full account numbers are required for payment instructions; do not mask.
    Artifact access control is the protection layer for these credentials.
    """

    async def build(self, session: AsyncSession, ctx: ReportContext) -> BankAdviceDTO:
        _run, version, period, org = await require_posted_run(session, ctx)
        as_of = month_end(period.period_year, period.period_month)
        packed = await load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )

        # Credit-worthiness is judged on disbursement (what is actually paid),
        # not on treasury-face net payable.
        paid = [item for item in packed if money(item["result"]["disbursement"]) > ZERO]

        snapshot = None
        identities: dict[str, Any] = {}
        if ctx.template_version in {"v2", "v3"}:
            snapshot = await load_report_snapshot(
                session,
                organization_id=ctx.organization_id,
                run_version_id=version["id"],
            )
            identities = snapshot.get("employee_identity") or {}
            missing = [
                str(item["result"]["employee_number"])
                for item in paid
                if not (identities.get(str(item["result"]["employee_id"])) or {}).get(
                    "bank_account_number"
                )
                or not (identities.get(str(item["result"]["employee_id"])) or {}).get("bank_ifsc")
            ]
            if missing:
                raise MissingPrimarySalaryAccountError(missing)
            accounts = {}
        else:
            employee_ids = [item["result"]["employee_id"] for item in paid]
            number_by_id = {
                item["result"]["employee_id"]: str(item["result"]["employee_number"])
                for item in paid
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

        canonical = ctx.template_version == "v3"
        columns = _bank_advice_columns(canonical=canonical)
        rows: list[tuple[Any, ...]] = []
        advice_total = ZERO

        for item in paid:
            result = item["result"]
            employee_id = result["employee_id"]
            if snapshot is not None:
                identity = identities[str(employee_id)]
                name = str(identity.get("name") or "")
                account_number = str(identity["bank_account_number"])
                ifsc = str(identity["bank_ifsc"])
                bank_name = str(identity.get("bank_name") or "")
                bank_branch = str(identity.get("bank_branch") or "")
            else:
                profile = await resolve_profile_as_of(
                    session,
                    organization_id=ctx.organization_id,
                    employee_id=employee_id,
                    as_of=as_of,
                )
                name = str(profile["name"]) if profile is not None else ""
                account = accounts[employee_id]
                account_number = str(account["account_number"])
                ifsc = str(account["ifsc"])
                bank_name = str(account["bank_name"] or "")
                bank_branch = str(account["branch"] or "")
            credit = money(result["disbursement"])
            advice_total += credit
            row: tuple[Any, ...] = (str(result["employee_number"]), name)
            if canonical:
                row += (bank_name, bank_branch)
            rows.append(row + (account_number, ifsc, credit))

        advice_total = money(advice_total)
        posted_disbursement = _posted_disbursement(version)
        # Defense in depth: advice credits must equal the posted run disbursement.
        # NOTE: this is deliberately reconciled against disbursement, NOT against
        # net payable — off-bill NPS employer makes those two differ, and they
        # must never be asserted equal (docs/payroll-domain.md "Resolved").
        # Raise (not assert) so the invariant holds even under `python -O`.
        if advice_total != posted_disbursement:
            raise ConflictError(
                f"bank advice total {advice_total} != posted disbursement {posted_disbursement}"
            )

        totals: tuple[Any, ...] = ("TOTAL",) + (None,) * (len(columns) - 2) + (advice_total,)

        sections: list[TableSection] = []
        if snapshot is not None:
            recipient = (snapshot.get("report_profile") or {}).get("bank_advice_recipient") or {}
            sections.append(
                TableSection(
                    title="Advice recipient",
                    columns=(ReportColumn("field", "Field"), ReportColumn("value", "Value")),
                    rows=(
                        ("Bank", str(recipient.get("bank_name") or "")),
                        ("Branch", str(recipient.get("branch") or "")),
                        ("Address", ", ".join(recipient.get("address_lines") or [])),
                    ),
                )
            )
        sections.append(
            TableSection(
                title="Payment credits",
                columns=columns,
                rows=tuple(rows),
                totals=totals,
            )
        )
        return ReportDTO(
            report_type=REPORT_TYPE_BANK_ADVICE,
            template_version=ctx.template_version,
            title="Bank / RTGS Advice",
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
            subtitle=period_label(period.period_year, period.period_month),
            sections=tuple(sections),
            metadata=(
                {
                    "report_profile": dict(snapshot.get("report_profile") or {}),
                    "run_metadata": dict(snapshot.get("run_metadata") or {}),
                }
                if snapshot is not None and ctx.template_version == "v3"
                else {}
            ),
        )


def _line_display_classification(line: Any) -> str:
    """Trace-aware classification for display.

    Informational lines are stored under the legacy ``earning`` DB bucket
    (see ``run_calculation._to_db_classification``); the immutable trace keeps
    the true ``informational`` classification, which is what a payslip must
    show. ``AG_deduction`` (trace) normalizes to the DB ``ag_deduction`` form.
    """
    trace = line["trace"] or {}
    code = str(line["component_code"])
    if code == "FOREGONE_HRA" or trace.get("classification") == "informational":
        return "informational"
    value = str(trace.get("classification") or line["classification"])
    return "ag_deduction" if value == "AG_deduction" else value


def _line_kind_for_payslip(line: Any) -> str:
    code = str(line["component_code"])
    trace = line["trace"] or {}
    if code == "FOREGONE_HRA" or trace.get("classification") == "informational":
        return "informational"
    classification = _line_display_classification(line)
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
        _run, version, period, org = await require_posted_run(session, ctx)
        as_of = month_end(period.period_year, period.period_month)
        packed = await load_result_rows(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )

        canonical = ctx.template_version == "v3"
        columns = _payslip_columns(canonical=canonical)
        sections: list[TableSection] = []
        snapshot = None
        identities: dict[str, Any] = {}
        if ctx.template_version in {"v2", "v3"}:
            snapshot = await load_report_snapshot(
                session,
                organization_id=ctx.organization_id,
                run_version_id=version["id"],
            )
            identities = snapshot.get("employee_identity") or {}

        for item in packed:
            result = item["result"]
            employee_id = result["employee_id"]
            employee_number = str(result["employee_number"])
            if snapshot is not None:
                identity = identities.get(str(employee_id)) or {}
                name = str(identity.get("name") or "")
                tax_regime = str(identity.get("retirement_regime") or "")
                pan_masked = mask_value(identity.get("pan"))
                pran_masked = mask_value(identity.get("pran"))
                designation = str(identity.get("designation") or "")
            else:
                profile = await resolve_profile_as_of(
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
            # Payslip take-home is the disbursement (what reaches the bank
            # account), not the treasury-face net payable.
            net = money(result["net_payable"])
            disbursement = money(result["disbursement"])
            words = amount_in_words(disbursement)

            def payslip_row(
                kind: str,
                code: str,
                detail: Any,
                amount: Any,
                *,
                employer_transfer: bool = False,
            ) -> tuple[Any, ...]:
                values = (kind, code, detail, amount)
                return values + (employer_transfer,) if canonical else values

            rows: list[tuple[Any, ...]] = [
                payslip_row("identity", "employee_number", employee_number, None),
                payslip_row("identity", "name", name, None),
                payslip_row("identity", "designation", designation, None),
                payslip_row("identity", "tax_regime", tax_regime, None),
                payslip_row("identity", "pan", pan_masked or "", None),
                payslip_row("identity", "pran", pran_masked or "", None),
            ]
            for line in item["lines"]:
                kind = _line_kind_for_payslip(line)
                trace = line["trace"] or {}
                rows.append(
                    payslip_row(
                        kind,
                        str(line["component_code"]),
                        _line_display_classification(line),
                        money(line["amount"]),
                        employer_transfer=bool(trace.get("employer_transfer", False)),
                    )
                )
            offbill = money(result["offbill_employer_remittance"])
            rows.append(payslip_row("net", "net_payable", "Net payable (treasury-face)", net))
            if offbill > ZERO:
                rows.append(
                    payslip_row(
                        "net",
                        "offbill_employer_remittance",
                        "Employer NPS share (off-bill; not withheld from pay)",
                        offbill,
                    )
                )
            rows.append(payslip_row("net", "disbursement", "Amount credited", disbursement))
            rows.append(payslip_row("net", "amount_in_words", words, None))

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
            organization_name=(
                str((snapshot.get("organization") or {}).get("name") or org.name)
                if snapshot is not None
                else org.name
            ),
            subtitle=period_label(period.period_year, period.period_month),
            sections=tuple(sections),
            metadata=(
                {
                    "report_profile": dict(snapshot.get("report_profile") or {}),
                    "run_metadata": dict(snapshot.get("run_metadata") or {}),
                }
                if snapshot is not None and ctx.template_version == "v3"
                else {}
            ),
        )


# Module-level builder instances for registry wiring.
bank_advice_builder = BankAdviceBuilder()
payslip_bundle_builder = PayslipBundleBuilder()


def bank_advice_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def bank_advice_to_excel(dto: ReportDTO) -> bytes:
    if dto.template_version == "v3":
        from app.reports.canonical_front_sheets import bank_tip_to_excel

        return bank_tip_to_excel(dto)
    return base_to_excel(dto)


def bank_advice_to_pdf(dto: ReportDTO) -> bytes:
    """PDF is supported via the generic renderer (catalog lists PDF for bank advice)."""
    return base_to_pdf(dto)


def payslip_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def payslip_to_excel(dto: ReportDTO) -> bytes:
    """One worksheet per employee, matching the PDF bundle section boundary."""
    if dto.template_version == "v3":
        from app.reports.canonical_front_sheets import payslip_to_excel as canonical_payslip

        return canonical_payslip(dto)
    return base_to_excel(dto)


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
        content_types=PAYSLIP_CONTENT_TYPES,
        filename_pattern=PAYSLIPS_FILENAME_PATTERN,
    )
