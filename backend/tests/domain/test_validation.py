"""Unit coverage for payroll run input/result validation."""

from __future__ import annotations

from decimal import Decimal

from app.domain.payroll.engine import calculate_run
from app.domain.payroll.inputs import ComponentInput, EmployeeCalcInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.results import CalculationTrace, EmployeeResult, RunResult
from app.domain.payroll.rounding import ROUND_HALF_UP_PAISE, ROUND_NONE
from app.domain.payroll.validation import (
    Severity,
    ValidationFinding,
    has_blocking,
    validate_run_inputs,
    validate_run_result,
)


def _earning(code: str, amount: str) -> ComponentInput:
    return ComponentInput(
        component_code=code,
        classification="earning",
        calc_kind="fixed_recurring_amount",
        amount=Money.from_str(amount),
    )


def _run(*employees: EmployeeCalcInput) -> RunCalcInput:
    return RunCalcInput(period="2026-06", org_ref="ORG", employees=employees)


def _codes(findings: tuple[ValidationFinding, ...]) -> list[str]:
    return [f.code for f in findings]


def _zero_employee_result(
    employee_ref: str,
    *,
    net_payable: Money | None = None,
    gross_total: Money | None = None,
    earnings_total: Money | None = None,
    deductions_total: Money | None = None,
    ag_deduction_total: Money | None = None,
    treasury_deduction_total: Money | None = None,
    external_recovery_total: Money | None = None,
    employer_contribution_total: Money | None = None,
    gross_adjustment_total: Money | None = None,
    lines: tuple[CalculationTrace, ...] = (),
) -> EmployeeResult:
    zero = Money.zero()
    resolved_net = net_payable if net_payable is not None else zero
    return EmployeeResult(
        employee_ref=employee_ref,
        lines=lines,
        earnings_total=earnings_total if earnings_total is not None else zero,
        employer_contribution_total=(
            employer_contribution_total if employer_contribution_total is not None else zero
        ),
        gross_adjustment_total=(
            gross_adjustment_total if gross_adjustment_total is not None else zero
        ),
        gross_total=gross_total if gross_total is not None else zero,
        ag_deduction_total=ag_deduction_total if ag_deduction_total is not None else zero,
        treasury_deduction_total=(
            treasury_deduction_total if treasury_deduction_total is not None else zero
        ),
        external_recovery_total=(
            external_recovery_total if external_recovery_total is not None else zero
        ),
        deductions_total=deductions_total if deductions_total is not None else zero,
        net_payable=resolved_net,
        offbill_employer_remittance=zero,
        disbursement=resolved_net,
    )


def _trace(
    component: str,
    classification: str,
    rounded: str,
) -> CalculationTrace:
    return CalculationTrace(
        component=component,
        classification=classification,
        basis=(),
        basis_total=None,
        rate=None,
        unrounded_value=rounded,
        rounding_rule=ROUND_NONE,
        rounded_value=Money.from_str(rounded),
        source_version_ids=(),
        calculator_kind="fixed_recurring_amount",
        engine_version="test",
    )


def _run_result(*employees: EmployeeResult) -> RunResult:
    return RunResult(
        period="2026-06",
        org_ref="ORG",
        engine_version="test",
        employees=employees,
        earnings_total=Money.zero(),
        employer_contribution_total=Money.zero(),
        gross_adjustment_total=Money.zero(),
        gross_total=Money.zero(),
        ag_deduction_total=Money.zero(),
        treasury_deduction_total=Money.zero(),
        external_recovery_total=Money.zero(),
        deductions_total=Money.zero(),
        net_payable=Money.zero(),
        content_hash="0" * 64,
    )


# --- input finding codes ------------------------------------------------------


def test_duplicate_component_code() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            _earning("BASIC", "1000.00"),
            _earning("BASIC", "2000.00"),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "duplicate_component_code" in _codes(findings)
    assert any(f.severity is Severity.error for f in findings)


