"""Shared helpers for API route handlers."""

from datetime import date

from fastapi import HTTPException, status


def validate_date_range(from_date: date | None, to_date: date | None) -> None:
    """Reject inverted inclusive date ranges."""
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="from_date must be on or before to_date.",
        )
