"""Typed calculation-engine results (ADR 0006/0007).

``CalculationTrace`` fields match ADR 0007 line-level audit requirements.
``unrounded_value`` is a canonical Decimal string (full pre-round precision),
not a rounded Money string.

Identity (by construction in the engine)::

    net_payable == gross_total - deductions_total

where::

    gross_total = earnings_total + employer_contribution_total + gross_adjustment_total
    deductions_total = ag_deduction_total + treasury_deduction_total + external_recovery_total
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate


@dataclass(frozen=True, slots=True)
class CalculationTrace:
    """Immutable per-line calculation audit record (ADR 0007)."""

    component: str
    classification: str
    basis: tuple[str, ...]
    basis_total: Money | None
    rate: Rate | None
    unrounded_value: str
    rounding_rule: str
    rounded_value: Money
    source_version_ids: tuple[str, ...]
    calculator_kind: str
    engine_version: str


@dataclass(frozen=True, slots=True)
class EmployeeResult:
    """Per-employee aggregates and line traces.

    ``lines`` appear in the same order as the input ``ComponentInput`` tuple
    for that employee (not topological calculation order).
    """

    employee_ref: str
    lines: tuple[CalculationTrace, ...]
    earnings_total: Money
    employer_contribution_total: Money
    gross_adjustment_total: Money
    gross_total: Money
    ag_deduction_total: Money
    treasury_deduction_total: Money
    external_recovery_total: Money
    deductions_total: Money
    net_payable: Money


@dataclass(frozen=True, slots=True)
class RunResult:
    """Immutable run-level calculation snapshot.

    ``employees`` are sorted by ``employee_ref`` for determinism.
    ``content_hash`` is a SHA-256 hex digest of the canonical serialization
    of this result (computed by the engine).
    """

    period: str
    org_ref: str
    engine_version: str
    employees: tuple[EmployeeResult, ...]
    earnings_total: Money
    employer_contribution_total: Money
    gross_adjustment_total: Money
    gross_total: Money
    ag_deduction_total: Money
    treasury_deduction_total: Money
    external_recovery_total: Money
    deductions_total: Money
    net_payable: Money
    content_hash: str
