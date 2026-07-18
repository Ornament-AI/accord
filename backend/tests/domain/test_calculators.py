"""Unit tests for the closed calculator registry (all 7 ADR-0007 kinds)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.payroll.calculators import (
    CalculatorContext,
    MissingAmountError,
    MissingBasisComponentError,
    MissingBasisError,
    MissingRateError,
    UnknownCalculatorKindError,
    get,
)
from app.domain.payroll.inputs import ComponentInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.rounding import ROUND_HALF_UP_PAISE, ROUND_HALF_UP_RUPEE


def _ctx(
    *,
    code: str,
    kind: str,
    classification: str = "earning",
    amount: Money | None = None,
    rate: Rate | None = None,
    basis: tuple[str, ...] = (),
    rounding_rule: str = ROUND_HALF_UP_PAISE,
    computed: dict[str, Money] | None = None,
) -> CalculatorContext:
    return CalculatorContext(
        component=ComponentInput(
            component_code=code,
            classification=classification,
            calc_kind=kind,
            amount=amount,
            rate=rate,
            basis=basis,
            rounding_rule=rounding_rule,
        ),
        computed=computed or {},
    )


# --- passthrough kinds ------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "fixed_recurring_amount",
        "direct_monthly_amount",
        "loan_installment_recovery",
        "accommodation_charge",
        "one_time_adjustment",
    ],
)
def test_passthrough_happy_path(kind: str) -> None:
    amount = Money.from_str("1234.56")
    result = get(kind)(_ctx(code="X", kind=kind, amount=amount))
    assert result.rounded_value == amount
    assert result.unrounded_value == Decimal("1234.56")
    assert result.basis_total is None
    assert result.rate is None


@pytest.mark.parametrize(
    "kind",
    [
        "fixed_recurring_amount",
        "direct_monthly_amount",
        "loan_installment_recovery",
        "accommodation_charge",
        "one_time_adjustment",
    ],
)
def test_passthrough_missing_amount(kind: str) -> None:
    with pytest.raises(MissingAmountError):
        get(kind)(_ctx(code="X", kind=kind, amount=None))


def test_one_time_adjustment_allows_negative() -> None:
    amount = Money.from_str("-500.00")
    result = get("one_time_adjustment")(_ctx(code="ADJ", kind="one_time_adjustment", amount=amount))
    assert result.rounded_value == amount
    assert result.unrounded_value == Decimal("-500.00")


# --- percentage / contribution ----------------------------------------------


def test_percentage_of_component_bases_happy_path() -> None:
    computed = {
        "BASIC": Money.from_str("1000.00"),
        "DA": Money.from_str("500.00"),
    }
    rate = Rate.from_fraction("0.125000")
    result = get("percentage_of_component_bases")(
        _ctx(
            code="HRA",
            kind="percentage_of_component_bases",
            rate=rate,
            basis=("BASIC", "DA"),
            rounding_rule=ROUND_HALF_UP_PAISE,
            computed=computed,
        )
    )
    # 1500 * 0.125 = 187.5 -> 187.50 paise half-up
    assert result.basis_total == Money.from_str("1500.00")
    assert result.rate == rate
    assert result.unrounded_value == Decimal("187.5")
    assert result.rounded_value == Money.from_str("187.50")


def test_percentage_rounding_rupee_vs_paise() -> None:
    """Documented difference: HALF_UP_RUPEE vs HALF_UP_PAISE on 187.5."""
    computed = {"BASIC": Money.from_str("1000.00"), "DA": Money.from_str("500.00")}
    rate = Rate.from_fraction("0.125000")
    paise = get("percentage_of_component_bases")(
        _ctx(
            code="HRA",
            kind="percentage_of_component_bases",
            rate=rate,
            basis=("BASIC", "DA"),
            rounding_rule=ROUND_HALF_UP_PAISE,
            computed=computed,
        )
    )
    rupee = get("percentage_of_component_bases")(
        _ctx(
            code="HRA",
            kind="percentage_of_component_bases",
            rate=rate,
            basis=("BASIC", "DA"),
            rounding_rule=ROUND_HALF_UP_RUPEE,
            computed=computed,
        )
    )
    assert paise.unrounded_value == Decimal("187.5")
    assert rupee.unrounded_value == Decimal("187.5")
    assert paise.rounded_value == Money.from_str("187.50")
    assert rupee.rounded_value == Money.from_str("188.00")


def test_percentage_missing_rate() -> None:
    with pytest.raises(MissingRateError):
        get("percentage_of_component_bases")(
            _ctx(
                code="HRA",
                kind="percentage_of_component_bases",
                rate=None,
                basis=("BASIC",),
                computed={"BASIC": Money.from_str("100.00")},
            )
        )


def test_percentage_missing_basis() -> None:
    with pytest.raises(MissingBasisError):
        get("percentage_of_component_bases")(
            _ctx(
                code="HRA",
                kind="percentage_of_component_bases",
                rate=Rate.from_fraction("0.100000"),
                basis=(),
            )
        )


def test_percentage_missing_basis_component() -> None:
    with pytest.raises(MissingBasisComponentError) as excinfo:
        get("percentage_of_component_bases")(
            _ctx(
                code="HRA",
                kind="percentage_of_component_bases",
                rate=Rate.from_fraction("0.100000"),
                basis=("BASIC", "MISSING"),
                computed={"BASIC": Money.from_str("100.00")},
            )
        )
    assert excinfo.value.missing_code == "MISSING"
    assert excinfo.value.requesting_code == "HRA"


def test_employer_employee_contribution_happy_path() -> None:
    computed = {"BASIC": Money.from_str("10000.00")}
    rate = Rate.from_fraction("0.120000")
    result = get("employer_employee_contribution")(
        _ctx(
            code="EPF_EMPLOYEE",
            kind="employer_employee_contribution",
            classification="AG_deduction",
            rate=rate,
            basis=("BASIC",),
            rounding_rule=ROUND_HALF_UP_RUPEE,
            computed=computed,
        )
    )
    assert result.rounded_value == Money.from_str("1200.00")
    assert result.basis_total == Money.from_str("10000.00")


def test_employer_employee_contribution_missing_rate() -> None:
    with pytest.raises(MissingRateError):
        get("employer_employee_contribution")(
            _ctx(
                code="EPF",
                kind="employer_employee_contribution",
                rate=None,
                basis=("BASIC",),
                computed={"BASIC": Money.from_str("1.00")},
            )
        )


# --- registry ---------------------------------------------------------------


def test_unknown_calc_kind_raises_typed_error() -> None:
    with pytest.raises(UnknownCalculatorKindError) as excinfo:
        get("not_a_real_kind")
    assert "not_a_real_kind" in str(excinfo.value)
    assert not isinstance(excinfo.value, KeyError)
