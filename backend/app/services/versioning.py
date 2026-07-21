"""Shared effective-dated version helpers (ADR-0005 clip-and-insert).

Public contract for all Phase 3 master-data lanes. Dependency-light: only
SQLAlchemy, ``app.exceptions``, and ``app.models.effective``.

Half-open Postgres ``daterange`` semantics ``[effective_from, effective_to)``
are used throughout. Open-ended versions use ``upper = NULL``.

Clip-and-insert ordering (GiST EXCLUDE is NOT deferrable):
1. Locate the currently open version (``upper_inf(validity)``).
2. Reject ``effective_from <= lower(open.validity)`` with ``ConflictError``.
3. Reject ``effective_from`` that lands inside / at-or-after another historical
   version (excluding the open row being clipped).
4. UPDATE the open row's validity to ``[old_lower, effective_from)`` and flush.
5. INSERT the new open-ended row ``[effective_from, )`` and flush.
6. Map residual GiST ``ExclusionViolation`` / ``IntegrityError`` to
   ``ConflictError`` (409).

Public API
----------
- ``insert_version(session, version_table, *, organization_id, header_id,
  effective_from, values, change_reason, created_by) -> Mapping``
- ``get_active_version(session, version_table, *, header_id, organization_id,
  on_date) -> RowMapping | None``
- ``list_versions(session, version_table, *, header_id, organization_id,
  order="desc") -> Sequence[RowMapping]``
  Default order is newest-first (``lower(validity) DESC``) for history APIs;
  pass ``order="asc"`` for oldest-first.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import ExclusionViolationError
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.effective import effective_on, select_active_version
from app.services.db_errors import integrity_is, raise_integrity_error

__all__ = [
    "get_active_version",
    "get_active_versions_map",
    "insert_version",
    "list_versions",
    "terminate_open_version",
]


def _validity_lower(validity: Any) -> date:
    lower = validity.lower
    if lower is None:
        raise ConflictError("Version validity is missing a lower bound.")
    return lower


async def _fetch_open_version(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
) -> RowMapping | None:
    stmt = (
        sa.select(version_table)
        .where(version_table.c.organization_id == organization_id)
        .where(version_table.c.header_id == header_id)
        .where(sa.func.upper_inf(version_table.c.validity))
    )
    result = await session.execute(stmt)
    return result.mappings().first()


async def _assert_no_historical_conflict(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
    effective_from: date,
    exclude_id: UUID | None,
) -> None:
    """Reject effective_from that overlaps a closed historical range or a future version."""
    validity = version_table.c.validity
    stmt = (
        sa.select(version_table.c.id)
        .where(version_table.c.organization_id == organization_id)
        .where(version_table.c.header_id == header_id)
        .where(
            sa.or_(
                validity.contains(effective_from),
                sa.func.lower(validity) >= effective_from,
            )
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(version_table.c.id != exclude_id)
    result = await session.execute(stmt)
    if result.first() is not None:
        raise ConflictError("the requested effective_from overlaps an existing historical version")


async def insert_version(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
    effective_from: date,
    values: dict[str, Any],
    change_reason: str | None,
    created_by: UUID,
) -> Mapping[str, Any]:
    """Clip any open version and insert a new open-ended version row.

    Returns the inserted row as a mapping (RETURNING), so callers do not need a
    second SELECT.
    """
    open_row = await _fetch_open_version(
        session,
        version_table,
        organization_id=organization_id,
        header_id=header_id,
    )
    open_id: UUID | None = None
    if open_row is not None:
        open_id = open_row["id"]
        old_lower = _validity_lower(open_row["validity"])
        if effective_from <= old_lower:
            raise ConflictError(
                "effective_from must be after the current version's start date "
                f"(effective_from={effective_from.isoformat()}, "
                f"current_start={old_lower.isoformat()})"
            )

    await _assert_no_historical_conflict(
        session,
        version_table,
        organization_id=organization_id,
        header_id=header_id,
        effective_from=effective_from,
        exclude_id=open_id,
    )

    try:
        if open_row is not None:
            old_lower = _validity_lower(open_row["validity"])
            await session.execute(
                sa.update(version_table)
                .where(version_table.c.id == open_row["id"])
                .values(validity=Range(old_lower, effective_from, bounds="[)"))
            )
            await session.flush()

        insert_values: dict[str, Any] = {
            "organization_id": organization_id,
            "header_id": header_id,
            "validity": Range(effective_from, None, bounds="[)"),
            "created_by": created_by,
            "change_reason": change_reason,
            **values,
        }
        result = await session.execute(
            sa.insert(version_table).values(**insert_values).returning(version_table)
        )
        row = result.mappings().one()
        await session.flush()
        return row
    except IntegrityError as exc:
        await session.rollback()
        if integrity_is(exc, ExclusionViolationError):
            raise ConflictError(
                "the requested effective_from overlaps an existing historical version"
            ) from exc
        # Non-exclusion integrity failures (FK, check, etc.) propagate unchanged.
        raise


async def terminate_open_version(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
    end_on: date,
) -> Mapping[str, Any]:
    """Close the open version at ``end_on`` without inserting a successor.

    Used for soft-ending an effective-dated series (e.g. ending a recurring
    instruction). Returns the clipped row. Raises ``ConflictError`` when no
    open version exists and ``ValidationError`` when ``end_on`` does not fall
    after the open version's start.
    """
    open_row = await _fetch_open_version(
        session,
        version_table,
        organization_id=organization_id,
        header_id=header_id,
    )
    if open_row is None:
        raise ConflictError("No open version exists to terminate.")
    old_lower = _validity_lower(open_row["validity"])
    if end_on <= old_lower:
        raise ValidationError("end_on must be after the open version start.")
    try:
        result = await session.execute(
            sa.update(version_table)
            .where(version_table.c.id == open_row["id"])
            .values(validity=Range(old_lower, end_on, bounds="[)"))
            .returning(version_table)
        )
    except IntegrityError as exc:
        await session.rollback()
        raise_integrity_error(exc)
    row = result.mappings().one()
    await session.flush()
    return row


async def get_active_version(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    header_id: UUID,
    organization_id: UUID,
    on_date: date,
) -> RowMapping | None:
    """Return the version active on ``on_date``, or ``None``."""
    stmt = select_active_version(
        version_table,
        header_id=header_id,
        organization_id=organization_id,
        on_date=on_date,
    )
    result = await session.execute(stmt)
    return result.mappings().first()


async def get_active_versions_map(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    header_ids: Sequence[UUID],
    organization_id: UUID,
    on_date: date,
) -> dict[UUID, RowMapping]:
    """Batch variant of :func:`get_active_version`.

    Returns ``{header_id: active version row}`` for every header in
    ``header_ids`` that has a version active on ``on_date``. Headers without
    an active version are absent from the map. One query regardless of the
    number of headers (GiST EXCLUDE guarantees at most one row per header).
    """
    if not header_ids:
        return {}
    stmt = (
        sa.select(version_table)
        .where(version_table.c.organization_id == organization_id)
        .where(version_table.c.header_id.in_(list(header_ids)))
        .where(effective_on(version_table.c.validity, on_date))
    )
    result = await session.execute(stmt)
    return {row["header_id"]: row for row in result.mappings().all()}


async def list_versions(
    session: AsyncSession,
    version_table: sa.Table,
    *,
    header_id: UUID,
    organization_id: UUID,
    order: str = "desc",
) -> Sequence[RowMapping]:
    """List all versions for a header.

    Default ``order="desc"`` is newest-first (``lower(validity) DESC``).
    Pass ``order="asc"`` for oldest-first.
    """
    lower = sa.func.lower(version_table.c.validity)
    if order == "asc":
        order_by = lower.asc()
    elif order == "desc":
        order_by = lower.desc()
    else:
        raise ValueError("order must be 'asc' or 'desc'")

    stmt = (
        sa.select(version_table)
        .where(version_table.c.organization_id == organization_id)
        .where(version_table.c.header_id == header_id)
        .order_by(order_by)
    )
    result = await session.execute(stmt)
    return list(result.mappings().all())
