"""Convert INR money amounts to Indian-English words (cheque / bill style).

Words are a pure function of the numeric amount (``decimal.Decimal`` or a
canonical decimal string). They are never stored or edited as an independent
string that could drift from the number (see report-catalog reconciliation).

Indian numbering units used (largest first): crore, lakh, thousand, hundred,
then tens/units. The units ``arab`` and ``kharab`` are intentionally **not**
supported.

Cap (rupee integer part):
    Supported inclusive range: ``0`` .. ``9_999_999_999``
    (Indian display ``9,99,99,99,999`` — up to
    "Nine Hundred Ninety Nine Crore Ninety Nine Lakh Ninety Nine Thousand
    Nine Hundred Ninety Nine").
    Values with rupee integer part ``>= 10_000_000_000``
    (``10,00,00,00,000``, one thousand crore) raise ``ValueError``.

Money policy (ADR 0006): ``float`` is banned; only ``Decimal`` / clean strings
with at most 2 decimal places are accepted. Final INR amounts use paise scale.
"""

from __future__ import annotations

from decimal import Decimal

from app.reports._money_input import parse_money_decimal

# Inclusive maximum rupee integer part (9,99,99,99,999).
MAX_RUPEES_INCLUSIVE = 9_999_999_999
# First unsupported rupee integer part (10,00,00,00,000).
MIN_UNSUPPORTED_RUPEES = 10_000_000_000

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
)

_TEENS = (
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)

_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)


def _words_under_100(n: int) -> str:
    """Return Indian-English words for ``n`` in ``0..99`` (empty string for 0)."""
    if n == 0:
        return ""
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _TENS[tens]
    return f"{_TENS[tens]} {_ONES[ones]}"


def _words_under_1000(n: int) -> str:
    """Return Indian-English words for ``n`` in ``0..999`` (empty string for 0)."""
    if n == 0:
        return ""
    hundreds, rest = divmod(n, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    rest_words = _words_under_100(rest)
    if rest_words:
        parts.append(rest_words)
    return " ".join(parts)


def _rupees_in_words(rupees: int) -> str:
    """Convert a non-negative rupee integer (within cap) to Indian-English words."""
    if rupees == 0:
        return "Zero"

    crore, rem = divmod(rupees, 10_000_000)
    lakh, rem = divmod(rem, 100_000)
    thousand, hundred = divmod(rem, 1_000)

    parts: list[str] = []
    if crore:
        parts.append(f"{_words_under_1000(crore)} Crore")
    if lakh:
        parts.append(f"{_words_under_100(lakh)} Lakh")
    if thousand:
        parts.append(f"{_words_under_100(thousand)} Thousand")
    if hundred:
        parts.append(_words_under_1000(hundred))
    return " ".join(parts)


def amount_in_words(value: Decimal | str) -> str:
    """Convert an INR money amount to Indian-English cheque/bill words.

    Args:
        value: Non-negative money as ``Decimal`` or a clean decimal string with
            at most 2 decimal places (e.g. ``"5102985.00"``).

    Returns:
        A string such as
        ``"Rupees Fifty One Lakh Two Thousand Nine Hundred Eighty Five Only"``
        when paise are zero, or
        ``"Rupees One Hundred and Paise Twenty Five Only"`` when paise are
        non-zero.

    Raises:
        TypeError: If ``value`` is a ``float`` or other unsupported type.
        ValueError: If ``value`` is malformed, negative, non-finite, has more
            than 2 decimal places, or the rupee integer part is at or above
            ``10_000_000_000``.
    """
    amount = parse_money_decimal(value)

    if amount < 0:
        raise ValueError("amount_in_words does not support negative amounts")

    # Split into rupees and paise without float arithmetic.
    rupees = int(amount // 1)
    paise = int((amount % 1) * 100)

    if rupees >= MIN_UNSUPPORTED_RUPEES:
        raise ValueError(
            f"amount exceeds supported cap (rupee integer part must be <= {MAX_RUPEES_INCLUSIVE})"
        )

    rupee_words = _rupees_in_words(rupees)
    if paise == 0:
        return f"Rupees {rupee_words} Only"

    paise_words = _words_under_100(paise)
    return f"Rupees {rupee_words} and Paise {paise_words} Only"
