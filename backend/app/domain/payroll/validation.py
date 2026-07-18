"""Pre- and post-calculation validation for payroll runs (ADR 0007).

Pure domain checks over ``RunCalcInput`` / ``RunResult``. No I/O, no DB.
Findings are deterministic: same input always yields the same ordered tuple.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from app.domain.payroll.inputs import (
    ComponentInput,
    EmployeeCalcInput,
    RunCalcInput,
)
from app.domain.payroll.money import Money
from app.domain.payroll.results import EmployeeResult, RunResult

_AMOUNT_KINDS: frozenset[str] = frozenset(
    {
        "fixed_recurring_amount",
        "direct_monthly_amount",
        "loan_installment_recovery",
        "accommodation_charge",
        "one_time_adjustment",
    }
)

_RATE_KINDS: frozenset[str] = frozenset(
    {
        "percentage_of_component_bases",
        "employer_employee_contribution",
    }
)

_BASIS_KINDS: frozenset[str] = frozenset(
    {
        "percentage_of_component_bases",
        "employer_employee_contribution",
    }
)

_DEDUCTION_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "AG_deduction",
        "treasury_deduction",
        "external_recovery",
    }
)


class Severity(Enum):
    """Finding severity for validation results."""

    error = "error"
    warning = "warning"
    info = "info"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One validation finding with a stable machine-readable code.

    ``context`` is stored as an immutable mapping (``MappingProxyType`` over a
    plain ``dict`` copy). Findings with a non-empty context are not intended
    as dict keys; equality still compares context contents.
    """

    code: str
    severity: Severity
    employee_ref: str | None
    component_code: str | None
    message: str
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


def has_blocking(findings: Iterable[ValidationFinding]) -> bool:
    """Return True if any finding has severity ``error``."""
    return any(f.severity is Severity.error for f in findings)


def _sort_key(finding: ValidationFinding) -> tuple[str, str, str]:
    return (
        finding.employee_ref or "",
        finding.code,
        finding.component_code or "",
    )


def _sorted_findings(findings: list[ValidationFinding]) -> tuple[ValidationFinding, ...]:
    return tuple(sorted(findings, key=_sort_key))


def _regime_indicates_gpf(retirement_regime: str | None) -> bool:
    if retirement_regime is None:
        return False
    return "gpf" in retirement_regime.casefold()


def _has_gpf_jurisdiction(employee: EmployeeCalcInput) -> bool:
    if employee.gpf_jurisdiction is not None and employee.gpf_jurisdiction != "":
        return True
    for component in employee.components:
        if component.gpf_jurisdiction is not None and component.gpf_jurisdiction != "":
            return True
    return False


def _validate_employee_inputs(employee: EmployeeCalcInput) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    ref = employee.employee_ref
    seen_codes: dict[str, int] = {}
    for component in employee.components:
        seen_codes[component.component_code] = seen_codes.get(component.component_code, 0) + 1

    duplicate_codes = {code for code, count in seen_codes.items() if count > 1}
    for component in employee.components:
        if component.component_code in duplicate_codes:
            findings.append(
                ValidationFinding(
                    code="duplicate_component_code",
                    severity=Severity.error,
                    employee_ref=ref,
                    component_code=component.component_code,
                    message=(
                        f"Employee {ref!r} has duplicate component_code "
                        f"{component.component_code!r}"
                    ),
                    context={
                        "employee_ref": ref,
                        "component_code": component.component_code,
                    },
                )
            )
            # One finding per duplicate code is enough; skip repeats of same code.
            duplicate_codes.discard(component.component_code)

    present_codes = {c.component_code for c in employee.components}

    for component in employee.components:
        findings.extend(_validate_component(employee, component, present_codes))

    if _regime_indicates_gpf(employee.retirement_regime) and not _has_gpf_jurisdiction(employee):
        findings.append(
            ValidationFinding(
                code="missing_gpf_jurisdiction",
                severity=Severity.error,
                employee_ref=ref,
                component_code=None,
                message=(
                    f"Employee {ref!r} has GPF retirement regime but no "
                    "gpf_jurisdiction on the employee or any component"
                ),
                context={
                    "employee_ref": ref,
                    "retirement_regime": employee.retirement_regime or "",
                },
            )
        )

    earning_count = sum(1 for c in employee.components if c.classification == "earning")
    if earning_count == 0:
        findings.append(
            ValidationFinding(
                code="no_earning_components",
                severity=Severity.warning,
                employee_ref=ref,
                component_code=None,
                message=f"Employee {ref!r} has no components classified as 'earning'",
                context={"employee_ref": ref},
            )
        )

    return findings


