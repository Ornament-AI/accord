"""Tests for Indian-English amount-in-words conversion."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.reports.amount_in_words import (
    MAX_RUPEES_INCLUSIVE,
    MIN_UNSUPPORTED_RUPEES,
    amount_in_words,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0"), "Rupees Zero Only"),
        (Decimal("0.00"), "Rupees Zero Only"),
        (Decimal("1"), "Rupees One Only"),
        (Decimal("9"), "Rupees Nine Only"),
        (Decimal("10"), "Rupees Ten Only"),
        (Decimal("11"), "Rupees Eleven Only"),
        (Decimal("19"), "Rupees Nineteen Only"),
        (Decimal("20"), "Rupees Twenty Only"),
        (Decimal("21"), "Rupees Twenty One Only"),
        (Decimal("99"), "Rupees Ninety Nine Only"),
        (Decimal("100"), "Rupees One Hundred Only"),
        (Decimal("101"), "Rupees One Hundred One Only"),
        (Decimal("111"), "Rupees One Hundred Eleven Only"),
        (Decimal("199"), "Rupees One Hundred Ninety Nine Only"),
        (Decimal("200"), "Rupees Two Hundred Only"),
        (Decimal("999"), "Rupees Nine Hundred Ninety Nine Only"),
        (Decimal("1000"), "Rupees One Thousand Only"),
        (Decimal("1001"), "Rupees One Thousand One Only"),
        (Decimal("9999"), "Rupees Nine Thousand Nine Hundred Ninety Nine Only"),
        (Decimal("100000"), "Rupees One Lakh Only"),
        (Decimal("100001"), "Rupees One Lakh One Only"),
        (
            Decimal("9999999"),
            "Rupees Ninety Nine Lakh Ninety Nine Thousand Nine Hundred Ninety Nine Only",
        ),
        (Decimal("10000000"), "Rupees One Crore Only"),
        (Decimal("10000001"), "Rupees One Crore One Only"),
        (
            Decimal(str(MAX_RUPEES_INCLUSIVE)),
            "Rupees Nine Hundred Ninety Nine Crore Ninety Nine Lakh "
            "Ninety Nine Thousand Nine Hundred Ninety Nine Only",
        ),
    ],
)
def test_number_name_boundaries(value: Decimal, expected: str) -> None:
    assert amount_in_words(value) == expected


def test_gross_bill_june_2026_invariant() -> None:
    assert amount_in_words(Decimal("5102985.00")) == (
        "Rupees Fifty One Lakh Two Thousand Nine Hundred Eighty Five Only"
    )


def test_net_payable_june_2026_invariant() -> None:
    assert amount_in_words(Decimal("3838095.00")) == (
        "Rupees Thirty Eight Lakh Thirty Eight Thousand Ninety Five Only"
    )


def test_total_deductions_june_2026_invariant() -> None:
    assert amount_in_words(Decimal("1264890.00")) == (
        "Rupees Twelve Lakh Sixty Four Thousand Eight Hundred Ninety Only"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("100.00"), "Rupees One Hundred Only"),
        (Decimal("100.01"), "Rupees One Hundred and Paise One Only"),
        (Decimal("100.05"), "Rupees One Hundred and Paise Five Only"),
        (Decimal("100.10"), "Rupees One Hundred and Paise Ten Only"),
        (Decimal("100.25"), "Rupees One Hundred and Paise Twenty Five Only"),
        (Decimal("100.50"), "Rupees One Hundred and Paise Fifty Only"),
        (Decimal("100.99"), "Rupees One Hundred and Paise Ninety Nine Only"),
        (Decimal("0.50"), "Rupees Zero and Paise Fifty Only"),
        (Decimal("0.01"), "Rupees Zero and Paise One Only"),
        (Decimal("0.99"), "Rupees Zero and Paise Ninety Nine Only"),
        ("5102985.00", "Rupees Fifty One Lakh Two Thousand Nine Hundred Eighty Five Only"),
    ],
)
def test_paise_variants(value: Decimal | str, expected: str) -> None:
    assert amount_in_words(value) == expected


def test_just_above_cap_raises() -> None:
    with pytest.raises(ValueError, match="cap"):
        amount_in_words(Decimal(str(MIN_UNSUPPORTED_RUPEES)))


def test_float_input_raises_type_error() -> None:
    with pytest.raises(TypeError, match="float"):
        amount_in_words(5102985.00)  # intentional float input


def test_negative_amount_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        amount_in_words(Decimal("-1.00"))


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
def test_malformed_strings_raise_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        amount_in_words(bad)


def test_int_input_raises_type_error() -> None:
    with pytest.raises(TypeError):
        amount_in_words(100)  # type: ignore[arg-type]


def test_pragmatic_tens_units_reverse_mapping() -> None:
    """Catch systematic tens/units bugs via a small reverse word table."""
    reverse = {
        "One": 1,
        "Two": 2,
        "Three": 3,
        "Four": 4,
        "Five": 5,
        "Six": 6,
        "Seven": 7,
        "Eight": 8,
        "Nine": 9,
        "Ten": 10,
        "Eleven": 11,
        "Twelve": 12,
        "Thirteen": 13,
        "Fourteen": 14,
        "Fifteen": 15,
        "Sixteen": 16,
        "Seventeen": 17,
        "Eighteen": 18,
        "Nineteen": 19,
        "Twenty": 20,
        "Twenty One": 21,
        "Thirty Five": 35,
        "Forty Two": 42,
        "Fifty": 50,
        "Sixty Seven": 67,
        "Seventy Eight": 78,
        "Eighty Five": 85,
        "Ninety Nine": 99,
    }
    samples = [
        Decimal("21"),
        Decimal("35"),
        Decimal("42"),
        Decimal("67"),
        Decimal("78"),
        Decimal("85"),
        Decimal("99"),
        Decimal("185"),
        Decimal("1299"),
        Decimal("5102985.00"),
    ]
    for amount in samples:
        words = amount_in_words(amount)
        # Strip leading "Rupees " and trailing " Only".
        body = words.removeprefix("Rupees ").removesuffix(" Only")
        last_two_digits = int(amount // 1) % 100
        if last_two_digits == 0:
            continue
        # Prefer two-word tens+ones match, else single word.
        matched = False
        for phrase, value in reverse.items():
            if body.endswith(phrase) and value == last_two_digits:
                matched = True
                break
        assert matched, f"no reverse match for {amount} -> {words!r}"


def test_module_has_no_float_calls() -> None:
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "app" / "reports" / "amount_in_words.py"
    text = source.read_text(encoding="utf-8")
    assert "float(" not in text
