"""Strict Decimal money input parsing for report helpers (ADR 0006)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_money_decimal(value: Decimal | str) -> Decimal:
    """Parse a money input as ``Decimal`` under ADR 0006 strictness.

    Accepts ``decimal.Decimal`` or a string that parses cleanly to a finite
    ``Decimal`` with at most 2 decimal places (paise scale).

    Raises:
        TypeError: If ``value`` is a ``float`` (banned) or any non-``Decimal``/
            non-``str`` type.
        ValueError: If the string is empty/whitespace, non-numeric, non-finite
            (NaN/Infinity), or has more than 2 decimal places.
    """
    if isinstance(value, float):
        raise TypeError("float is banned for money values; use decimal.Decimal or a decimal string")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        if not value or value.strip() != value:
            raise ValueError(
                "money string must be a non-empty decimal literal without surrounding whitespace"
            )
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"money string does not parse cleanly to Decimal: {value!r}") from exc
    else:
        raise TypeError(f"money value must be Decimal or str, got {type(value).__name__}")

    if not amount.is_finite():
        raise ValueError("money value must be a finite Decimal (not NaN or Infinity)")

    if amount.as_tuple().exponent < -2:
        raise ValueError("money value must have at most 2 decimal places")

    return amount
