"""Unit coverage for the payroll calculation engine (ADR 0007).

Covers: dependency ordering across a basis chain, named-cycle rejection,
unknown calc_kind propagation, empty-run handling, and content-hash
stability under employee-input reordering (the engine sorts employees by
``employee_ref`` internally, so caller order must not affect the hash).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.payroll.calculators import UnknownCalculatorKindError
from app.domain.payroll.engine import (
    ENGINE_VERSION,
    CalculationCycleError,
    DuplicateComponentCodeError,
    calculate_employee,
    calculate_run,
)
from app.domain.payroll.inputs import ComponentInput, EmployeeCalcInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.rounding import ROUND_HALF_UP_PAISE


def test_engine_version_is_a_nonempty_string() -> None:
    assert isinstance(ENGINE_VERSION, str)
    assert ENGINE_VERSION


# --- dependency ordering -----------------------------------------------------


def test_dependency_chain_calculates_in_correct_order() -> None:
    """C depends on B (percentage), B depends on A (percentage); A is a fixed amount."""
    a = ComponentInput(
        component_code="A",
        classification="earning",
        calc_kind="fixed_recurring_amount",
        amount=Money.from_str("1000.00"),
    )
    b = ComponentInput(
        component_code="B",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.500000"),
        basis=("A",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    c = ComponentInput(
        component_code="C",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("B",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    # Deliberately out of dependency order in the input tuple.
    employee = EmployeeCalcInput(employee_ref="E1", components=(c, a, b))
    result = calculate_employee(employee)

    by_code = {line.component: line for line in result.lines}
    assert by_code["A"].rounded_value == Money.from_str("1000.00")
    assert by_code["B"].rounded_value == Money.from_str("500.00")  # 1000 * 0.5
    assert by_code["C"].rounded_value == Money.from_str("50.00")  # 500 * 0.1

    # Lines are emitted in original input order (C, A, B), not calc order.
    assert [line.component for line in result.lines] == ["C", "A", "B"]

    # Aggregate: all three are "earning" classified.
    assert result.earnings_total == Money.from_str("1550.00")
    assert result.gross_total == Money.from_str("1550.00")
    assert result.net_payable == Money.from_str("1550.00")


def test_duplicate_component_code_is_rejected() -> None:
    dup1 = ComponentInput(
        component_code="X",
        classification="earning",
        calc_kind="fixed_recurring_amount",
        amount=Money.from_str("1.00"),
    )
    dup2 = ComponentInput(
        component_code="X",
        classification="earning",
        calc_kind="fixed_recurring_amount",
        amount=Money.from_str("2.00"),
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(dup1, dup2))
    with pytest.raises(DuplicateComponentCodeError):
        calculate_employee(employee)


# --- cycle rejection ----------------------------------------------------------


def test_dependency_cycle_is_rejected_with_named_cycle() -> None:
    """A depends on B, B depends on A: a 2-node cycle."""
    a = ComponentInput(
        component_code="A",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("B",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    b = ComponentInput(
        component_code="B",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("A",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(a, b))
    with pytest.raises(CalculationCycleError) as excinfo:
        calculate_employee(employee)
    cycle = excinfo.value.cycle
    # The cycle must actually name A and B (not a generic "a cycle exists").
    assert set(cycle) == {"A", "B"}
    assert cycle[0] == cycle[-1]
    assert len(cycle) >= 3


def test_three_node_dependency_cycle_is_rejected_with_named_cycle() -> None:
    """A -> B -> C -> A."""
    a = ComponentInput(
        component_code="A",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("C",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    b = ComponentInput(
        component_code="B",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("A",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    c = ComponentInput(
        component_code="C",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("B",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(a, b, c))
    with pytest.raises(CalculationCycleError) as excinfo:
        calculate_employee(employee)
    cycle = excinfo.value.cycle
    assert set(cycle) == {"A", "B", "C"}
    assert cycle[0] == cycle[-1]


def test_self_referential_basis_is_a_cycle() -> None:
    a = ComponentInput(
        component_code="A",
        classification="earning",
        calc_kind="percentage_of_component_bases",
        rate=Rate.from_fraction("0.100000"),
        basis=("A",),
        rounding_rule=ROUND_HALF_UP_PAISE,
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(a,))
    with pytest.raises(CalculationCycleError) as excinfo:
        calculate_employee(employee)
    assert excinfo.value.cycle == ("A", "A")


# --- unknown calc_kind propagation --------------------------------------------


def test_unknown_calc_kind_propagates_typed_error_through_calculate_employee() -> None:
    bogus = ComponentInput(
        component_code="X",
        classification="earning",
        calc_kind="not_a_real_kind",
        amount=Money.from_str("1.00"),
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(bogus,))
    with pytest.raises(UnknownCalculatorKindError):
        calculate_employee(employee)


def test_unknown_calc_kind_propagates_through_calculate_run() -> None:
    bogus = ComponentInput(
        component_code="X",
        classification="earning",
        calc_kind="not_a_real_kind",
        amount=Money.from_str("1.00"),
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(bogus,))
    run_input = RunCalcInput(period="2026-06", org_ref="ORG", employees=(employee,))
    with pytest.raises(UnknownCalculatorKindError):
        calculate_run(run_input)


# --- empty run -----------------------------------------------------------------


def test_empty_run_produces_zero_totals_and_a_valid_hash() -> None:
    run_input = RunCalcInput(period="2026-06", org_ref="ORG", employees=())
    result = calculate_run(run_input)
    assert result.employees == ()
    assert result.earnings_total == Money.zero()
    assert result.employer_contribution_total == Money.zero()
    assert result.gross_total == Money.zero()
    assert result.deductions_total == Money.zero()
    assert result.net_payable == Money.zero()
    assert isinstance(result.content_hash, str)
    assert len(result.content_hash) == 64

    # Deterministic even for the empty run.
    result2 = calculate_run(run_input)
    assert result.content_hash == result2.content_hash


def test_employee_with_no_components_produces_zero_totals() -> None:
    employee = EmployeeCalcInput(employee_ref="E1", components=())
    result = calculate_employee(employee)
    assert result.lines == ()
    assert result.earnings_total == Money.zero()
    assert result.net_payable == Money.zero()


# --- hash stability under reordering -----------------------------------------


def _two_employee_run(order: tuple[str, str]) -> RunCalcInput:
    def make(ref: str, amount: str) -> EmployeeCalcInput:
        return EmployeeCalcInput(
            employee_ref=ref,
            components=(
                ComponentInput(
                    component_code="BASIC",
                    classification="earning",
                    calc_kind="fixed_recurring_amount",
                    amount=Money.from_str(amount),
                ),
            ),
        )

    employees_by_ref = {
        "E001": make("E001", "1000.00"),
        "E002": make("E002", "2000.00"),
    }
    return RunCalcInput(
        period="2026-06",
        org_ref="ORG",
        employees=tuple(employees_by_ref[ref] for ref in order),
    )


def test_content_hash_is_stable_under_employee_input_reordering() -> None:
    """Caller order of ``RunCalcInput.employees`` must not affect the hash.

    The engine documents that it sorts employees by ``employee_ref``
    internally before computing, so the same logical set of employees yields
    an identical ``content_hash`` regardless of the order they were supplied
    in.
    """
    forward = calculate_run(_two_employee_run(("E001", "E002")))
    reversed_order = calculate_run(_two_employee_run(("E002", "E001")))
    assert forward.content_hash == reversed_order.content_hash
    assert [e.employee_ref for e in forward.employees] == ["E001", "E002"]
    assert [e.employee_ref for e in reversed_order.employees] == ["E001", "E002"]


def test_content_hash_changes_when_an_amount_changes() -> None:
    base = calculate_run(_two_employee_run(("E001", "E002")))

    def make_changed() -> RunCalcInput:
        return RunCalcInput(
            period="2026-06",
            org_ref="ORG",
            employees=(
                EmployeeCalcInput(
                    employee_ref="E001",
                    components=(
                        ComponentInput(
                            component_code="BASIC",
                            classification="earning",
                            calc_kind="fixed_recurring_amount",
                            amount=Money.from_str("1000.01"),
                        ),
                    ),
                ),
                EmployeeCalcInput(
                    employee_ref="E002",
                    components=(
                        ComponentInput(
                            component_code="BASIC",
                            classification="earning",
                            calc_kind="fixed_recurring_amount",
                            amount=Money.from_str("2000.00"),
                        ),
                    ),
                ),
            ),
        )

    changed = calculate_run(make_changed())
    assert base.content_hash != changed.content_hash


def test_content_hash_binds_employer_transfer_metadata_and_disbursement() -> None:
    def run(*, employer_transfer: bool) -> object:
        employee = EmployeeCalcInput(
            employee_ref="E001",
            components=(
                ComponentInput(
                    component_code="BASIC",
                    classification="earning",
                    calc_kind="fixed_recurring_amount",
                    amount=Money.from_str("1000.00"),
                ),
                ComponentInput(
                    component_code="NPS_EMPLOYER_TRANSFER",
                    classification="AG_deduction",
                    calc_kind="fixed_recurring_amount",
                    amount=Money.from_str("100.00"),
                    employer_transfer=employer_transfer,
                ),
            ),
        )
        return calculate_run(RunCalcInput(period="2026-06", org_ref="ORG", employees=(employee,)))

    ordinary = run(employer_transfer=False)
    offbill = run(employer_transfer=True)
    assert ordinary.content_hash != offbill.content_hash
    assert ordinary.disbursement == Money.from_str("900.00")
    assert offbill.disbursement == Money.from_str("1000.00")


def test_content_hash_binds_export_reason_and_service_period() -> None:
    def run(*, reason: str, service_period: str) -> object:
        employee = EmployeeCalcInput(
            employee_ref="E001",
            components=(
                ComponentInput(
                    component_code="ADJUSTMENT",
                    classification="earning",
                    calc_kind="one_time_adjustment",
                    amount=Money.from_str("100.00"),
                    reason=reason,
                    service_period=service_period,
                ),
            ),
        )
        return calculate_run(RunCalcInput(period="2026-06", org_ref="ORG", employees=(employee,)))

    baseline = run(reason="April arrears", service_period="2026-04-01/2026-04-30")
    changed_reason = run(reason="May arrears", service_period="2026-04-01/2026-04-30")
    changed_period = run(reason="April arrears", service_period="2026-05-01/2026-05-31")

    assert baseline.content_hash != changed_reason.content_hash
    assert baseline.content_hash != changed_period.content_hash
    trace = baseline.employees[0].lines[0]
    assert trace.reason == "April arrears"
    assert trace.service_period == "2026-04-01/2026-04-30"


def test_employer_transfer_requires_matching_contribution_amount() -> None:
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="EPF_EMPLOYER",
                classification="employer_contribution",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("150.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not match"):
        calculate_employee(employee)


def test_employer_transfer_sums_multiple_lines_against_one_contribution() -> None:
    """Two transfer lines whose sum equals the contribution pair cleanly."""
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="EPF_EMPLOYER",
                classification="employer_contribution",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER_A",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("60.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER_B",
                classification="treasury_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("40.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
        ),
    )
    result = calculate_employee(employee)
    # 100 gross addition - 100 paired transfer deductions; off-bill is zero.
    assert result.net_payable == Money.from_str("0.00")
    assert result.offbill_employer_remittance == Money.zero()
    assert result.disbursement == Money.from_str("0.00")


def test_employer_transfer_sum_shortfall_is_rejected() -> None:
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="EPF_EMPLOYER",
                classification="employer_contribution",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER_A",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("60.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER_B",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("30.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not match"):
        calculate_employee(employee)


def test_unpaired_employer_contribution_is_rejected() -> None:
    """A non-excluded employer_contribution with no transfer line would pay
    the employee employer money — it must not survive to net_payable."""
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="BASIC",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("1000.00"),
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER",
                classification="employer_contribution",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("120.00"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="no paired"):
        calculate_employee(employee)


def test_transfer_referencing_missing_contribution_is_rejected() -> None:
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="BASIC",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("1000.00"),
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER",
                classification="AG_deduction",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("120.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
        ),
    )
    with pytest.raises(ValueError, match="missing employer contribution"):
        calculate_employee(employee)


def test_zero_contribution_without_transfer_is_allowed() -> None:
    """A zero-valued contribution carries no employer money — no transfer
    line is required to reverse it."""
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="EPF_EMPLOYER",
                classification="employer_contribution",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("0.00"),
            ),
        ),
    )
    result = calculate_employee(employee)
    assert result.net_payable == Money.zero()


def test_employer_transfer_on_earning_classification_is_rejected() -> None:
    employee = EmployeeCalcInput(
        employee_ref="E001",
        components=(
            ComponentInput(
                component_code="EPF_EMPLOYER",
                classification="employer_contribution",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
            ),
            ComponentInput(
                component_code="EPF_EMPLOYER_TRANSFER",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("100.00"),
                employer_transfer=True,
                transfer_of="EPF_EMPLOYER",
            ),
        ),
    )
    with pytest.raises(ValueError, match="must be a deduction"):
        calculate_employee(employee)


# --- canonical unrounded_value (M-data-4) -------------------------------------


def test_canonical_unrounded_str_normalizes_scientific_and_negative_zero() -> None:
    from app.domain.payroll.results import canonical_unrounded_str

    assert canonical_unrounded_str(Decimal("1E+3")) == "1000"
    assert canonical_unrounded_str(Decimal("-0.00")) == "0.00"
    assert canonical_unrounded_str("1E+3") == "1000"
    assert canonical_unrounded_str(Decimal("1234.567890")) == "1234.567890"
    assert canonical_unrounded_str(Decimal("-42.10")) == "-42.10"


def test_trace_unrounded_value_is_fixed_point_not_scientific() -> None:
    """A tiny unrounded value whose ``str()`` form is scientific notation must
    serialize canonically in the trace so content hashing is stable
    (ADR-0006). 0.01 * 0.000001 -> Decimal('1E-8')."""
    employee = EmployeeCalcInput(
        employee_ref="E1",
        components=(
            ComponentInput(
                component_code="BASIC",
                classification="earning",
                calc_kind="fixed_recurring_amount",
                amount=Money.from_str("0.01"),
            ),
            ComponentInput(
                component_code="DA",
                classification="earning",
                calc_kind="percentage_of_component_bases",
                rate=Rate.from_fraction("0.000001"),
                basis=("BASIC",),
                rounding_rule=ROUND_HALF_UP_PAISE,
            ),
        ),
    )
    result = calculate_employee(employee)
    by_code = {line.component: line for line in result.lines}
    assert str(Decimal("0.01") * Decimal("0.000001")) == "1E-8"  # premise
    assert by_code["DA"].unrounded_value == "0.00000001"
    assert "E" not in by_code["DA"].unrounded_value.upper()


# --- negative gross_adjustment ------------------------------------------------


def test_negative_one_time_adjustment_reduces_gross_and_net() -> None:
    basic = ComponentInput(
        component_code="BASIC",
        classification="earning",
        calc_kind="fixed_recurring_amount",
        amount=Money.from_str("1000.00"),
    )
    adjustment = ComponentInput(
        component_code="ADJ",
        classification="gross_adjustment",
        calc_kind="one_time_adjustment",
        amount=Money.from_decimal(Decimal("-100.00")),
    )
    employee = EmployeeCalcInput(employee_ref="E1", components=(basic, adjustment))
    result = calculate_employee(employee)
    assert result.gross_adjustment_total == Money.from_decimal(Decimal("-100.00"))
    assert result.gross_total == Money.from_str("900.00")
    assert result.net_payable == Money.from_str("900.00")
