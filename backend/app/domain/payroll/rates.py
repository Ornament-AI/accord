"""Rate value object for payroll fractions (ADR 0006).

Internal representation is a dimensionless **fraction** (not percent),
e.g. ``0.125000`` means 12.5%. Canonical scale is **6** decimal places
(within ADR 0006's recommended 4–6 digits for rates).

Design decisions
----------------
1. ``Rate.from_fraction`` parses an already-resolved fraction string.
2. ``Rate.from_percent`` parses a percent string (e.g. ``\"12.5\"`` for 12.5%)
   and divides by 100 under a local ``Context(prec=28)``. The two constructors
   are deliberately distinct so callers cannot confuse percent vs fraction.
3. Fewer than 6 fractional digits are accepted; ``to_canonical_str`` /
   ``__str__`` zero-pad to 6dp without changing the numeric value.
4. More than 6 fractional digits are rejected.
5. Leading/trailing whitespace and leading ``+`` are rejected (same as Money).
6. Float input is banned (``TypeError``).
7. ``Rate * Money`` and ``Money * Rate`` yield ``UnroundedAmount`` under a
   local ``Context(prec=28)``; callers must round via a named rule in
   ``rounding.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from typing import TYPE_CHECKING

from app.domain.payroll.money import _parse_strict_decimal_string, _reject_float

if TYPE_CHECKING:
    from app.domain.payroll.money import UnroundedAmount

RATE_SCALE = 6
_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class Rate:
    """Immutable payroll rate stored as a fraction at scale ``RATE_SCALE`` (6)."""

    amount: Decimal

    def __post_init__(self) -> None:
        _reject_float(self.amount, what="Rate.amount")
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"Rate.amount must be Decimal, got {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise ValueError("Rate.amount must be finite")
        exponent = self.amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -RATE_SCALE:
            raise ValueError(f"Rate.amount must have at most {RATE_SCALE} decimal places")

    @classmethod
    def from_fraction(cls, value: str) -> Rate:
        """Parse a canonical fraction string (e.g. ``\"0.125000\"`` = 12.5%)."""
        amount = _parse_strict_decimal_string(value, max_dp=RATE_SCALE, what="rate fraction")
        return cls(amount=amount)

    @classmethod
    def from_percent(cls, value: str) -> Rate:
        """Parse a percent string (e.g. ``\"12.5\"`` → fraction ``0.125000``).

        The percent literal may have at most ``RATE_SCALE`` fractional digits.
        After dividing by 100, the resulting fraction must still fit in
        ``RATE_SCALE`` decimal places (no silent rounding on construction).
        """
        percent = _parse_strict_decimal_string(value, max_dp=RATE_SCALE, what="rate percent")
        with localcontext(Context(prec=28)):
            fraction = percent / _HUNDRED
        exponent = fraction.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -RATE_SCALE:
            raise ValueError(
                f"rate percent {value!r} resolves to more than {RATE_SCALE} "
                "fractional decimal places"
            )
        return cls(amount=fraction)

    def to_decimal(self) -> Decimal:
        return Decimal(self.amount)

    def to_canonical_str(self) -> str:
        """Fixed 6dp canonical fraction string, e.g. ``\"0.125000\"``."""
        return format(self.amount, ".6f")

    def __str__(self) -> str:
        return self.to_canonical_str()

    def __mul__(self, other: object) -> UnroundedAmount:
        """Multiply by ``Money`` → ``UnroundedAmount`` (local prec=28)."""
        if isinstance(other, float):
            raise TypeError("float is banned for rate arithmetic")
        from app.domain.payroll.money import Money, UnroundedAmount

        if isinstance(other, Money):
            with localcontext(Context(prec=28)):
                product = other.amount * self.amount
            return UnroundedAmount(amount=product, currency=other.currency)
        return NotImplemented

    def __rmul__(self, other: object) -> UnroundedAmount:
        return self.__mul__(other)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Rate):
            return NotImplemented
        return self.amount == other.amount
