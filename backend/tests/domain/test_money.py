"""Exhaustive unit tests for Money and UnroundedAmount."""

from __future__ import annotations

from decimal import Decimal, getcontext

import pytest

from app.domain.payroll.money import CurrencyMismatchError, Money, UnroundedAmount
from app.domain.payroll.rates import Rate
from app.domain.payroll.rounding import (
    ROUND_DOWN_RUPEE,
    ROUND_HALF_UP_PAISE,
    ROUND_HALF_UP_RUPEE,
    ROUND_NONE,
    apply,
)


def _money_with_currency(amount: str, currency: str) -> Money:
    """Bypass INR-only validation to exercise CurrencyMismatchError paths."""
    m = Money.__new__(Money)
    object.__setattr__(m, "amount", Decimal(amount))
    object.__setattr__(m, "currency", currency)
    return m


def _snapshot_context() -> tuple[int, str]:
    ctx = getcontext()
    return ctx.prec, ctx.rounding


# --- constructors: success -------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0", Decimal("0")),
        ("0.1", Decimal("0.1")),
        ("0.10", Decimal("0.10")),
        ("1", Decimal("1")),
        ("1.2", Decimal("1.2")),
        ("1.23", Decimal("1.23")),
        ("5073200.00", Decimal("5073200.00")),
        ("-1.25", Decimal("-1.25")),
        ("-0.01", Decimal("-0.01")),
    ],
)
def test_from_str_success(raw: str, expected: Decimal) -> None:
    m = Money.from_str(raw)
    assert m.amount == expected
    assert m.currency == "INR"


def test_from_int_success() -> None:
    assert Money.from_int(42).amount == Decimal("42")
    assert Money.from_int(0).amount == Decimal("0")
    assert Money.from_int(-7).amount == Decimal("-7")


def test_from_decimal_success() -> None:
    assert Money.from_decimal(Decimal("1.5")).amount == Decimal("1.5")
    assert Money.from_decimal(Decimal("0")).currency == "INR"


def test_zero() -> None:
    z = Money.zero()
    assert z.amount == Decimal("0")
    assert z.currency == "INR"
    assert z.to_canonical_str() == "0.00"


def test_direct_construction_success() -> None:
    m = Money(amount=Decimal("10.5"), currency="INR")
    assert m.amount == Decimal("10.5")


# --- constructors: failure -------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        " 1.00",
        "1.00 ",
        "1.00\n",
        "+1.00",
        "+0",
        "1,000.00",
        "1e2",
        "1E2",
        "1.2e1",
        "1.001",
        "0.001",
        "abc",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_from_str_rejects_invalid_format(raw: str) -> None:
    with pytest.raises(ValueError):
        Money.from_str(raw)


@pytest.mark.parametrize("bad", [1, 1.5, Decimal("1.00"), None, True, b"1.00"])
def test_from_str_rejects_non_str(bad: object) -> None:
    with pytest.raises(TypeError):
        Money.from_str(bad)  # type: ignore[arg-type]


def test_from_str_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Money.from_str(1.5)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [True, False, 1.5, "1", Decimal("1"), None, 1.0])
def test_from_int_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        Money.from_int(bad)  # type: ignore[arg-type]


def test_from_int_rejects_bool_explicitly() -> None:
    with pytest.raises(TypeError, match="int"):
        Money.from_int(True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [1, "1.00", 1.5, None, True])
def test_from_decimal_rejects_non_decimal(bad: object) -> None:
    with pytest.raises(TypeError):
        Money.from_decimal(bad)  # type: ignore[arg-type]


def test_from_decimal_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Money.from_decimal(1.5)  # type: ignore[arg-type]


def test_from_decimal_rejects_more_than_2dp() -> None:
    with pytest.raises(ValueError, match="decimal places"):
        Money.from_decimal(Decimal("1.001"))


def test_from_decimal_rejects_non_inr_currency() -> None:
    with pytest.raises(ValueError, match="INR"):
        Money.from_decimal(Decimal("1.00"), currency="USD")


