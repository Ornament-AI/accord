"""Canonical money and rate wire types (ADR 0006).

Money crosses the API as a canonical decimal string, never as a float. These
Annotated types validate inbound strings into ``Decimal`` and serialize back
out at the canonical scales: money at two places, rates at four.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

__all__ = ["LenientMoneyAmount", "MoneyAmount", "RateValue", "serialize_money", "serialize_rate"]


def require_decimal_string(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("Must be a decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ValueError("Invalid decimal string") from exc
    if not parsed.is_finite():
        raise ValueError("Decimal must be finite")
    return parsed


def require_decimal_or_string(value: Any) -> Decimal:
    """Accept JSON decimal strings and in-process ``Decimal``; reject int/float.

    Used by schemas that services also construct directly with ``Decimal``
    values (e.g. employee create/version inputs).
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, (int, float)) or not isinstance(value, str):
        raise ValueError("Must be a decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ValueError("Invalid decimal string") from exc
    return parsed


def serialize_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def serialize_rate(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001'))}"


MoneyAmount = Annotated[
    Decimal,
    BeforeValidator(require_decimal_string),
    PlainSerializer(serialize_money, return_type=str),
]
RateValue = Annotated[
    Decimal,
    BeforeValidator(require_decimal_string),
    PlainSerializer(serialize_rate, return_type=str),
]
LenientMoneyAmount = Annotated[
    Decimal,
    BeforeValidator(require_decimal_or_string),
    PlainSerializer(serialize_money, return_type=str),
]
