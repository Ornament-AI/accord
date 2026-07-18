"""Canonical effective-dated version resolution helpers (ADR-0005).

Every version table in Phase 3 uses a ``validity`` ``daterange`` column with
half-open ``[from, to)`` semantics. The single primitive for "is this version
active on date D?" is ``validity @> :on_date`` — exposed here as
``effective_on`` so service-layer code never invents per-table date logic.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.sql import ColumnElement, Select


def effective_on(column: Any, on_date: date | sa.BindParameter[Any]) -> ColumnElement[bool]:
    """Return a boolean SQL expression equivalent to ``column @> on_date``.

    Parameters
    ----------
    column:
        A SQLAlchemy column element typed as Postgres ``daterange`` (typically
        ``VersionTable.c.validity``).
    on_date:
        The calendar date to test for containment, or a bound SQL parameter.

    Returns
    -------
    ColumnElement[bool]
        Boolean expression usable in ``select(...).where(...)``.
    """
    return column.contains(on_date)


def select_active_version(
    version_table: sa.Table,
    *,
    header_id: UUID | sa.BindParameter[Any],
    organization_id: UUID | sa.BindParameter[Any],
    on_date: date | sa.BindParameter[Any],
    header_column: str = "header_id",
    organization_column: str = "organization_id",
    validity_column: str = "validity",
) -> Select[Any]:
    """Build a ``SELECT`` for the single active version of a header as of ``on_date``.

    Parameters
    ----------
    version_table:
        SQLAlchemy Core ``Table`` for a ``*_versions`` table attached to
        ``SQLModel.metadata``.
    header_id:
        Stable header row id to resolve.
    organization_id:
        Tenant scope (must match the header's organization).
    on_date:
        Calendar date for ADR-0005 resolution (``validity @> on_date``).
    header_column:
        Name of the FK column pointing at the header table (default
        ``header_id``).
    organization_column:
        Name of the tenant column (default ``organization_id``).
    validity_column:
        Name of the ``daterange`` column (default ``validity``).

    Returns
    -------
    Select
        A select of all columns from ``version_table`` filtered to the active
        row. Callers should treat zero or multiple rows as a data-integrity
        error (GiST EXCLUDE should prevent multiples).
    """
    validity = version_table.c[validity_column]
    return (
        sa.select(version_table)
        .where(version_table.c[organization_column] == organization_id)
        .where(version_table.c[header_column] == header_id)
        .where(effective_on(validity, on_date))
    )
