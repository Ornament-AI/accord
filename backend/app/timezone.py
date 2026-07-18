"""Shared business timezone helpers.

Accord stores clock timestamps as UTC-naive datetimes. User-facing day
boundaries and labels use Asia/Kolkata (IST).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def current_ist_date() -> date:
    """Today's calendar date in IST."""
    return datetime.now(tz=UTC).astimezone(IST).date()


def ist_day_start_utc_naive(day: date) -> datetime:
    """UTC-naive instant of IST midnight for ``day``."""
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=IST)
    return local_midnight.astimezone(UTC).replace(tzinfo=None)


def ist_next_day_start_utc_naive(day: date) -> datetime:
    """UTC-naive instant of IST midnight for the day after ``day``."""
    return ist_day_start_utc_naive(day + timedelta(days=1))
