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