def test_direct_construction_rejects_float_amount() -> None:
    with pytest.raises(TypeError, match="float"):
        Money(amount=1.5)  # type: ignore[arg-type]


def test_unrounded_rejects_float_amount() -> None:
    with pytest.raises(TypeError, match="float"):
        UnroundedAmount(amount=1.5)  # type: ignore[arg-type]


# --- arithmetic ------------------------------------------------------------


def test_add_sub_money() -> None:
    a = Money.from_str("10.25")
    b = Money.from_str("0.75")
    assert (a + b).to_canonical_str() == "11.00"
    assert (a - b).to_canonical_str() == "9.50"


def test_mul_by_decimal_yields_unrounded() -> None:
    m = Money.from_str("100.00")
    product = m * Decimal("0.125")
    assert isinstance(product, UnroundedAmount)
    assert product.to_decimal() == Decimal("12.500")
    assert product.currency == "INR"


def test_mul_by_rate_both_orders() -> None:
    m = Money.from_str("1000.00")
    r = Rate.from_percent("12.5")
    left = m * r
    right = r * m
    assert isinstance(left, UnroundedAmount)
    assert isinstance(right, UnroundedAmount)
    assert left.to_decimal() == right.to_decimal() == Decimal("125.000000")


def test_rmul_decimal() -> None:
    m = Money.from_str("10.00")
    product = Decimal("2") * m
    assert isinstance(product, UnroundedAmount)
    assert product.to_decimal() == Decimal("20.00")


@pytest.mark.parametrize(
    "op",
    [
        lambda a, b: a + b,
        lambda a, b: a - b,
        lambda a, b: a * b,
    ],
)
def test_arithmetic_rejects_float(op: object) -> None:
    m = Money.from_str("1.00")
    with pytest.raises(TypeError, match="float"):
        op(m, 1.5)  # type: ignore[operator]


