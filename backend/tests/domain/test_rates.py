"""Unit tests for Rate value object."""

from __future__ import annotations

from decimal import Decimal, getcontext

import pytest

from app.domain.payroll.money import Money, UnroundedAmount
from app.domain.payroll.rates import RATE_SCALE, Rate


def test_rate_scale_is_six() -> None:
    assert RATE_SCALE == 6


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0", Decimal("0")),
        ("0.125", Decimal("0.125")),
        ("0.125000", Decimal("0.125000")),
        ("1", Decimal("1")),
        ("0.000001", Decimal("0.000001")),
        ("-0.125000", Decimal("-0.125000")),
    ],
)
def test_from_fraction_success(raw: str, expected: Decimal) -> None:
    r = Rate.from_fraction(raw)
    assert r.amount == expected
    assert r.to_decimal() == expected


def test_from_percent_converts_to_fraction() -> None:
    r = Rate.from_percent("12.5")
    assert r.amount == Decimal("0.125")
    assert r.to_canonical_str() == "0.125000"


def test_from_percent_zero_and_hundred() -> None:
    assert Rate.from_percent("0").to_canonical_str() == "0.000000"
    assert Rate.from_percent("100").to_canonical_str() == "1.000000"


def test_percent_vs_fraction_are_distinct_constructors() -> None:
    """``12.5`` as percent is 12.5%; as fraction it is 1250%."""
    as_percent = Rate.from_percent("12.5")
    as_fraction = Rate.from_fraction("12.5")
    assert as_percent.to_canonical_str() == "0.125000"
    assert as_fraction.to_canonical_str() == "12.500000"
    assert as_percent != as_fraction


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("0.125", "0.125000"),
        ("0.125000", "0.125000"),
        ("1", "1.000000"),
        ("0", "0.000000"),
        ("-0.12", "-0.120000"),
    ],
)
def test_canonical_str_pads_to_6dp(raw: str, canonical: str) -> None:
    r = Rate.from_fraction(raw)
    assert r.to_canonical_str() == canonical
    assert str(r) == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " 0.1",
        "0.1 ",
        "+0.1",
        "0,125",
        "1e-3",
        "1E-3",
        "0.0000001",  # > 6dp
        "abc",
    ],
)
def test_from_fraction_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        Rate.from_fraction(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " 12.5",
        "+12.5",
        "12,5",
        "1e2",
        "12.5000001",
    ],
)
def test_from_percent_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        Rate.from_percent(raw)


def test_from_percent_rejects_result_exceeding_scale() -> None:
    # 0.000001 / 100 = 0.00000001 → 8 fractional places
    with pytest.raises(ValueError, match="fractional"):
        Rate.from_percent("0.000001")


@pytest.mark.parametrize("bad", [1, 1.5, Decimal("0.1"), None, True])
def test_from_fraction_rejects_non_str(bad: object) -> None:
    with pytest.raises(TypeError):
        Rate.from_fraction(bad)  # type: ignore[arg-type]


def test_from_fraction_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Rate.from_fraction(0.125)  # type: ignore[arg-type]


def test_from_percent_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Rate.from_percent(12.5)  # type: ignore[arg-type]


def test_direct_construction_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Rate(amount=0.125)  # type: ignore[arg-type]


def test_direct_construction_rejects_more_than_6dp() -> None:
    with pytest.raises(ValueError, match="decimal places"):
        Rate(amount=Decimal("0.0000001"))


def test_mul_with_money_both_orders() -> None:
    m = Money.from_str("200.00")
    r = Rate.from_fraction("0.125000")
    left = m * r
    right = r * m
    assert isinstance(left, UnroundedAmount)
    assert isinstance(right, UnroundedAmount)
    assert left.to_decimal() == right.to_decimal() == Decimal("25.000000")
    assert left.currency == "INR"


def test_mul_rejects_float() -> None:
    r = Rate.from_fraction("0.1")
    with pytest.raises(TypeError, match="float"):
        _ = r * 1.5  # type: ignore[operator]


def test_equality() -> None:
    a = Rate.from_fraction("0.125")
    b = Rate.from_fraction("0.125000")
    c = Rate.from_percent("12.5")
    assert a == b
    assert a == c
    assert a != Rate.from_fraction("0.12")
    assert a != Decimal("0.125")


def test_rate_ops_do_not_mutate_global_context() -> None:
    before = (getcontext().prec, getcontext().rounding)
    _ = Rate.from_percent("12.5")
    _ = Rate.from_fraction("0.125") * Money.from_str("100.00")
    assert (getcontext().prec, getcontext().rounding) == before
