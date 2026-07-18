"""Tests for Indian-format INR display helpers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.reports.formatting import format_inr, format_inr_whole


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0"), "0.00"),
        (Decimal("0.00"), "0.00"),
        (Decimal("1"), "1.00"),
        (Decimal("12"), "12.00"),
        (Decimal("100"), "100.00"),
        (Decimal("999"), "999.00"),
        (Decimal("1000"), "1,000.00"),
        (Decimal("1000.5"), "1,000.50"),
        (Decimal("9999"), "9,999.00"),
        (Decimal("10000"), "10,000.00"),
        (Decimal("100000"), "1,00,000.00"),
        (Decimal("5102985.00"), "51,02,985.00"),
        (Decimal("9999999"), "99,99,999.00"),
        (Decimal("10000000"), "1,00,00,000.00"),
        (Decimal("1234567890.50"), "1,23,45,67,890.50"),
        (Decimal("999999999999.99"), "9,99,99,99,99,999.99"),
        ("100", "100.00"),
        (Decimal("-1000.5"), "-1,000.50"),
        (Decimal("-5102985.00"), "-51,02,985.00"),
    ],
)
def test_format_inr(value: Decimal | str, expected: str) -> None:
    assert format_inr(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0.00"), "0"),
        (Decimal("100"), "100"),
        (Decimal("1000"), "1,000"),
        (Decimal("100000"), "1,00,000"),
        (Decimal("5102985.00"), "51,02,985"),
        (Decimal("5102985.99"), "51,02,985"),  # truncate toward zero
        (Decimal("10000000"), "1,00,00,000"),
        (Decimal("1234567890.50"), "1,23,45,67,890"),
        (Decimal("-1000.99"), "-1,000"),
        ("5102985.00", "51,02,985"),
    ],
)
def test_format_inr_whole(value: Decimal | str, expected: str) -> None:
    assert format_inr_whole(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("123"), "123.00"),  # 3-digit
        (Decimal("1234"), "1,234.00"),  # 4-digit / thousand
        (Decimal("123456"), "1,23,456.00"),  # 6-digit / lakh
        (Decimal("12345678"), "1,23,45,678.00"),  # 8-digit
        (Decimal("1234567890"), "1,23,45,67,890.00"),  # 10-digit
        (Decimal("123456789012"), "1,23,45,67,89,012.00"),  # 12-digit
    ],
)
def test_format_inr_grouping_boundaries(value: Decimal, expected: str) -> None:
    assert format_inr(value) == expected


def test_format_inr_float_raises_type_error() -> None:
    with pytest.raises(TypeError, match="float"):
        format_inr(5102985.00)


def test_format_inr_whole_float_raises_type_error() -> None:
    with pytest.raises(TypeError, match="float"):
        format_inr_whole(5102985.00)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "abc",
        "5102985.005",
        "NaN",
        "Infinity",
        "+Infinity",
        "-Infinity",
    ],
)
def test_format_inr_malformed_strings_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        format_inr(bad)
    with pytest.raises(ValueError):
        format_inr_whole(bad)


def test_formatting_modules_have_no_float_calls() -> None:
    reports_dir = Path(__file__).resolve().parents[2] / "app" / "reports"
    for name in ("formatting.py", "_money_input.py", "amount_in_words.py"):
        text = (reports_dir / name).read_text(encoding="utf-8")
        assert "float(" not in text