def test_add_currency_mismatch() -> None:
    a = Money.from_str("1.00")
    b = _money_with_currency("1.00", "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = a + b


def test_sub_currency_mismatch() -> None:
    a = Money.from_str("1.00")
    b = _money_with_currency("1.00", "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = a - b


# --- comparisons -----------------------------------------------------------


def test_comparisons() -> None:
    a = Money.from_str("1.00")
    b = Money.from_str("2.00")
    c = Money.from_str("1.00")
    assert a == c
    assert a != b
    assert a < b
    assert a <= b
    assert a <= c
    assert b > a
    assert b >= a
    assert c >= a


def test_eq_with_non_money_is_false() -> None:
    assert Money.from_str("1.00") != Decimal("1.00")
    assert Money.from_str("1.00") != "1.00"


def test_comparison_currency_mismatch() -> None:
    a = Money.from_str("1.00")
    b = _money_with_currency("2.00", "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = a < b


# --- sum / quantize / paise / rupee ----------------------------------------


def test_sum_empty_is_zero() -> None:
    assert Money.sum([]) == Money.zero()


def test_sum_basic() -> None:
    items = [Money.from_str("1.11"), Money.from_str("2.22"), Money.from_str("3.33")]
    assert Money.sum(items).to_canonical_str() == "6.66"


def test_sum_quantizes_once_with_half_up_paise() -> None:
    """Money.sum accumulates Decimals then applies ROUND_HALF_UP_PAISE once.

    Per-step rounding of intermediate Money values can drift from this
    single final quantize; callers that need a shared total should prefer
    ``Money.sum`` (or an explicit unrounded accumulation) over rounding
    each part before adding.
    """
    parts = [
        Money.from_str("0.01"),
        Money.from_str("0.02"),
        Money.from_str("0.03"),
    ]
    exact = sum((p.amount for p in parts), Decimal("0"))
    assert Money.sum(parts) == Money.from_decimal(apply(ROUND_HALF_UP_PAISE, exact))


def test_sum_currency_mismatch() -> None:
    items = [Money.from_str("1.00"), _money_with_currency("1.00", "USD")]
    with pytest.raises(CurrencyMismatchError):
        Money.sum(items)


def test_sum_rejects_float_item() -> None:
    with pytest.raises(TypeError, match="float"):
        Money.sum([Money.from_str("1.00"), 1.5])  # type: ignore[list-item]


def test_sum_rejects_non_money_item() -> None:
    with pytest.raises(TypeError, match="Money"):
        Money.sum([Money.from_str("1.00"), Decimal("1.00")])  # type: ignore[list-item]


def test_quantize_to_paise_and_rupee() -> None:
    m = Money.from_str("10.12")
    assert m.to_paise().to_canonical_str() == "10.12"
    assert m.to_rupee().to_canonical_str() == "10.00"
    half = Money.from_str("10.50")
    assert half.to_rupee().to_canonical_str() == "11.00"
    assert half.quantize(ROUND_HALF_UP_PAISE).to_canonical_str() == "10.50"
    assert half.quantize(ROUND_HALF_UP_RUPEE).to_canonical_str() == "11.00"


def test_quantize_round_down_rupee_toward_zero() -> None:
    assert Money.from_str("10.99").quantize(ROUND_DOWN_RUPEE).to_canonical_str() == "10.00"
    assert Money.from_str("-10.99").quantize(ROUND_DOWN_RUPEE).to_canonical_str() == "-10.00"


def test_unrounded_construction_and_rejects() -> None:
    u = UnroundedAmount(amount=Decimal("12.3456"))
    assert u.to_decimal() == Decimal("12.3456")
    assert u.currency == "INR"
    with pytest.raises(TypeError, match="must be Decimal"):
        UnroundedAmount(amount="1.00")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        UnroundedAmount(amount=Decimal("NaN"))
    with pytest.raises(ValueError, match="not supported"):
        UnroundedAmount(amount=Decimal("1"), currency="USD")


def test_unrounded_quantize_to_money() -> None:
    u = UnroundedAmount(amount=Decimal("10.125"))
    assert u.quantize(ROUND_HALF_UP_PAISE).to_canonical_str() == "10.13"
    assert u.quantize(ROUND_HALF_UP_RUPEE).to_canonical_str() == "10.00"


def test_unrounded_quantize_round_none_raises() -> None:
    u = UnroundedAmount(amount=Decimal("10.125"))
    with pytest.raises(ValueError, match="ROUND_NONE"):
        u.quantize(ROUND_NONE)


def test_money_quantize_round_none_raises() -> None:
    with pytest.raises(ValueError, match="ROUND_NONE"):
        Money.from_str("10.12").quantize(ROUND_NONE)


# --- canonical strings -----------------------------------------------------


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("0", "0.00"),
        ("1", "1.00"),
        ("1.2", "1.20"),
        ("1.23", "1.23"),
        ("5073200.00", "5073200.00"),
        ("-1", "-1.00"),
        ("-1.2", "-1.20"),
        ("-1.25", "-1.25"),
        ("-0.01", "-0.01"),
    ],
)
def test_canonical_str_and_str(raw: str, canonical: str) -> None:
    m = Money.from_str(raw)
    assert m.to_canonical_str() == canonical
    assert str(m) == canonical


def test_proven_aggregate_round_trip() -> None:
    """Proven June 2026 aggregate string must round-trip unchanged."""
    raw = "5073200.00"
    assert Money.from_str(raw).to_canonical_str() == raw


# --- global context isolation ----------------------------------------------


def test_operations_do_not_mutate_global_decimal_context() -> None:
    before = _snapshot_context()
    a = Money.from_str("100.00")
    b = Money.from_str("0.01")
    _ = a + b
    _ = a - b
    _ = a * Decimal("0.125")
    _ = a * Rate.from_fraction("0.120000")
    _ = Money.sum([a, b, Money.from_str("9.99")])
    _ = UnroundedAmount(amount=Decimal("1.234")).quantize(ROUND_HALF_UP_PAISE)
    _ = a.to_paise()
    _ = a.to_rupee()
    assert _snapshot_context() == before
