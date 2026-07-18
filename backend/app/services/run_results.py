"""Read-side service for calculated payroll run results."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.money import Money
from app.exceptions import ConflictError, NotFoundError
from app.models.payroll_runs import (
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)


def _money_str(value: Decimal) -> str:
    return Money.from_decimal(Decimal(value)).to_canonical_str()


def serialize_version(row: sa.RowMapping | dict[str, Any]) -> dict[str, Any]:
    """Serialize a ``payroll_run_versions`` row into the CurrentVersion shape."""
    totals = row["totals"] or {}
    return {
        "id": row["id"],
        "version_number": int(row["version_number"]),
        "content_hash": str(row["content_hash"]),
        "engine_version": str(row["engine_version"]),
        "calculated_at": row["calculated_at"],
        "totals": {str(k): str(v) for k, v in totals.items()},
    }


def _employee_summary(row: sa.RowMapping) -> dict[str, Any]:
    return {
        "employee_id": row["employee_id"],
        "employee_number": row["employee_number"],
        "earnings_total": _money_str(row["earnings_total"]),
        "employer_contribution_total": _money_str(row["employer_contribution_total"]),
        "gross_total": _money_str(row["gross_total"]),
        "deductions_total": _money_str(row["deductions_total"]),
        "net_payable": _money_str(row["net_payable"]),
    }


async def _get_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> PayrollRun:
    run = await db.get(PayrollRun, run_id)
    if run is None or run.organization_id != organization_id:
        raise NotFoundError("Payroll run not found.")
    return run


async def _load_version_by_id(
    db: AsyncSession,
    *,
    organization_id: UUID,
    version_id: UUID,
) -> sa.RowMapping:
    stmt = sa.select(payroll_run_versions).where(
        payroll_run_versions.c.id == version_id,
        payroll_run_versions.c.organization_id == organization_id,
    )
    row = (await db.execute(stmt)).mappings().one_or_none()
    if row is None:
        raise ConflictError("Payroll run has no calculated version.")
    return row


async def _resolve_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run: PayrollRun,
    version_number: int | None,
) -> sa.RowMapping:
    """Resolve the version row for a results read.

    Error conventions
    -----------------
    * Missing run (caller already 404'd via ``_get_run``).
    * No calculated version at all, or requested ``version_number`` not found
      for this run → **409 Conflict** (documented choice: treat both as
      "no usable calculated version" rather than 404 for a missing number).
    """
    if version_number is None:
        if run.current_version_id is None:
            raise ConflictError("Payroll run has no calculated version.")
        return await _load_version_by_id(
            db,
            organization_id=organization_id,
            version_id=run.current_version_id,
        )

    stmt = sa.select(payroll_run_versions).where(
        payroll_run_versions.c.organization_id == organization_id,
        payroll_run_versions.c.run_id == run.id,
        payroll_run_versions.c.version_number == version_number,
    )
    row = (await db.execute(stmt)).mappings().one_or_none()
    if row is None:
        raise ConflictError(
            f"Payroll run has no calculated version with version_number={version_number}."
        )
    return row


async def get_current_version_for_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run: PayrollRun,
) -> dict[str, Any] | None:
    """Return CurrentVersion payload for a run, or None if uncalculated."""
    if run.current_version_id is None:
        return None
    stmt = sa.select(payroll_run_versions).where(
        payroll_run_versions.c.id == run.current_version_id,
        payroll_run_versions.c.organization_id == organization_id,
    )
    row = (await db.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None
    return serialize_version(row)


async def get_run_results(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    version_number: int | None = None,
) -> dict[str, Any]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    version = await _resolve_version(
        db,
        organization_id=organization_id,
        run=run,
        version_number=version_number,
    )
    version_payload = serialize_version(version)

    emp_stmt = (
        sa.select(payroll_employee_results)
        .where(
            payroll_employee_results.c.organization_id == organization_id,
            payroll_employee_results.c.run_version_id == version["id"],
        )
        .order_by(payroll_employee_results.c.employee_number)
    )
    employees = [_employee_summary(row) for row in (await db.execute(emp_stmt)).mappings().all()]

    return {
        "version": version_payload,
        "totals": version_payload["totals"],
        "employees": employees,
    }


async def get_employee_result(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    employee_id: UUID,
    version_number: int | None = None,
) -> dict[str, Any]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    version = await _resolve_version(
        db,
        organization_id=organization_id,
        run=run,
        version_number=version_number,
    )

    emp_stmt = sa.select(payroll_employee_results).where(
        payroll_employee_results.c.organization_id == organization_id,
        payroll_employee_results.c.run_version_id == version["id"],
        payroll_employee_results.c.employee_id == employee_id,
    )
    emp = (await db.execute(emp_stmt)).mappings().one_or_none()
    if emp is None:
        raise NotFoundError("Employee result not found for this run version.")

    lines_stmt = (
        sa.select(payroll_result_lines)
        .where(
            payroll_result_lines.c.organization_id == organization_id,
            payroll_result_lines.c.employee_result_id == emp["id"],
        )
        .order_by(payroll_result_lines.c.sequence)
    )
    lines = [
        {
            "component_code": row["component_code"],
            "classification": row["classification"],
            "calc_kind": row["calc_kind"],
            "amount": _money_str(row["amount"]),
            "trace": row["trace"],
        }
        for row in (await db.execute(lines_stmt)).mappings().all()
    ]

    summary = _employee_summary(emp)
    summary["lines"] = lines
    return summary