def _validate_component(
    employee: EmployeeCalcInput,
    component: ComponentInput,
    present_codes: set[str],
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    ref = employee.employee_ref
    code = component.component_code

    if component.calc_kind in _BASIS_KINDS and not component.basis:
        findings.append(
            ValidationFinding(
                code="empty_basis",
                severity=Severity.error,
                employee_ref=ref,
                component_code=code,
                message=(
                    f"Component {code!r} on employee {ref!r} has calc_kind "
                    f"{component.calc_kind!r} with an empty basis"
                ),
                context={
                    "employee_ref": ref,
                    "component_code": code,
                    "calc_kind": component.calc_kind,
                },
            )
        )

    if component.calc_kind in _BASIS_KINDS:
        for basis_code in component.basis:
            if basis_code not in present_codes:
                findings.append(
                    ValidationFinding(
                        code="unknown_basis_component",
                        severity=Severity.error,
                        employee_ref=ref,
                        component_code=code,
                        message=(
                            f"Component {code!r} on employee {ref!r} references "
                            f"unknown basis component {basis_code!r}"
                        ),
                        context={
                            "employee_ref": ref,
                            "component_code": code,
                            "basis_component_code": basis_code,
                        },
                    )
                )

    needs_amount = component.calc_kind in _AMOUNT_KINDS and component.amount is None
    needs_rate = component.calc_kind in _RATE_KINDS and component.rate is None
    if needs_amount or needs_rate:
        findings.append(
            ValidationFinding(
                code="missing_amount_or_rate",
                severity=Severity.error,
                employee_ref=ref,
                component_code=code,
                message=(
                    f"Component {code!r} on employee {ref!r} is missing "
                    f"{'amount' if needs_amount else 'rate'} required by "
                    f"calc_kind {component.calc_kind!r}"
                ),
                context={
                    "employee_ref": ref,
                    "component_code": code,
                    "calc_kind": component.calc_kind,
                    "missing": "amount" if needs_amount else "rate",
                },
            )
        )

    if (
        component.amount is not None
        and component.amount < Money.zero()
        and component.calc_kind != "one_time_adjustment"
    ):
        findings.append(
            ValidationFinding(
                code="negative_amount",
                severity=Severity.error,
                employee_ref=ref,
                component_code=code,
                message=(
                    f"Component {code!r} on employee {ref!r} has a negative "
                    f"amount but calc_kind {component.calc_kind!r} does not "
                    "allow negatives"
                ),
                context={
                    "employee_ref": ref,
                    "component_code": code,
                    "calc_kind": component.calc_kind,
                    "amount": component.amount.to_canonical_str(),
                },
            )
        )

    if component.calc_kind == "one_time_adjustment" and (
        component.reason is None or component.reason == ""
    ):
        findings.append(
            ValidationFinding(
                code="missing_adjustment_reason",
                severity=Severity.warning,
                employee_ref=ref,
                component_code=code,
                message=(
                    f"one_time_adjustment component {code!r} on employee "
                    f"{ref!r} is missing a reason"
                ),
                context={
                    "employee_ref": ref,
                    "component_code": code,
                },
            )
        )

    return findings


def validate_run_inputs(run: RunCalcInput) -> tuple[ValidationFinding, ...]:
    """Pre-calculation structural checks over a ``RunCalcInput``."""
    findings: list[ValidationFinding] = []
    for employee in run.employees:
        findings.extend(_validate_employee_inputs(employee))
    return _sorted_findings(findings)


def _identity_holds(employee: EmployeeResult) -> bool:
    expected_net = employee.gross_total - employee.deductions_total
    expected_gross = (
        employee.earnings_total
        + employee.employer_contribution_total
        + employee.gross_adjustment_total
    )
    expected_deductions = (
        employee.ag_deduction_total
        + employee.treasury_deduction_total
        + employee.external_recovery_total
    )
    return (
        employee.net_payable == expected_net
        and employee.gross_total == expected_gross
        and employee.deductions_total == expected_deductions
    )


def _validate_employee_result(employee: EmployeeResult) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    ref = employee.employee_ref

    if not _identity_holds(employee):
        findings.append(
            ValidationFinding(
                code="identity_violation",
                severity=Severity.error,
                employee_ref=ref,
                component_code=None,
                message=(
                    f"Employee {ref!r} fails gross-to-net identity checks "
                    "(net/gross/deductions aggregates are inconsistent)"
                ),
                context={
                    "employee_ref": ref,
                    "net_payable": employee.net_payable.to_canonical_str(),
                    "gross_total": employee.gross_total.to_canonical_str(),
                    "deductions_total": employee.deductions_total.to_canonical_str(),
                    "earnings_total": employee.earnings_total.to_canonical_str(),
                    "employer_contribution_total": (
                        employee.employer_contribution_total.to_canonical_str()
                    ),
                    "gross_adjustment_total": employee.gross_adjustment_total.to_canonical_str(),
                    "ag_deduction_total": employee.ag_deduction_total.to_canonical_str(),
                    "treasury_deduction_total": employee.treasury_deduction_total.to_canonical_str(),
                    "external_recovery_total": employee.external_recovery_total.to_canonical_str(),
                },
            )
        )

    if employee.net_payable < Money.zero():
        findings.append(
            ValidationFinding(
                code="negative_net_payable",
                severity=Severity.error,
                employee_ref=ref,
                component_code=None,
                message=f"Employee {ref!r} has negative net_payable",
                context={
                    "employee_ref": ref,
                    "net_payable": employee.net_payable.to_canonical_str(),
                },
            )
        )
    elif employee.net_payable == Money.zero():
        findings.append(
            ValidationFinding(
                code="zero_net_payable",
                severity=Severity.warning,
                employee_ref=ref,
                component_code=None,
                message=f"Employee {ref!r} has zero net_payable",
                context={
                    "employee_ref": ref,
                    "net_payable": employee.net_payable.to_canonical_str(),
                },
            )
        )

    for line in employee.lines:
        if (
            line.classification in _DEDUCTION_CLASSIFICATIONS
            and line.rounded_value > employee.gross_total
        ):
            findings.append(
                ValidationFinding(
                    code="deduction_exceeds_gross",
                    severity=Severity.warning,
                    employee_ref=ref,
                    component_code=line.component,
                    message=(
                        f"Deduction line {line.component!r} on employee {ref!r} "
                        f"({line.rounded_value.to_canonical_str()}) exceeds "
                        f"gross_total ({employee.gross_total.to_canonical_str()})"
                    ),
                    context={
                        "employee_ref": ref,
                        "component_code": line.component,
                        "classification": line.classification,
                        "rounded_value": line.rounded_value.to_canonical_str(),
                        "gross_total": employee.gross_total.to_canonical_str(),
                    },
                )
            )

    return findings


def validate_run_result(result: RunResult) -> tuple[ValidationFinding, ...]:
    """Post-calculation identity and sanity checks over a ``RunResult``."""
    findings: list[ValidationFinding] = []

    if len(result.employees) == 0:
        findings.append(
            ValidationFinding(
                code="empty_run",
                severity=Severity.error,
                employee_ref=None,
                component_code=None,
                message="Run result has zero employees",
                context={
                    "period": result.period,
                    "org_ref": result.org_ref,
                },
            )
        )

    for employee in result.employees:
        findings.extend(_validate_employee_result(employee))

    return _sorted_findings(findings)
