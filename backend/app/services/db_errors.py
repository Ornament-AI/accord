"""Shared mapping from database ``IntegrityError`` to API-facing errors.

Postgres constraint violations surface through SQLAlchemy as
:class:`~sqlalchemy.exc.IntegrityError` wrapping an asyncpg exception. This
module owns the one canonical translation to Accord's HTTP error taxonomy so
services do not each grow a slightly different copy.
"""

from __future__ import annotations

from typing import NoReturn

from asyncpg.exceptions import CheckViolationError, ExclusionViolationError, UniqueViolationError
from sqlalchemy.exc import IntegrityError

from app.exceptions import ConflictError, ValidationError

__all__ = ["integrity_is", "raise_integrity_error"]


def integrity_is(exc: BaseException, *types: type[BaseException]) -> bool:
    """Walk SQLAlchemy/asyncpg exception wrappers for a concrete PG error type."""
    stack: list[BaseException | None] = [exc]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, types):
            return True
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
        stack.append(current.__cause__)
        stack.append(getattr(current, "orig", None))
    return False


def raise_integrity_error(exc: IntegrityError) -> NoReturn:
    """Re-raise ``exc`` as the API error matching its Postgres violation.

    Unique -> 409 conflict; exclusion (version-range overlap) -> 409 conflict;
    check -> 422 validation; anything else -> generic 409 conflict.
    """
    if integrity_is(exc, UniqueViolationError):
        raise ConflictError("A conflicting record already exists.") from exc
    if integrity_is(exc, ExclusionViolationError):
        raise ConflictError("Version periods overlap.") from exc
    if integrity_is(exc, CheckViolationError):
        raise ValidationError("Request violates a database constraint.") from exc
    raise ConflictError("Database constraint violation.") from exc
