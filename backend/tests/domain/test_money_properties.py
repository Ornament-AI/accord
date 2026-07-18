"""Hypothesis property tests and explicit half-up boundary coverage for Money."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings, strategies as st

from app.domain.payroll.money import Money, UnroundedAmount
from app.domain.payroll.rates import Rate
from app.domain.payroll.rounding import (
    ROUND_HALF_UP_PAISE,
    ROUND_HALF_UP_RUPEE,
    apply,
)

# Up to 12-digit rupee amounts with exactly 2 decimal places (paise integers).
_MAX_PAISE = 10**14 - 1  # 999999999999.99


def _money_from_paise(paise: int) -> Money:
    return Money.from_decimal(Decimal(paise) / Decimal("100"))


def _canonical_2dp(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    mag = abs(paise)
    rupees, rem = divmod(mag, 100)
    return f"{sign}{rupees}.{rem:02d}"


def _canonical_rate(micros: int) -> str:
    """``micros`` is rate * 1e6 as a non-negative integer (0 .. 1_000_000)."""
    whole, frac = divmod(micros, 1_000_000)
    return f"{whole}.{frac:06d}"


_paise_strategy = st.integers(min_value=-_MAX_PAISE, max_value=_MAX_PAISE)
_money_strategy = _paise_strategy.map(_money_from_paise)


# --- associativity / commutativity -----------------------------------------


@given(a=_money_strategy, b=_money_strategy)
@settings(max_examples=100)
def test_money_addition_commutative(a: Money, b: Money) -> None:
    assert a + b == b + a


@given(a=_money_strategy, b=_money_strategy, c=_money_strategy)
@settings(max_examples=80)
def test_money_addition_associative(a: Money, b: Money, c: Money) -> None:
    assert (a + b) + c == a + (b + c)


# --- round-trip ------------------------------------------------------------


@given(paise=_paise_strategy)
@settings(max_examples=100)
def test_canonical_str_round_trip(paise: int) -> None:
    raw = _canonical_2dp(paise)
    assert Money.from_str(raw).to_canonical_str() == raw


# --- sum-of-parts ----------------------------------------------------------


@given(parts_paise=st.lists(_paise_strategy, min_size=1, max_size=8))
@settings(max_examples=60)
def test_sum_of_parts_matches_single_quantize(parts_paise: list[int]) -> None:
    """``Money.sum`` equals exact Decimal sum quantized once.

    Per-step rounding of each part (or of running totals) can drift because
    half-up boundaries accumulate differently when quantized N times versus
    once. ``Money.sum`` therefore accumulates under local prec=28 and applies
    ``ROUND_HALF_UP_PAISE`` a single time at the end.
    """
    parts = [_money_from_paise(p) for p in parts_paise]
    exact = sum((Decimal(p) / Decimal("100") for p in parts_paise), Decimal("0"))
    expected = Money.from_decimal(apply(ROUND_HALF_UP_PAISE, exact))
    assert Money.sum(parts) == expected


# --- rate application determinism ------------------------------------------


@given(
    paise=st.integers(min_value=0, max_value=10**10),
    rate_micros=st.integers(min_value=0, max_value=10**6),
)
@settings(max_examples=80)
def test_rate_application_deterministic(paise: int, rate_micros: int) -> None:
    money = _money_from_paise(paise)
    rate = Rate.from_fraction(_canonical_rate(rate_micros))
    first = money * rate
    second = money * rate
    assert isinstance(first, UnroundedAmount)
    assert first.to_decimal() == second.to_decimal()
    assert first.quantize(ROUND_HALF_UP_PAISE) == second.quantize(ROUND_HALF_UP_PAISE)
    assert first.quantize(ROUND_HALF_UP_RUPEE) == second.quantize(ROUND_HALF_UP_RUPEE)


@given(
    value=st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("1000000"),
        allow_nan=False,
        allow_infinity=False,
        places=6,
    )
)
@settings(max_examples=60)
def test_rounding_rule_deterministic(value: Decimal) -> None:
    assert apply(ROUND_HALF_UP_PAISE, value) == apply(ROUND_HALF_UP_PAISE, value)
    assert apply(ROUND_HALF_UP_RUPEE, value) == apply(ROUND_HALF_UP_RUPEE, value)


# --- explicit half-up boundaries (parametrized, not hypothesis) ------------


@pytest.mark.parametrize(
    "value, rule, expected",
    [
        (Decimal("10.125"), ROUND_HALF_UP_PAISE, Decimal("10.13")),
        (Decimal("100.50"), ROUND_HALF_UP_RUPEE, Decimal("101")),
        (Decimal("99.50"), ROUND_HALF_UP_RUPEE, Decimal("100")),
        (Decimal("-100.50"), ROUND_HALF_UP_RUPEE, Decimal("-101")),
        # Positive / negative paise X.x5
        (Decimal("1.005"), ROUND_HALF_UP_PAISE, Decimal("1.01")),
        (Decimal("-1.005"), ROUND_HALF_UP_PAISE, Decimal("-1.01")),
        (Decimal("0.015"), ROUND_HALF_UP_PAISE, Decimal("0.02")),
        (Decimal("-0.015"), ROUND_HALF_UP_PAISE, Decimal("-0.02")),
        (Decimal("2.225"), ROUND_HALF_UP_PAISE, Decimal("2.23")),
        (Decimal("-2.225"), ROUND_HALF_UP_PAISE, Decimal("-2.23")),
        # Positive / negative rupee X.50
        (Decimal("0.50"), ROUND_HALF_UP_RUPEE, Decimal("1")),
        (Decimal("-0.50"), ROUND_HALF_UP_RUPEE, Decimal("-1")),
        (Decimal("10.50"), ROUND_HALF_UP_RUPEE, Decimal("11")),
        (Decimal("-10.50"), ROUND_HALF_UP_RUPEE, Decimal("-11")),
        (Decimal("999.50"), ROUND_HALF_UP_RUPEE, Decimal("1000")),
        (Decimal("-999.50"), ROUND_HALF_UP_RUPEE, Decimal("-1000")),
    ],
)
def test_explicit_half_up_boundaries(value: Decimal, rule: str, expected: Decimal) -> None:
    assert apply(rule, value) == expected


# --- no silent precision loss ----------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "5073200.00",
        "999999999999.99",
        "-999999999999.99",
        "100000000000.00",
        "123456789012.34",
        "-123456789012.34",
    ],
)
def test_large_12_digit_amounts_preserve_exact_2dp(raw: str) -> None:
    m = Money.from_str(raw)
    assert m.amount == Decimal(raw)
    assert m.to_canonical_str() == raw
    assert format(m.amount, ".2f") == raw
