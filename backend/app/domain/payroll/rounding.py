"""Named rounding rules for payroll money (ADR 0006).

Uses a local ``decimal.Context(prec=28)`` for quantize operations and never
mutates the process-global ``decimal.getcontext()``.

``ROUND_DOWN_RUPEE`` uses ``decimal.ROUND_DOWN`` (toward zero), including for
negative values.

``ROUND_NONE`` is identity (no rounding). It is intended for intermediate
values only and is **not** valid for final statutory output, but this module
does not enforce that business rule.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, localcontext
from types import MappingProxyType

ROUND_HALF_UP_PAISE = "ROUND_HALF_UP_PAISE"
ROUND_HALF_UP_RUPEE = "ROUND_HALF_UP_RUPEE"
ROUND_DOWN_RUPEE = "ROUND_DOWN_RUPEE"
ROUND_NONE = "ROUND_NONE"

# Closed registry: quantum Decimal | None, rounding mode | None.
# MappingProxyType prevents callers from registering rules at runtime.
_REGISTRY: MappingProxyType[str, tuple[Decimal | None, str | None]] = MappingProxyType(
    {
        ROUND_HALF_UP_PAISE: (Decimal("0.01"), ROUND_HALF_UP),
        ROUND_HALF_UP_RUPEE: (Decimal("1"), ROUND_HALF_UP),
        # ROUND_DOWN = toward zero (not floor); negatives truncate toward zero.
        ROUND_DOWN_RUPEE: (Decimal("1"), ROUND_DOWN),
        ROUND_NONE: (None, None),
    }
)


class RoundingRuleError(Exception):
    """Raised when ``rule_name`` is not in the closed rounding registry."""


def apply(rule_name: str, value: Decimal) -> Decimal:
    """Apply a named rounding rule to a finite ``Decimal``.

    Returns a new ``Decimal``. ``ROUND_NONE`` returns an identity copy of
    ``value`` (still requires a finite ``Decimal``).
    """
    if isinstance(value, float):
        raise TypeError("float is banned; use decimal.Decimal")
    if not isinstance(value, Decimal):
        raise TypeError(f"value must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError("value must be a finite Decimal (not NaN or Infinity)")

    try:
        quantum, mode = _REGISTRY[rule_name]
    except KeyError as exc:
        raise RoundingRuleError(f"unknown rounding rule: {rule_name!r}") from exc

    if quantum is None:
        # Identity / no rounding (intermediate use only; not enforced here).
        return Decimal(value)

    with localcontext(Context(prec=28, rounding=mode)):
        return value.quantize(quantum)
