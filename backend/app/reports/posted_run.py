"""Shared posted-run loading helpers for report family builders.

Every report family builds from the same immutable posted-run inputs: the
posted :class:`~app.models.payroll_runs.PayrollRun`, its pinned run version,
the payroll period, and the organization. These helpers were previously
copy-pasted into each family module; they are extracted here so the gating
and loading semantics can never drift between families.

Money values loaded from posted rows are quantized with :func:`money` (two
decimal places, ADR 0006). Identity resolution via
:func:`resolve_profile_as_of` is safe against posted data because
effective-dated versions are never mutated in place (ADR 0005).
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.effective import select_active_version
from app.models.employees import employee_profile_versions
from app.models.identity import Organization
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.reports.base import ReportContext

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")

DEFAULT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
DEFAULT_FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"


def money(value: Any) -> Decimal:
    """Quantize a posted value to two decimal places (ADR 0006)."""
    return Decimal(str(value)).quantize(TWO_PLACES)


def month_end(year: int, month: int) -> date:
    """Return the last calendar day of ``year``/``month``."""
    return date(year, month, calendar.monthrange(year, month)[1])


def period_label(year: int, month: int) -> str:
    """Return the human-readable period label, e.g. ``"June 2025"``."""
    return date(year, month, 1).strftime("%B %Y")


async def require_posted_run(
    session: AsyncSession,
    ctx: ReportContext,
) -> tuple[PayrollRun, Any, PayrollPeriod, Organization]:
    """Load the posted run, its pinned version, period, and organization.

    Raises :class:`~app.exceptions.NotFoundError` when the run does not exist
    in the organization, and :class:`~app.exceptions.ConflictError` when the
    run is not posted or its version pointer is broken. Reports must only
    ever read posted, immutable data — this is the single gate for that rule.
    """
    run = await session.get(PayrollRun, ctx.posted_run_id)
    if run is None or run.organization_id != ctx.organization_id:
        raise NotFoundError("Payroll run not found.")
    if run.status != "posted":
        raise ConflictError(
            f"Payroll run must be posted to generate reports; found {run.status!r}.",
            details={"run_id": str(run.id), "status": run.status},
        )
    if run.current_version_id is None:
        raise ConflictError("Posted payroll run has no current_version_id.")

    version = (
        (
            await session.execute(
                sa.select(payroll_run_versions).where(
                    payroll_run_versions.c.id == run.current_version_id,
                    payroll_run_versions.c.organization_id == ctx.organization_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise ConflictError("Posted payroll run version not found.")

    period = await session.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != ctx.organization_id:
        raise NotFoundError("Payroll period not found.")

    org = await session.get(Organization, ctx.organization_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    return run, version, period, org


async def load_result_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
    run_version_id: UUID,
) -> list[dict[str, Any]]:
    """Load posted employee results with their result lines, batched.

    Returns ``[{"result": row, "lines": [line, ...]}, ...]`` ordered by
    employee number, with lines ordered by sequence.
    """
    results = (
        (
            await session.execute(
                sa.select(payroll_employee_results)
                .where(
                    payroll_employee_results.c.organization_id == organization_id,
                    payroll_employee_results.c.run_version_id == run_version_id,
                )
                .order_by(payroll_employee_results.c.employee_number)
            )
        )
        .mappings()
        .all()
    )

    if not results:
        return []

    result_ids = [row["id"] for row in results]
    lines = (
        (
            await session.execute(
                sa.select(payroll_result_lines)
                .where(
                    payroll_result_lines.c.organization_id == organization_id,
                    payroll_result_lines.c.employee_result_id.in_(result_ids),
                )
                .order_by(
                    payroll_result_lines.c.employee_result_id,
                    payroll_result_lines.c.sequence,
                )
            )
        )
        .mappings()
        .all()
    )

    lines_by_result: dict[UUID, list[Any]] = {rid: [] for rid in result_ids}
    for line in lines:
        lines_by_result[line["employee_result_id"]].append(line)

    return [{"result": row, "lines": lines_by_result.get(row["id"], [])} for row in results]


async def resolve_profile_as_of(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> dict[str, Any] | None:
    """Resolve the employee profile version effective on ``as_of``.

    Posted runs pin immutable effective-dated version ids (ADR 0005), so
    resolving identity fields as-of period end never observes mutated data.
    """
    return (
        (
            await session.execute(
                select_active_version(
                    employee_profile_versions,
                    header_id=employee_id,
                    organization_id=organization_id,
                    on_date=as_of,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
