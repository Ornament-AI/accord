"""Read immutable presentation snapshots for posted-run reports."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.payroll_runs import payroll_report_snapshots


async def load_report_snapshot(
    session: AsyncSession,
    *,
    organization_id: UUID,
    run_version_id: UUID,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                sa.select(payroll_report_snapshots).where(
                    payroll_report_snapshots.c.organization_id == organization_id,
                    payroll_report_snapshots.c.run_version_id == run_version_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConflictError(
            "Posted payroll run has no immutable report snapshot. "
            "Create an explicit audited backfill before regenerating reports.",
            details={"error_code": "report_snapshot_missing"},
        )
    snapshot = row["snapshot"]
    if not isinstance(snapshot, dict):
        raise ConflictError("Immutable report snapshot is malformed.")
    return snapshot
