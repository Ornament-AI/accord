"""Unit tests for Money/Rate JSON serialization helpers (ADR 0006)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.serialization import parse_money, parse_rate, to_json_str

_BANNED_FLOAT = float("1.5")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Money.from_str("0"), "0.00"),
        (Money.from_str("1.5"), "1.50"),
        (Money.from_str("5073200.00"), "5073200.00"),
        (Money.from_str("-10.25"), "-10.25"),
        (Rate.from_fraction("0.125"), "0.125000"),
        (Rate.from_percent("12.5"), "0.125000"),
        (Rate.from_fraction("0"), "0.000000"),
    ],
)
def test_to_json_str_success(value: Money | Rate, expected: str) -> None:
    assert to_json_str(value) == expected


def test_to_json_str_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        to_json_str(_BANNED_FLOAT)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [Decimal("1.00"), "1.00", 1, None])
def test_to_json_str_rejects_non_money_or_rate(value: object) -> None:
    with pytest.raises(TypeError, match="requires Money or Rate"):
        to_json_str(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("0", "0.00"),
        ("1", "1.00"),
        ("1.5", "1.50"),
        ("1.50", "1.50"),
        ("5073200.00", "5073200.00"),
        ("-0.01", "-0.01"),
    ],
)
def test_parse_money_success(raw: str, canonical: str) -> None:
    money = parse_money(raw)
    assert isinstance(money, Money)
    assert money.to_canonical_str() == canonical


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("0", "0.000000"),
        ("0.125", "0.125000"),
        ("0.125000", "0.125000"),
        ("1", "1.000000"),
        ("0.000001", "0.000001"),
    ],
)
def test_parse_rate_success_fraction_form(raw: str, canonical: str) -> None:
    rate = parse_rate(raw)
    assert isinstance(rate, Rate)
    assert rate.to_canonical_str() == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        " 1.00",
        "1.00 ",
        "+1.00",
        "1,000.00",
        "1e2",
        "1E-2",
        "1.234",
        "abc",
    ],
)
def test_parse_money_rejects_invalid_strings(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_money(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        " 0.1",
        "0.1 ",
        "+0.1",
        "0,125",
        "1e-3",
        "1E-3",
        "0.1234567",
        "abc",
    ],
)
def test_parse_rate_rejects_invalid_strings(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(raw)


def test_parse_money_rejects_int() -> None:
    with pytest.raises(TypeError, match="requires str"):
        parse_money(100)  # type: ignore[arg-type]


def test_parse_money_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        parse_money(_BANNED_FLOAT)  # type: ignore[arg-type]


def test_parse_rate_rejects_int() -> None:
    with pytest.raises(TypeError, match="requires str"):
        parse_rate(1)  # type: ignore[arg-type]


def test_parse_rate_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        parse_rate(_BANNED_FLOAT)  # type: ignore[arg-type]


def test_fewer_than_scale_accepted_and_padded() -> None:
    assert parse_money("10").to_canonical_str() == "10.00"
    assert parse_money("10.5").to_canonical_str() == "10.50"
    assert parse_rate("0.1").to_canonical_str() == "0.100000"
    assert parse_rate("0.125").to_canonical_str() == "0.125000"


def test_round_trip_json_money_and_rate() -> None:
    money = Money.from_str("5073200.00")
    rate = Rate.from_fraction("0.125000")
    assert parse_money(to_json_str(money)) == money
    assert parse_rate(to_json_str(rate)) == rate
