"""Indian-format INR display strings for reports.

Grouping follows the Indian numbering system: the last three digits form the
first group, then groups of two digits thereafter (thousand / lakh / crore
boundaries). Examples: ``1,000``, ``1,00,000``, ``1,00,00,000``.

Money policy (ADR 0006): ``float`` is banned; only ``Decimal`` / clean strings
with at most 2 decimal places are accepted.
"""

from __future__ import annotations

from decimal import Decimal

from app.reports._money_input import parse_money_decimal


def _indian_group_digits(digits: str) -> str:
    """Apply Indian comma grouping to an unsigned digit string."""
    if len(digits) <= 3:
        return digits
    last3 = digits[-3:]
    rest = digits[:-3]
    groups: list[str] = []
    while rest:
        groups.append(rest[-2:])
        rest = rest[:-2]
    groups.reverse()
    return ",".join([*groups, last3])


def format_inr(value: Decimal | str) -> str:
    """Format money with Indian digit grouping and always two decimal places.

    Negatives are allowed for display and rendered with a leading ``-``
    (unlike :func:`amount_in_words`, which rejects negatives).

    Examples:
        ``Decimal("5102985.00")`` -> ``"51,02,985.00"``
        ``Decimal("100")`` -> ``"100.00"``
        ``Decimal("1234567890.50")`` -> ``"1,23,45,67,890.50"``
        ``Decimal("-1000.5")`` -> ``"-1,000.50"``

    Raises:
        TypeError: If ``value`` is a ``float`` or other unsupported type.
        ValueError: If ``value`` is malformed, non-finite, or has more than
            2 decimal places.
    """
    amount = parse_money_decimal(value)
    negative = amount < 0
    absolute = -amount if negative else amount

    rupees = int(absolute // 1)
    paise = int((absolute % 1) * 100)
    grouped = _indian_group_digits(str(rupees))
    body = f"{grouped}.{paise:02d}"
    return f"-{body}" if negative else body


def format_inr_whole(value: Decimal | str) -> str:
    """Format the rupee integer part with Indian digit grouping (no decimals).

    The fractional (paise) part is **truncated toward zero** — discarded, not
    rounded. Examples: ``5102985.99`` -> ``"51,02,985"``,
    ``-1000.99`` -> ``"-1,000"``.

    Negatives are allowed for display and rendered with a leading ``-``.

    Raises:
        TypeError: If ``value`` is a ``float`` or other unsupported type.
        ValueError: If ``value`` is malformed, non-finite, or has more than
            2 decimal places.
    """
    amount = parse_money_decimal(value)
    negative = amount < 0
    absolute = -amount if negative else amount
    rupees = int(absolute // 1)
    grouped = _indian_group_digits(str(rupees))
    return f"-{grouped}" if negative else grouped