def test_empty_basis() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            _earning("BASIC", "1000.00"),
            ComponentInput(
                component_code="HRA",
                classification="earning",
                calc_kind="percentage_of_component_bases",
                rate=Rate.from_fraction("0.100000"),
                basis=(),
                rounding_rule=ROUND_HALF_UP_PAISE,
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "empty_basis" in _codes(findings)


def test_unknown_basis_component() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            _earning("BASIC", "1000.00"),
            ComponentInput(
                component_code="HRA",
                classification="earning",
                calc_kind="percentage_of_component_bases",
                rate=Rate.from_fraction("0.100000"),
                basis=("MISSING",),
                rounding_rule=ROUND_HALF_UP_PAISE,
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "unknown_basis_component" in _codes(findings)


def test_missing_amount_on_passthrough_kind() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            ComponentInput(
                component_code="BASIC",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=None,
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "missing_amount_or_rate" in _codes(findings)


def test_missing_rate_on_percentage_kind() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            _earning("BASIC", "1000.00"),
            ComponentInput(
                component_code="HRA",
                classification="earning",
                calc_kind="percentage_of_component_bases",
                rate=None,
                basis=("BASIC",),
                rounding_rule=ROUND_HALF_UP_PAISE,
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "missing_amount_or_rate" in _codes(findings)


def test_negative_amount_not_allowed_except_one_time_adjustment() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            ComponentInput(
                component_code="BASIC",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_decimal(Decimal("-10.00")),
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "negative_amount" in _codes(findings)


def test_negative_one_time_adjustment_is_allowed() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            _earning("BASIC", "1000.00"),
            ComponentInput(
                component_code="ADJ",
                classification="gross_adjustment",
                calc_kind="one_time_adjustment",
                amount=Money.from_decimal(Decimal("-10.00")),
                reason="arrears correction",
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "negative_amount" not in _codes(findings)


def test_missing_gpf_jurisdiction() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        retirement_regime="State GPF Scheme",
        gpf_jurisdiction=None,
        components=(_earning("BASIC", "1000.00"),),
    )
    findings = validate_run_inputs(_run(emp))
    assert "missing_gpf_jurisdiction" in _codes(findings)


def test_gpf_jurisdiction_from_component_satisfies_check() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        retirement_regime="gpf",
        gpf_jurisdiction=None,
        components=(
            ComponentInput(
                component_code="GPF",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
                gpf_jurisdiction="Mumbai",
            ),
            _earning("BASIC", "1000.00"),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert "missing_gpf_jurisdiction" not in _codes(findings)


def test_no_earning_components_warning() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            ComponentInput(
                component_code="GPF",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert any(
        f.code == "no_earning_components" and f.severity is Severity.warning for f in findings
    )


def test_missing_adjustment_reason_warning() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            _earning("BASIC", "1000.00"),
            ComponentInput(
                component_code="ADJ",
                classification="gross_adjustment",
                calc_kind="one_time_adjustment",
                amount=Money.from_str("50.00"),
                reason=None,
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert any(
        f.code == "missing_adjustment_reason" and f.severity is Severity.warning for f in findings
    )


# --- result finding codes -----------------------------------------------------


def test_identity_violation() -> None:
    emp = _zero_employee_result(
        "E1",
        earnings_total=Money.from_str("1000.00"),
        gross_total=Money.from_str("1000.00"),
        deductions_total=Money.from_str("100.00"),
        net_payable=Money.from_str("999.00"),  # should be 900.00
    )
    findings = validate_run_result(_run_result(emp))
    assert "identity_violation" in _codes(findings)


def test_negative_net_payable() -> None:
    emp = _zero_employee_result(
        "E1",
        earnings_total=Money.from_str("100.00"),
        gross_total=Money.from_str("100.00"),
        deductions_total=Money.from_str("200.00"),
        ag_deduction_total=Money.from_str("200.00"),
        net_payable=Money.from_decimal(Decimal("-100.00")),
    )
    findings = validate_run_result(_run_result(emp))
    assert "negative_net_payable" in _codes(findings)
    assert has_blocking(findings) is True


def test_zero_net_payable_warning() -> None:
    emp = _zero_employee_result(
        "E1",
        earnings_total=Money.from_str("100.00"),
        gross_total=Money.from_str("100.00"),
        deductions_total=Money.from_str("100.00"),
        ag_deduction_total=Money.from_str("100.00"),
        net_payable=Money.zero(),
    )
    findings = validate_run_result(_run_result(emp))
    assert any(f.code == "zero_net_payable" and f.severity is Severity.warning for f in findings)


def test_deduction_exceeds_gross_warning() -> None:
    line = _trace("GPF", "AG_deduction", "500.00")
    emp = _zero_employee_result(
        "E1",
        earnings_total=Money.from_str("100.00"),
        gross_total=Money.from_str("100.00"),
        deductions_total=Money.from_str("500.00"),
        ag_deduction_total=Money.from_str("500.00"),
        net_payable=Money.from_decimal(Decimal("-400.00")),
        lines=(line,),
    )
    findings = validate_run_result(_run_result(emp))
    assert any(
        f.code == "deduction_exceeds_gross" and f.severity is Severity.warning for f in findings
    )


def test_empty_run() -> None:
    findings = validate_run_result(_run_result())
    assert "empty_run" in _codes(findings)
    assert has_blocking(findings) is True


# --- has_blocking / severities / ordering / clean path ------------------------


def test_has_blocking_false_for_warnings_only() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            ComponentInput(
                component_code="GPF",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp))
    assert findings
    assert all(f.severity is Severity.warning for f in findings)
    assert has_blocking(findings) is False


def test_error_and_warning_severities_both_appear() -> None:
    emp = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            ComponentInput(
                component_code="ADJ",
                classification="gross_adjustment",
                calc_kind="one_time_adjustment",
                amount=Money.from_str("50.00"),
                reason="",
            ),
        ),
    )
    # no earning -> warning; missing reason -> warning; but also need an error:
    # add negative amount on a non-adjustment kind via a separate employee.
    emp2 = EmployeeCalcInput(
        employee_ref="E2",
        components=(
            ComponentInput(
                component_code="BASIC",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_decimal(Decimal("-1.00")),
            ),
        ),
    )
    findings = validate_run_inputs(_run(emp, emp2))
    severities = {f.severity for f in findings}
    assert Severity.error in severities
    assert Severity.warning in severities


def test_findings_are_sorted_deterministically() -> None:
    """Multiple employees/findings in shuffled input order yield a sorted tuple."""
    # E2 findings first in input, E1 second — output must sort by employee_ref.
    emp_b = EmployeeCalcInput(
        employee_ref="E2",
        components=(
            ComponentInput(
                component_code="Z_ADJ",
                classification="gross_adjustment",
                calc_kind="one_time_adjustment",
                amount=Money.from_str("1.00"),
                reason=None,
            ),
            ComponentInput(
                component_code="A_DUP",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("1.00"),
            ),
            ComponentInput(
                component_code="A_DUP",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("2.00"),
            ),
        ),
    )
    emp_a = EmployeeCalcInput(
        employee_ref="E1",
        retirement_regime="GPF",
        gpf_jurisdiction="",
        components=(
            ComponentInput(
                component_code="M_ADJ",
                classification="gross_adjustment",
                calc_kind="one_time_adjustment",
                amount=Money.from_str("1.00"),
                reason="",
            ),
            ComponentInput(
                component_code="N_DED",
                classification="treasury_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("1.00"),
            ),
        ),
    )
    run = _run(emp_b, emp_a)
    first = validate_run_inputs(run)
    second = validate_run_inputs(run)
    assert first == second

    expected_order = sorted(
        first,
        key=lambda f: (f.employee_ref or "", f.code, f.component_code or ""),
    )
    assert first == tuple(expected_order)
    # E1 findings precede E2 (employee_ref sort).
    e1_idxs = [i for i, f in enumerate(first) if f.employee_ref == "E1"]
    e2_idxs = [i for i, f in enumerate(first) if f.employee_ref == "E2"]
    assert e1_idxs and e2_idxs
    assert max(e1_idxs) < min(e2_idxs)


def test_clean_run_inputs_and_engine_result_have_zero_findings() -> None:
    run = _run(
        EmployeeCalcInput(
            employee_ref="E1",
            components=(_earning("BASIC", "1000.00"),),
        )
    )
    assert validate_run_inputs(run) == ()
    result = calculate_run(run)
    assert validate_run_result(result) == ()


def test_every_finding_code_is_covered() -> None:
    """Meta-check: the suite exercises each documented finding code at least once.

    Codes are collected from dedicated tests above by re-running the same
    minimal triggers here so the contract stays explicit in one place.
    """
    covered: set[str] = set()

    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(_earning("X", "1.00"), _earning("X", "2.00")),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(
                            _earning("BASIC", "1.00"),
                            ComponentInput(
                                component_code="HRA",
                                classification="earning",
                                calc_kind="percentage_of_component_bases",
                                rate=Rate.from_fraction("0.100000"),
                                basis=(),
                                rounding_rule=ROUND_HALF_UP_PAISE,
                            ),
                        ),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(
                            _earning("BASIC", "1.00"),
                            ComponentInput(
                                component_code="HRA",
                                classification="earning",
                                calc_kind="percentage_of_component_bases",
                                rate=Rate.from_fraction("0.100000"),
                                basis=("NOPE",),
                                rounding_rule=ROUND_HALF_UP_PAISE,
                            ),
                        ),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(
                            ComponentInput(
                                component_code="BASIC",
                                classification="earning",
                                calc_kind="direct_monthly_amount",
                                amount=None,
                            ),
                        ),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(
                            ComponentInput(
                                component_code="BASIC",
                                classification="earning",
                                calc_kind="fixed_recurring_amount",
                                amount=Money.from_decimal(Decimal("-1.00")),
                            ),
                        ),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        retirement_regime="gpf",
                        components=(_earning("BASIC", "1.00"),),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(
                            ComponentInput(
                                component_code="GPF",
                                classification="AG_deduction",
                                calc_kind="fixed_recurring_amount",
                                amount=Money.from_str("1.00"),
                            ),
                        ),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_inputs(
                _run(
                    EmployeeCalcInput(
                        employee_ref="E1",
                        components=(
                            _earning("BASIC", "1.00"),
                            ComponentInput(
                                component_code="ADJ",
                                classification="gross_adjustment",
                                calc_kind="one_time_adjustment",
                                amount=Money.from_str("1.00"),
                                reason=None,
                            ),
                        ),
                    )
                )
            )
        )
    )

    covered.update(
        _codes(
            validate_run_result(
                _run_result(
                    _zero_employee_result(
                        "E1",
                        earnings_total=Money.from_str("100.00"),
                        gross_total=Money.from_str("100.00"),
                        deductions_total=Money.from_str("10.00"),
                        net_payable=Money.from_str("99.00"),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_result(
                _run_result(
                    _zero_employee_result(
                        "E1",
                        earnings_total=Money.from_str("100.00"),
                        gross_total=Money.from_str("100.00"),
                        deductions_total=Money.from_str("200.00"),
                        ag_deduction_total=Money.from_str("200.00"),
                        net_payable=Money.from_decimal(Decimal("-100.00")),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_result(
                _run_result(
                    _zero_employee_result(
                        "E1",
                        earnings_total=Money.from_str("100.00"),
                        gross_total=Money.from_str("100.00"),
                        deductions_total=Money.from_str("100.00"),
                        ag_deduction_total=Money.from_str("100.00"),
                        net_payable=Money.zero(),
                    )
                )
            )
        )
    )
    covered.update(
        _codes(
            validate_run_result(
                _run_result(
                    _zero_employee_result(
                        "E1",
                        earnings_total=Money.from_str("100.00"),
                        gross_total=Money.from_str("100.00"),
                        deductions_total=Money.from_str("500.00"),
                        ag_deduction_total=Money.from_str("500.00"),
                        net_payable=Money.from_decimal(Decimal("-400.00")),
                        lines=(_trace("GPF", "AG_deduction", "500.00"),),
                    )
                )
            )
        )
    )
    covered.update(_codes(validate_run_result(_run_result())))

    expected = {
        "duplicate_component_code",
        "empty_basis",
        "unknown_basis_component",
        "missing_amount_or_rate",
        "negative_amount",
        "missing_gpf_jurisdiction",
        "no_earning_components",
        "missing_adjustment_reason",
        "identity_violation",
        "negative_net_payable",
        "zero_net_payable",
        "deduction_exceeds_gross",
        "empty_run",
    }
    assert expected <= covered
