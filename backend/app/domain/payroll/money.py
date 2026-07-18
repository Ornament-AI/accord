"""INR Money value object and UnroundedAmount intermediate (ADR 0006).

Design decisions
----------------
1. Leading/trailing whitespace is **rejected** (no strip).
2. Leading ``+`` is **rejected**.
3. Fewer than the canonical 2 decimal places are accepted; storage keeps the
   exact value and ``to_canonical_str`` / ``__str__`` pad to 2dp without
   changing the numeric value.
4. Multiplication by a ``Rate`` or ``Decimal`` yields ``UnroundedAmount``
   because the product may have higher precision than money scale; callers
   must apply a named rounding rule explicitly via ``quantize``.
5. ``Money.sum`` accumulates under a local ``Context(prec=28)`` and quantizes
   **once** at the end with ``ROUND_HALF_UP_PAISE``, avoiding per-step
   rounding drift.

Currency is INR only. Float input is banned (``TypeError``). Arithmetic uses
a local ``Context(prec=28)`` and never mutates ``decimal.getcontext()``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext

from app.domain.payroll.rounding import (
    ROUND_HALF_UP_PAISE,
    ROUND_HALF_UP_RUPEE,
    ROUND_NONE,
    apply,
)

_MONEY_SCALE = 2
_CURRENCY_INR = "INR"


class CurrencyMismatchError(ValueError):
    """Raised when Money operands have different currencies."""


def _reject_float(value: object, *, what: str) -> None:
    if isinstance(value, float):
        raise TypeError(f"float is banned for {what}; use Decimal or a decimal string")


def _parse_strict_decimal_string(value: str, *, max_dp: int, what: str) -> Decimal:
    """Parse a strict base-10 decimal literal string.

    Rejects empty strings, leading/trailing whitespace, leading ``+``,
    thousands separators, scientific notation, and more than ``max_dp``
    fractional digits. Accepts fewer than ``max_dp`` places.
    """
    _reject_float(value, what=what)
    if not isinstance(value, str):
        raise TypeError(f"{what} must be str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{what} string must be non-empty")
    if value.strip() != value:
        raise ValueError(f"{what} string must not have leading/trailing whitespace")
    if value.startswith("+"):
        raise ValueError(f"{what} string must not have a leading '+'")
    if "," in value:
        raise ValueError(f"{what} string must not contain thousands separators")
    if "e" in value or "E" in value:
        raise ValueError(f"{what} string must not use scientific notation")

    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{what} string does not parse cleanly to Decimal: {value!r}") from exc

    if not amount.is_finite():
        raise ValueError(f"{what} value must be a finite Decimal (not NaN or Infinity)")

    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -max_dp:
        raise ValueError(f"{what} value must have at most {max_dp} decimal places")

    return amount


@dataclass(frozen=True, slots=True)
class UnroundedAmount:
    """Higher-precision money product awaiting an explicit named rounding rule.

    Exists because ``Money * Rate`` (or ``Money * Decimal``) can exceed the
    canonical 2dp money scale. Callers must call ``quantize(rule_name)`` to
    obtain a ``Money`` value.
    """

    amount: Decimal
    currency: str = _CURRENCY_INR

    def __post_init__(self) -> None:
        _reject_float(self.amount, what="UnroundedAmount.amount")
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"UnroundedAmount.amount must be Decimal, got {type(self.amount).__name__}"
            )
        if not self.amount.is_finite():
            raise ValueError("UnroundedAmount.amount must be finite")
        if self.currency != _CURRENCY_INR:
            raise ValueError(f"currency {self.currency!r} is not supported; only INR")

    def to_decimal(self) -> Decimal:
        return Decimal(self.amount)

    def quantize(self, rule_name: str) -> Money:
        """Apply a named rounding rule and return ``Money``.

        ``ROUND_NONE`` is rejected here: identity on a higher-precision
        intermediate cannot satisfy Money's 2dp invariant. Use
        ``rounding.apply(ROUND_NONE, ...)`` for intermediate passthrough,
        or a paise/rupee rule to produce Money.
        """
        if rule_name == ROUND_NONE:
            raise ValueError(
                "ROUND_NONE is intermediate-only and cannot produce Money; "
                "use rounding.apply for identity, or a paise/rupee rule"
            )
        rounded = apply(rule_name, self.amount)
        return Money.from_decimal(rounded, currency=self.currency)


@dataclass(frozen=True, slots=True)
class Money:
    """Immutable INR money amount at canonical scale 2 (paise)."""

    amount: Decimal
    currency: str = _CURRENCY_INR

    def __post_init__(self) -> None:
        _reject_float(self.amount, what="Money.amount")
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"Money.amount must be Decimal, got {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise ValueError("Money.amount must be finite")
        exponent = self.amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -_MONEY_SCALE:
            raise ValueError("Money.amount must have at most 2 decimal places")
        if self.currency != _CURRENCY_INR:
            raise ValueError(f"currency {self.currency!r} is not supported; only INR")

    @classmethod
    def from_str(cls, value: str) -> Money:
        """Parse a strict money string into ``Money``.

        Accepts fewer than 2 decimal places (value unchanged; padded on
        serialize). Rejects scientific notation, commas, leading ``+``,
        whitespace, empty strings, and more than 2 decimal places.
        """
        amount = _parse_strict_decimal_string(value, max_dp=_MONEY_SCALE, what="money")
        return cls(amount=amount, currency=_CURRENCY_INR)

    @classmethod
    def from_int(cls, value: int) -> Money:
        _reject_float(value, what="money")
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"money from_int requires int, got {type(value).__name__}")
        return cls(amount=Decimal(value), currency=_CURRENCY_INR)

    @classmethod
    def from_decimal(cls, value: Decimal, *, currency: str = _CURRENCY_INR) -> Money:
        _reject_float(value, what="money")
        if not isinstance(value, Decimal):
            raise TypeError(f"money from_decimal requires Decimal, got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError("money value must be a finite Decimal (not NaN or Infinity)")
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -_MONEY_SCALE:
            raise ValueError("money value must have at most 2 decimal places")
        return cls(amount=value, currency=currency)

    @classmethod
    def zero(cls) -> Money:
        return cls(amount=Decimal("0"), currency=_CURRENCY_INR)

    @classmethod
    def sum(cls, items: Iterable[Money]) -> Money:
        """Sum ``Money`` values under ``Context(prec=28)``, quantize once.

        Accumulates underlying ``Decimal`` amounts in a local high-precision
        context, then applies ``ROUND_HALF_UP_PAISE`` a single time. This
        avoids per-step rounding drift that would occur if each addend were
        quantized before summing.
        """
        total = Decimal("0")
        currency: str | None = None
        with localcontext(Context(prec=28)):
            for item in items:
                if isinstance(item, float):
                    raise TypeError("float is banned for money sum")
                if not isinstance(item, Money):
                    raise TypeError(f"Money.sum requires Money items, got {type(item).__name__}")
                if currency is None:
                    currency = item.currency
                elif item.currency != currency:
                    raise CurrencyMismatchError(
                        f"currency mismatch: {currency!r} vs {item.currency!r}"
                    )
                total += item.amount
        if currency is None:
            return cls.zero()
        rounded = apply(ROUND_HALF_UP_PAISE, total)
        return cls.from_decimal(rounded, currency=currency)

    def quantize(self, rule_name: str) -> Money:
        """Apply a named rounding rule and return ``Money``.

        ``ROUND_NONE`` is rejected: use ``rounding.apply`` for identity
        passthrough on intermediate Decimals. Money production requires a
        paise/rupee named rule.
        """
        if rule_name == ROUND_NONE:
            raise ValueError(
                "ROUND_NONE is intermediate-only and cannot produce Money; "
                "use rounding.apply for identity, or a paise/rupee rule"
            )
        rounded = apply(rule_name, self.amount)
        return Money.from_decimal(rounded, currency=self.currency)

    def to_paise(self) -> Money:
        return self.quantize(ROUND_HALF_UP_PAISE)

    def to_rupee(self) -> Money:
        return self.quantize(ROUND_HALF_UP_RUPEE)

    def to_canonical_str(self) -> str:
        """Fixed 2dp canonical string, e.g. ``\"5073200.00\"``."""
        # Pad/format only; amount is already at most 2dp so value is unchanged.
        return format(self.amount, ".2f")

    def __str__(self) -> str:
        return self.to_canonical_str()

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"currency mismatch: {self.currency!r} vs {other.currency!r}"
            )

    def __add__(self, other: object) -> Money:
        if isinstance(other, float):
            raise TypeError("float is banned for money arithmetic")
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        with localcontext(Context(prec=28)):
            result = self.amount + other.amount
        return Money.from_decimal(result, currency=self.currency)

    def __sub__(self, other: object) -> Money:
        if isinstance(other, float):
            raise TypeError("float is banned for money arithmetic")
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        with localcontext(Context(prec=28)):
            result = self.amount - other.amount
        return Money.from_decimal(result, currency=self.currency)

    def __mul__(self, other: object) -> UnroundedAmount:
        """Multiply by ``Rate`` or ``Decimal`` → ``UnroundedAmount``.

        The product may exceed 2dp; apply a named rounding rule explicitly.
        """
        if isinstance(other, float):
            raise TypeError("float is banned for money arithmetic")
        if isinstance(other, Decimal):
            if not other.is_finite():
                raise ValueError("multiplier must be a finite Decimal")
            with localcontext(Context(prec=28)):
                product = self.amount * other
            return UnroundedAmount(amount=product, currency=self.currency)
        # Rate is imported lazily to avoid an import cycle with rates.py.
        from app.domain.payroll.rates import Rate

        if isinstance(other, Rate):
            with localcontext(Context(prec=28)):
                product = self.amount * other.amount
            return UnroundedAmount(amount=product, currency=self.currency)
        return NotImplemented

    def __rmul__(self, other: object) -> UnroundedAmount:
        """Support ``Decimal * Money`` and ``Rate * Money``."""
        return self.__mul__(other)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount >= other.amount
