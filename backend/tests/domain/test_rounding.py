"""Unit tests for named rounding rules (ADR 0006)."""

from __future__ import annotations

from decimal import Decimal, getcontext
from types import MappingProxyType

import pytest

from app.domain.payroll.rounding import (
    ROUND_DOWN_RUPEE,
    ROUND_HALF_UP_PAISE,
    ROUND_HALF_UP_RUPEE,
    ROUND_NONE,
    RoundingRuleError,
    _REGISTRY,
    apply,
)

_BANNED_FLOAT = float("1.5")


def test_rule_constants_equal_their_names() -> None:
    assert ROUND_HALF_UP_PAISE == "ROUND_HALF_UP_PAISE"
    assert ROUND_HALF_UP_RUPEE == "ROUND_HALF_UP_RUPEE"
    assert ROUND_DOWN_RUPEE == "ROUND_DOWN_RUPEE"
    assert ROUND_NONE == "ROUND_NONE"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("10.124"), Decimal("10.12")),
        (Decimal("10.125"), Decimal("10.13")),
        (Decimal("10.126"), Decimal("10.13")),
        (Decimal("-10.124"), Decimal("-10.12")),
        (Decimal("-10.125"), Decimal("-10.13")),
        (Decimal("-10.126"), Decimal("-10.13")),
        (Decimal("0.005"), Decimal("0.01")),
        (Decimal("-0.005"), Decimal("-0.01")),
        (Decimal("1.00"), Decimal("1.00")),
    ],
)
def test_half_up_paise_boundaries(value: Decimal, expected: Decimal) -> None:
    assert apply(ROUND_HALF_UP_PAISE, value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("100.49"), Decimal("100")),
        (Decimal("100.50"), Decimal("101")),
        (Decimal("99.50"), Decimal("100")),
        (Decimal("0.50"), Decimal("1")),
        (Decimal("-100.49"), Decimal("-100")),
        (Decimal("-100.50"), Decimal("-101")),
        (Decimal("-99.50"), Decimal("-100")),
        (Decimal("-0.50"), Decimal("-1")),
    ],
)
def test_half_up_rupee_boundaries(value: Decimal, expected: Decimal) -> None:
    assert apply(ROUND_HALF_UP_RUPEE, value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("10.01"), Decimal("10")),
        (Decimal("10.99"), Decimal("10")),
        (Decimal("10.00"), Decimal("10")),
        # ROUND_DOWN is toward zero (not floor).
        (Decimal("-10.01"), Decimal("-10")),
        (Decimal("-10.99"), Decimal("-10")),
        (Decimal("-10.00"), Decimal("-10")),
    ],
)
def test_round_down_rupee_toward_zero(value: Decimal, expected: Decimal) -> None:
    assert apply(ROUND_DOWN_RUPEE, value) == expected


@pytest.mark.parametrize(
    "value",
    [
        Decimal("0"),
        Decimal("10.125"),
        Decimal("-99.999"),
        Decimal("5073200.00"),
    ],
)
def test_round_none_is_identity(value: Decimal) -> None:
    result = apply(ROUND_NONE, value)
    assert result == value
    assert isinstance(result, Decimal)


def test_unknown_rule_raises_rounding_rule_error() -> None:
    with pytest.raises(RoundingRuleError, match="unknown rounding rule"):
        apply("ROUND_BANKERS", Decimal("1.00"))


def test_float_raises_type_error() -> None:
    with pytest.raises(TypeError, match="float"):
        apply(ROUND_HALF_UP_PAISE, _BANNED_FLOAT)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [1, "1.00", None])
def test_non_decimal_raises_type_error(value: object) -> None:
    with pytest.raises(TypeError, match="must be Decimal"):
        apply(ROUND_HALF_UP_PAISE, value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_raises_value_error(value: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        apply(ROUND_HALF_UP_PAISE, value)


def test_getcontext_unchanged_after_apply() -> None:
    before = getcontext().copy()
    apply(ROUND_HALF_UP_PAISE, Decimal("10.125"))
    apply(ROUND_HALF_UP_RUPEE, Decimal("100.50"))
    apply(ROUND_DOWN_RUPEE, Decimal("-10.99"))
    apply(ROUND_NONE, Decimal("1.2345"))
    after = getcontext()
    assert after.prec == before.prec
    assert after.rounding == before.rounding


def test_registry_is_mapping_proxy_and_closed() -> None:
    assert isinstance(_REGISTRY, MappingProxyType)
    with pytest.raises(TypeError):
        _REGISTRY["ROUND_CUSTOM"] = (Decimal("0.01"), "ROUND_HALF_UP")  # type: ignore[index]
    with pytest.raises(TypeError):
        _REGISTRY[ROUND_NONE] = (Decimal("1"), "ROUND_DOWN")  # type: ignore[index]
