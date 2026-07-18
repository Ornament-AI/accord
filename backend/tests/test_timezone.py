"""Tests for shared IST day-boundary helpers."""

from datetime import UTC, date, datetime

from app.timezone import (
    IST,
    current_ist_date,
    ist_day_start_utc_naive,
    ist_next_day_start_utc_naive,
)


def test_ist_day_start_converts_midnight_to_utc_naive():
    assert ist_day_start_utc_naive(date(2026, 5, 10)) == datetime(2026, 5, 9, 18, 30, 0)


def test_ist_next_day_start_is_half_open_upper_bound():
    assert ist_next_day_start_utc_naive(date(2026, 5, 10)) == datetime(2026, 5, 10, 18, 30, 0)


def test_current_ist_date_rolls_over_at_1830_utc():
    # 18:29 UTC is still the same IST date; 18:30 UTC is the next one.
    before = datetime(2026, 5, 10, 18, 29, tzinfo=UTC).astimezone(IST).date()
    after = datetime(2026, 5, 10, 18, 30, tzinfo=UTC).astimezone(IST).date()
    assert before == date(2026, 5, 10)
    assert after == date(2026, 5, 11)
    # And the helper agrees with the same conversion applied to "now".
    assert current_ist_date() == datetime.now(UTC).astimezone(IST).date()
