"""Canonical JSON-safe encoding/decoding for Money and Rate (ADR 0006).

Encoding delegates entirely to each value object's ``to_canonical_str`` —
this module does **not** reimplement decimal-to-string formatting.

Parsing accepts **only** ``str`` instances (reject ``int``, ``float``, and
any other type with ``TypeError``). Format validation matches the constructors
in ``money.py`` / ``rates.py``:

- Reject scientific notation, thousands separators, leading ``+``,
  leading/trailing whitespace (no strip — reject), and empty strings.
- Money: at most 2 decimal places; fewer than 2 are accepted and padded on
  serialize (same as ``Money.from_str``).
- Rate: ``parse_rate`` expects the **fraction** form at rate scale (6dp max);
  fewer than 6 places accepted and padded on serialize (same as
  ``Rate.from_fraction``).
"""

from __future__ import annotations

from typing import TypeAlias

from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate

MoneyOrRate: TypeAlias = Money | Rate


def to_json_str(money_or_rate: MoneyOrRate) -> str:
    """Return the canonical decimal string for JSON payloads."""
    if isinstance(money_or_rate, float):
        raise TypeError("float is banned; pass Money or Rate")
    if not isinstance(money_or_rate, (Money, Rate)):
        raise TypeError(f"to_json_str requires Money or Rate, got {type(money_or_rate).__name__}")
    return money_or_rate.to_canonical_str()


def parse_money(value: str) -> Money:
    """Parse a canonical money string. Accepts ``str`` only."""
    if isinstance(value, float):
        raise TypeError("float is banned for money JSON; use a decimal string")
    if not isinstance(value, str):
        raise TypeError(f"parse_money requires str, got {type(value).__name__}")
    return Money.from_str(value)


def parse_rate(value: str) -> Rate:
    """Parse a canonical **fraction** rate string. Accepts ``str`` only."""
    if isinstance(value, float):
        raise TypeError("float is banned for rate JSON; use a decimal string")
    if not isinstance(value, str):
        raise TypeError(f"parse_rate requires str, got {type(value).__name__}")
    return Rate.from_fraction(value)
