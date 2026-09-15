"""Shared payroll run-result reconstruction for hash-bound transitions.

Submit/approve (``run_workflow``) and post/reverse (``run_posting``) recompute
``content_hash`` from the same stored rows, so both lanes must rebuild the
``RunResult`` identically: employee aggregates come from the persisted
snapshot columns (the values the engine hashed at write time), the four
bucket fields with no column are re-derived from line classifications, and
run totals prefer the version's stored ``totals`` map with a line-sum
fallback. Line fields — including the ``unrounded_value`` string — are read
verbatim so versions written before canonical formatting still reproduce
their original hash.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.engine import content_hash_for
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.results import CalculationTrace, EmployeeResult, RunResult
from app.models.payroll_runs import (
    PayrollPeriod,
    payroll_employee_results,
    payroll_result_lines,
)


def period_label(period: PayrollPeriod) -> str:
    return f"{period.period_year:04d}-{period.period_month:02d}"


def money_from_db(value: Decimal | str | None) -> Money:
    if value is None:
        return Money.zero()
    if isinstance(value, Decimal):
        return Money.from_decimal(value)
    return Money.from_str(str(value))


def _optional_money_from_trace(value: Any) -> Money | None:
    if value is None:
        return None
    return Money.from_str(str(value))


def _optional_rate_from_trace(value: Any) -> Rate | None:
    if value is None:
        return None
    return Rate.from_fraction(str(value))


# ``informational`` / ``excluded_from_totals`` are added to ``CalculationTrace``
# alongside the trace-payload write in a parallel change; restore them only when
# the dataclass declares the fields so either landing order keeps working, and
# read with ``.get(name, False)`` so pre-existing payloads without the keys
# still reconstruct.
_TRACE_FLAG_FIELDS = tuple(
    name
    for name in ("informational", "excluded_from_totals")
    if name in CalculationTrace.__dataclass_fields__
)


def trace_from_row(row: Any) -> CalculationTrace:
    trace = row["trace"] or {}
    classification = str(trace.get("classification") or row["classification"])
    if classification == "ag_deduction":
        classification = "AG_deduction"
    return CalculationTrace(
        component=str(trace.get("component") or row["component_code"]),
        classification=classification,
        basis=tuple(str(b) for b in (trace.get("basis") or ())),
        basis_total=_optional_money_from_trace(trace.get("basis_total")),
        rate=_optional_rate_from_trace(trace.get("rate")),
        # Verbatim: the hash covers this string as stored. Canonicalizing here
        # would rewrite historical values (e.g. "1E-8" -> "0.00000001") and
        # break hash reproduction for pre-canonical versions; new writes are
        # already canonical at rest.
        unrounded_value=str(trace.get("unrounded_value") or row["amount"]),
        rounding_rule=str(trace.get("rounding_rule") or "ROUND_NONE"),
        rounded_value=money_from_db(row["amount"]),
        source_version_ids=tuple(str(v) for v in (trace.get("source_version_ids") or ())),
        calculator_kind=str(trace.get("calculator_kind") or row["calc_kind"]),
        engine_version=str(trace.get("engine_version") or ""),
        employer_transfer=bool(trace.get("employer_transfer", False)),
        transfer_of=(None if trace.get("transfer_of") is None else str(trace["transfer_of"])),
        service_period=(
            None if trace.get("service_period") is None else str(trace["service_period"])
        ),
        reason=(None if trace.get("reason") is None else str(trace["reason"])),
        **{name: bool(trace.get(name, False)) for name in _TRACE_FLAG_FIELDS},
    )


def _is_excluded_from_totals(line: CalculationTrace) -> bool:
    """Mirror ``ComponentInput.is_excluded_from_aggregates`` for stored lines."""
    return (
        line.classification == "informational"
        or getattr(line, "informational", False)
        or getattr(line, "excluded_from_totals", False)
    )


def _bucket_totals(
    lines: tuple[CalculationTrace, ...],
) -> tuple[Money, Money, Money, Money]:
    """Derive adjustment / deduction buckets from line classifications."""
    gross_adj = Money.zero()
    ag = Money.zero()
    treasury = Money.zero()
    external = Money.zero()
    for line in lines:
        if _is_excluded_from_totals(line):
            continue
        if line.classification == "gross_adjustment":
            gross_adj = gross_adj + line.rounded_value
        elif line.classification == "AG_deduction":
            ag = ag + line.rounded_value
        elif line.classification == "treasury_deduction":
            treasury = treasury + line.rounded_value
        elif line.classification == "external_recovery":
            external = external + line.rounded_value
    return gross_adj, ag, treasury, external


async def load_run_result(
    db: AsyncSession,
    *,
    organization_id: UUID,
    period: PayrollPeriod,
    version: Any,
) -> RunResult:
    """Rebuild a stored run version's ``RunResult`` with its content hash."""
    emp_rows = (
        (
            await db.execute(
                sa.select(payroll_employee_results)
                .where(payroll_employee_results.c.organization_id == organization_id)
                .where(payroll_employee_results.c.run_version_id == version["id"])
                .order_by(payroll_employee_results.c.employee_number)
            )
        )
        .mappings()
        .all()
    )

    # One fetch for every employee's lines (was a per-employee query inside the
    # run FOR UPDATE critical section); grouped by employee preserving the
    # per-employee ``sequence`` ordering.
    line_rows = []
    emp_result_ids = [emp["id"] for emp in emp_rows]
    if emp_result_ids:
        line_rows = (
            (
                await db.execute(
                    sa.select(payroll_result_lines)
                    .where(payroll_result_lines.c.organization_id == organization_id)
                    .where(payroll_result_lines.c.employee_result_id.in_(emp_result_ids))
                    .order_by(
                        payroll_result_lines.c.employee_result_id,
                        payroll_result_lines.c.sequence,
                    )
                )
            )
            .mappings()
            .all()
        )
    lines_by_emp: dict[Any, list[Any]] = {}
    for line_row in line_rows:
        lines_by_emp.setdefault(line_row["employee_result_id"], []).append(line_row)

    employees: list[EmployeeResult] = []
    for emp in emp_rows:
        lines = tuple(trace_from_row(row) for row in lines_by_emp.get(emp["id"], ()))
        # The four bucket fields have no snapshot column; everything else is
        # read from the persisted columns the engine hashed at write time.
        gross_adj, ag, treasury, external = _bucket_totals(lines)
        employees.append(
            EmployeeResult(
                employee_ref=str(emp["employee_id"]),
                lines=lines,
                earnings_total=money_from_db(emp["earnings_total"]),
                employer_contribution_total=money_from_db(emp["employer_contribution_total"]),
                gross_adjustment_total=gross_adj,
                gross_total=money_from_db(emp["gross_total"]),
                ag_deduction_total=ag,
                treasury_deduction_total=treasury,
                external_recovery_total=external,
                deductions_total=money_from_db(emp["deductions_total"]),
                net_payable=money_from_db(emp["net_payable"]),
                offbill_employer_remittance=money_from_db(emp["offbill_employer_remittance"]),
                disbursement=money_from_db(emp["disbursement"]),
            )
        )

    employees_sorted = tuple(sorted(employees, key=lambda e: e.employee_ref))
    totals = version["totals"] or {}

    def _total(key: str, fallback: Money) -> Money:
        raw = totals.get(key)
        if raw is None:
            return fallback
        return Money.from_str(str(raw))

    earnings = _total(
        "earnings_total",
        Money.sum(e.earnings_total for e in employees_sorted) if employees_sorted else Money.zero(),
    )
    employer = _total(
        "employer_contribution_total",
        (
            Money.sum(e.employer_contribution_total for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    gross_adj = _total(
        "gross_adjustment_total",
        (
            Money.sum(e.gross_adjustment_total for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    gross = _total(
        "gross_total",
        Money.sum(e.gross_total for e in employees_sorted) if employees_sorted else Money.zero(),
    )
    ag = _total(
        "ag_deduction_total",
        (
            Money.sum(e.ag_deduction_total for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    treasury = _total(
        "treasury_deduction_total",
        (
            Money.sum(e.treasury_deduction_total for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    external = _total(
        "external_recovery_total",
        (
            Money.sum(e.external_recovery_total for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    deductions = _total(
        "deductions_total",
        (
            Money.sum(e.deductions_total for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    net = _total(
        "net_payable",
        Money.sum(e.net_payable for e in employees_sorted) if employees_sorted else Money.zero(),
    )
    offbill = _total(
        "offbill_employer_remittance",
        (
            Money.sum(e.offbill_employer_remittance for e in employees_sorted)
            if employees_sorted
            else Money.zero()
        ),
    )
    disbursement = _total(
        "disbursement",
        Money.sum(e.disbursement for e in employees_sorted) if employees_sorted else Money.zero(),
    )

    # Recompute the content hash from the reconstructed result instead of
    # trusting the stored value: comparing stored-vs-stored was tautological.
    content_hash = content_hash_for(
        period=period_label(period),
        org_ref=str(organization_id),
        engine_version=str(version["engine_version"]),
        employees=employees_sorted,
        earnings_total=earnings,
        employer_contribution_total=employer,
        gross_adjustment_total=gross_adj,
        gross_total=gross,
        ag_deduction_total=ag,
        treasury_deduction_total=treasury,
        external_recovery_total=external,
        deductions_total=deductions,
        net_payable=net,
        offbill_employer_remittance=offbill,
        disbursement=disbursement,
    )

    return RunResult(
        period=period_label(period),
        org_ref=str(organization_id),
        engine_version=str(version["engine_version"]),
        employees=employees_sorted,
        earnings_total=earnings,
        employer_contribution_total=employer,
        gross_adjustment_total=gross_adj,
        gross_total=gross,
        ag_deduction_total=ag,
        treasury_deduction_total=treasury,
        external_recovery_total=external,
        deductions_total=deductions,
        net_payable=net,
        offbill_employer_remittance=offbill,
        disbursement=disbursement,
        content_hash=content_hash,
    )
