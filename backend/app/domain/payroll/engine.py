"""Payroll calculation engine (ADR 0006/0007).

Public API
----------
- ``ENGINE_VERSION``: version string denormalized onto every trace line
- ``calculate_employee(EmployeeCalcInput) -> EmployeeResult``
- ``calculate_run(RunCalcInput) -> RunResult``

Aggregation (non-informational / non-excluded lines only)::

    earnings_total              = sum(classification == "earning")
    employer_contribution_total = sum(classification == "employer_contribution")
    gross_adjustment_total      = sum(classification == "gross_adjustment")
    gross_total                 = earnings_total + employer_contribution_total
                                  + gross_adjustment_total
    ag_deduction_total          = sum(classification == "AG_deduction")
    treasury_deduction_total    = sum(classification == "treasury_deduction")
    external_recovery_total     = sum(classification == "external_recovery")
    deductions_total            = ag_deduction_total + treasury_deduction_total
                                  + external_recovery_total
    net_payable                 = gross_total - deductions_total

Lines with ``classification == "informational"``, ``informational=True``, or
``excluded_from_totals=True`` still produce a ``CalculationTrace`` for audit
but contribute to **no** aggregate.

Determinism
-----------
``calculate_run`` sorts employees by ``employee_ref`` before computing so that
caller order of the ``employees`` tuple does not affect ``content_hash``.
Per-employee ``lines`` are emitted in the original ``ComponentInput`` tuple
order (stable audit order), independent of topological calculation order.

Dependency ordering
-------------------
For each employee, ``ComponentInput.basis`` codes are dependencies that must
be calculated first. Cycles raise ``CalculationCycleError`` naming the exact
cycle path (e.g. ``["A", "B", "C", "A"]``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from app.domain.payroll import calculators
from app.domain.payroll.calculators import CalculatorContext
from app.domain.payroll.inputs import ComponentInput, EmployeeCalcInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.results import CalculationTrace, EmployeeResult, RunResult

ENGINE_VERSION: str = "accord-engine/1.1.0"


class CalculationCycleError(ValueError):
    """Raised when a component dependency cycle is detected.

    ``cycle`` is an ordered list of component codes forming the cycle, with
    the first code repeated at the end (e.g. ``["A", "B", "A"]``).
    """

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        super().__init__(f"calculation dependency cycle: {' -> '.join(self.cycle)}")


class DuplicateComponentCodeError(ValueError):
    """Raised when an employee has duplicate ``component_code`` values."""


def _topo_sort(components: Sequence[ComponentInput]) -> list[str]:
    """Return component codes in dependency order (bases before dependents).

    Edges: basis code -> component (basis must be calculated first).
    """
    by_code: dict[str, ComponentInput] = {}
    for comp in components:
        if comp.component_code in by_code:
            raise DuplicateComponentCodeError(
                f"duplicate component_code {comp.component_code!r} for employee"
            )
        by_code[comp.component_code] = comp

    # Only edges among this employee's components matter for ordering.
    deps: dict[str, tuple[str, ...]] = {
        code: tuple(b for b in comp.basis if b in by_code) for code, comp in by_code.items()
    }

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {code: WHITE for code in by_code}
    order: list[str] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in deps[node]:
            if color[dep] == GRAY:
                # Cycle: from first occurrence of dep in path through node back.
                start = path.index(dep)
                cycle = path[start:] + [dep]
                raise CalculationCycleError(cycle)
            if color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[node] = BLACK
        order.append(node)

    # Stable iteration: input tuple order for roots.
    for comp in components:
        code = comp.component_code
        if color[code] == WHITE:
            dfs(code, [])

    return order


def _money_sum(values: Sequence[Money]) -> Money:
    if not values:
        return Money.zero()
    return Money.sum(values)


def _aggregate_lines(
    components: Sequence[ComponentInput],
    rounded_by_code: Mapping[str, Money],
) -> tuple[Money, Money, Money, Money, Money, Money, Money, Money, Money]:
    earnings: list[Money] = []
    employer_contrib: list[Money] = []
    gross_adj: list[Money] = []
    ag: list[Money] = []
    treasury: list[Money] = []
    external: list[Money] = []

    for comp in components:
        if comp.is_excluded_from_aggregates():
            continue
        value = rounded_by_code[comp.component_code]
        if comp.classification == "earning":
            earnings.append(value)
        elif comp.classification == "employer_contribution":
            employer_contrib.append(value)
        elif comp.classification == "gross_adjustment":
            gross_adj.append(value)
        elif comp.classification == "AG_deduction":
            ag.append(value)
        elif comp.classification == "treasury_deduction":
            treasury.append(value)
        elif comp.classification == "external_recovery":
            external.append(value)

    earnings_total = _money_sum(earnings)
    employer_contribution_total = _money_sum(employer_contrib)
    gross_adjustment_total = _money_sum(gross_adj)
    gross_total = earnings_total + employer_contribution_total + gross_adjustment_total
    ag_deduction_total = _money_sum(ag)
    treasury_deduction_total = _money_sum(treasury)
    external_recovery_total = _money_sum(external)
    deductions_total = ag_deduction_total + treasury_deduction_total + external_recovery_total
    net_payable = gross_total - deductions_total
    return (
        earnings_total,
        employer_contribution_total,
        gross_adjustment_total,
        gross_total,
        ag_deduction_total,
        treasury_deduction_total,
        external_recovery_total,
        deductions_total,
        net_payable,
    )


def _offbill_employer_remittance(
    components: Sequence[ComponentInput],
    rounded_by_code: Mapping[str, Money],
) -> Money:
    """Sum of employer-transfer deduction lines with no paired gross addition.

    An ``employer_transfer`` deduction reverses an ``employer_contribution`` that
    was added into gross. When the paired contribution (``transfer_of``) is
    present as a non-excluded ``employer_contribution`` line for this employee,
    the pair is a true pass-through (EPF) — already net-neutral, so it is **not**
    counted here. When the paired contribution is absent, the transfer reduced
    net without any gross addition (NPS employer is off-bill per
    docs/payroll-domain.md) and must be added back to reach employee
    disbursement.
    """
    contributions = {
        comp.component_code: rounded_by_code[comp.component_code]
        for comp in components
        if not comp.is_excluded_from_aggregates() and comp.classification == "employer_contribution"
    }
    offbill: list[Money] = []
    for comp in components:
        if comp.is_excluded_from_aggregates():
            continue
        if not comp.employer_transfer:
            continue
        if comp.classification not in {
            "AG_deduction",
            "treasury_deduction",
            "external_recovery",
        }:
            raise ValueError(
                f"employer-transfer component {comp.component_code!r} must be a deduction"
            )
        transfer_amount = rounded_by_code[comp.component_code]
        if comp.transfer_of is None:
            offbill.append(transfer_amount)
            continue
        paired_amount = contributions.get(comp.transfer_of)
        if paired_amount is None:
            raise ValueError(
                f"employer-transfer component {comp.component_code!r} references missing "
                f"employer contribution {comp.transfer_of!r}"
            )
        if paired_amount != transfer_amount:
            raise ValueError(
                f"employer-transfer component {comp.component_code!r} amount "
                f"{transfer_amount.to_canonical_str()} does not match {comp.transfer_of!r} "
                f"amount {paired_amount.to_canonical_str()}"
            )
    return _money_sum(offbill)


def calculate_employee(input: EmployeeCalcInput) -> EmployeeResult:
    """Calculate one employee: topo-order calculators, then aggregate."""
    components = input.components
    by_code = {c.component_code: c for c in components}
    calc_order = _topo_sort(components)

    computed: dict[str, Money] = {}
    traces_by_code: dict[str, CalculationTrace] = {}

    for code in calc_order:
        comp = by_code[code]
        calc_fn = calculators.get(comp.calc_kind)
        result = calc_fn(CalculatorContext(component=comp, computed=computed))
        computed[code] = result.rounded_value
        traces_by_code[code] = CalculationTrace(
            component=comp.component_code,
            classification=comp.classification,
            basis=comp.basis,
            basis_total=result.basis_total,
            rate=result.rate,
            unrounded_value=str(result.unrounded_value),
            rounding_rule=comp.rounding_rule,
            rounded_value=result.rounded_value,
            source_version_ids=comp.source_version_ids,
            calculator_kind=comp.calc_kind,
            engine_version=ENGINE_VERSION,
            employer_transfer=comp.employer_transfer,
            transfer_of=comp.transfer_of,
        )

    # Emit lines in original input order (deterministic audit order).
    lines = tuple(traces_by_code[c.component_code] for c in components)
    (
        earnings_total,
        employer_contribution_total,
        gross_adjustment_total,
        gross_total,
        ag_deduction_total,
        treasury_deduction_total,
        external_recovery_total,
        deductions_total,
        net_payable,
    ) = _aggregate_lines(components, computed)

    offbill_employer_remittance = _offbill_employer_remittance(components, computed)
    disbursement = net_payable + offbill_employer_remittance

    return EmployeeResult(
        employee_ref=input.employee_ref,
        lines=lines,
        earnings_total=earnings_total,
        employer_contribution_total=employer_contribution_total,
        gross_adjustment_total=gross_adjustment_total,
        gross_total=gross_total,
        ag_deduction_total=ag_deduction_total,
        treasury_deduction_total=treasury_deduction_total,
        external_recovery_total=external_recovery_total,
        deductions_total=deductions_total,
        net_payable=net_payable,
        offbill_employer_remittance=offbill_employer_remittance,
        disbursement=disbursement,
    )


def _canonical_run_payload(
    *,
    period: str,
    org_ref: str,
    engine_version: str,
    employees: Sequence[EmployeeResult],
    earnings_total: Money,
    employer_contribution_total: Money,
    gross_adjustment_total: Money,
    gross_total: Money,
    ag_deduction_total: Money,
    treasury_deduction_total: Money,
    external_recovery_total: Money,
    deductions_total: Money,
    net_payable: Money,
    offbill_employer_remittance: Money,
    disbursement: Money,
) -> str:
    """Build a canonical JSON string for content hashing.

    Uses ``sort_keys=True`` and compact separators. Money/Rate become their
    canonical decimal strings. Employees are assumed already sorted by
    ``employee_ref``; lines remain in input order.
    """
    employee_payloads: list[dict[str, object]] = []
    for emp in employees:
        line_payloads: list[dict[str, object]] = []
        for line in emp.lines:
            line_payloads.append(
                {
                    "basis": list(line.basis),
                    "basis_total": (
                        None if line.basis_total is None else line.basis_total.to_canonical_str()
                    ),
                    "calculator_kind": line.calculator_kind,
                    "classification": line.classification,
                    "component": line.component,
                    "engine_version": line.engine_version,
                    "employer_transfer": line.employer_transfer,
                    "rate": None if line.rate is None else line.rate.to_canonical_str(),
                    "rounded_value": line.rounded_value.to_canonical_str(),
                    "rounding_rule": line.rounding_rule,
                    "source_version_ids": list(line.source_version_ids),
                    "transfer_of": line.transfer_of,
                    "unrounded_value": line.unrounded_value,
                }
            )
        employee_payloads.append(
            {
                "ag_deduction_total": emp.ag_deduction_total.to_canonical_str(),
                "deductions_total": emp.deductions_total.to_canonical_str(),
                "earnings_total": emp.earnings_total.to_canonical_str(),
                "employee_ref": emp.employee_ref,
                "employer_contribution_total": (emp.employer_contribution_total.to_canonical_str()),
                "external_recovery_total": emp.external_recovery_total.to_canonical_str(),
                "gross_adjustment_total": emp.gross_adjustment_total.to_canonical_str(),
                "gross_total": emp.gross_total.to_canonical_str(),
                "lines": line_payloads,
                "net_payable": emp.net_payable.to_canonical_str(),
                "offbill_employer_remittance": (emp.offbill_employer_remittance.to_canonical_str()),
                "disbursement": emp.disbursement.to_canonical_str(),
                "treasury_deduction_total": emp.treasury_deduction_total.to_canonical_str(),
            }
        )

    payload: dict[str, object] = {
        "ag_deduction_total": ag_deduction_total.to_canonical_str(),
        "deductions_total": deductions_total.to_canonical_str(),
        "earnings_total": earnings_total.to_canonical_str(),
        "employees": employee_payloads,
        "engine_version": engine_version,
        "employer_contribution_total": employer_contribution_total.to_canonical_str(),
        "external_recovery_total": external_recovery_total.to_canonical_str(),
        "gross_adjustment_total": gross_adjustment_total.to_canonical_str(),
        "gross_total": gross_total.to_canonical_str(),
        "net_payable": net_payable.to_canonical_str(),
        "offbill_employer_remittance": offbill_employer_remittance.to_canonical_str(),
        "disbursement": disbursement.to_canonical_str(),
        "org_ref": org_ref,
        "period": period,
        "treasury_deduction_total": treasury_deduction_total.to_canonical_str(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash_for(
    *,
    period: str,
    org_ref: str,
    engine_version: str,
    employees: Sequence[EmployeeResult],
    earnings_total: Money,
    employer_contribution_total: Money,
    gross_adjustment_total: Money,
    gross_total: Money,
    ag_deduction_total: Money,
    treasury_deduction_total: Money,
    external_recovery_total: Money,
    deductions_total: Money,
    net_payable: Money,
    offbill_employer_remittance: Money,
    disbursement: Money,
) -> str:
    """SHA-256 hex digest of the canonical run serialization."""
    canonical = _canonical_run_payload(
        period=period,
        org_ref=org_ref,
        engine_version=engine_version,
        employees=employees,
        earnings_total=earnings_total,
        employer_contribution_total=employer_contribution_total,
        gross_adjustment_total=gross_adjustment_total,
        gross_total=gross_total,
        ag_deduction_total=ag_deduction_total,
        treasury_deduction_total=treasury_deduction_total,
        external_recovery_total=external_recovery_total,
        deductions_total=deductions_total,
        net_payable=net_payable,
        offbill_employer_remittance=offbill_employer_remittance,
        disbursement=disbursement,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calculate_run(input: RunCalcInput) -> RunResult:
    """Calculate a full run.

    Employees are sorted by ``employee_ref`` internally before computing so
    that the same set of employees yields the same ``content_hash`` regardless
    of the order of ``input.employees``.
    """
    sorted_employees = tuple(sorted(input.employees, key=lambda e: e.employee_ref))
    results = tuple(calculate_employee(emp) for emp in sorted_employees)

    earnings_total = _money_sum([e.earnings_total for e in results])
    employer_contribution_total = _money_sum([e.employer_contribution_total for e in results])
    gross_adjustment_total = _money_sum([e.gross_adjustment_total for e in results])
    gross_total = _money_sum([e.gross_total for e in results])
    ag_deduction_total = _money_sum([e.ag_deduction_total for e in results])
    treasury_deduction_total = _money_sum([e.treasury_deduction_total for e in results])
    external_recovery_total = _money_sum([e.external_recovery_total for e in results])
    deductions_total = _money_sum([e.deductions_total for e in results])
    net_payable = _money_sum([e.net_payable for e in results])
    offbill_employer_remittance = _money_sum([e.offbill_employer_remittance for e in results])
    disbursement = _money_sum([e.disbursement for e in results])

    # Payment-critical transfer metadata and resulting disbursement are part of
    # the approval digest. Engine 1.1.0 intentionally changes the canonical hash
    # shape; historical 1.0.0 digests remain stored and valid for old versions.
    digest = content_hash_for(
        period=input.period,
        org_ref=input.org_ref,
        engine_version=ENGINE_VERSION,
        employees=results,
        earnings_total=earnings_total,
        employer_contribution_total=employer_contribution_total,
        gross_adjustment_total=gross_adjustment_total,
        gross_total=gross_total,
        ag_deduction_total=ag_deduction_total,
        treasury_deduction_total=treasury_deduction_total,
        external_recovery_total=external_recovery_total,
        deductions_total=deductions_total,
        net_payable=net_payable,
        offbill_employer_remittance=offbill_employer_remittance,
        disbursement=disbursement,
    )

    return RunResult(
        period=input.period,
        org_ref=input.org_ref,
        engine_version=ENGINE_VERSION,
        employees=results,
        earnings_total=earnings_total,
        employer_contribution_total=employer_contribution_total,
        gross_adjustment_total=gross_adjustment_total,
        gross_total=gross_total,
        ag_deduction_total=ag_deduction_total,
        treasury_deduction_total=treasury_deduction_total,
        external_recovery_total=external_recovery_total,
        deductions_total=deductions_total,
        net_payable=net_payable,
        content_hash=digest,
        offbill_employer_remittance=offbill_employer_remittance,
        disbursement=disbursement,
    )
