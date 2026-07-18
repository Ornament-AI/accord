"""Payroll period / run / draft-input services (draft-state mutations only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import CheckViolationError, UniqueViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, StaleRowError, ValidationError
from app.models.employees import Employee
from app.models.payroll_runs import PayrollPeriod, PayrollRun, PayrollRunInput
from app.schemas.payroll_runs import (
    PayrollPeriodCreate,
    PayrollRunCreate,
    PayrollRunInputUpsert,
    _serialize_money,
    _serialize_rate,
)
from app.services import run_results as run_results_service


def _serialize_optional_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _serialize_money(value)


def _serialize_optional_rate(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _serialize_rate(value)


def _integrity_is(exc: BaseException, *types: type[BaseException]) -> bool:
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


def _raise_integrity_error(exc: IntegrityError) -> None:
    if _integrity_is(exc, UniqueViolationError):
        raise ConflictError("A conflicting record already exists.") from exc
    if _integrity_is(exc, CheckViolationError):
        raise ValidationError("Request violates a database constraint.") from exc
    raise ConflictError("Database constraint violation.") from exc


def _period_response(period: PayrollPeriod) -> dict[str, Any]:
    return {
        "id": period.id,
        "period_year": period.period_year,
        "period_month": period.period_month,
        "status": period.status,
        "created_at": period.created_at,
        "updated_at": period.updated_at,
    }


def _run_list_item(run: PayrollRun, period: PayrollPeriod) -> dict[str, Any]:
    return {
        "id": run.id,
        "period_id": run.period_id,
        "period_year": period.period_year,
        "period_month": period.period_month,
        "run_type": run.run_type,
        "status": run.status,
        "lock_version": run.lock_version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _run_detail(run: PayrollRun, period: PayrollPeriod) -> dict[str, Any]:
    return {
        "id": run.id,
        "period_id": run.period_id,
        "period_year": period.period_year,
        "period_month": period.period_month,
        "period_status": period.status,
        "run_type": run.run_type,
        "status": run.status,
        "current_version": None,
        "lock_version": run.lock_version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _input_response(row: PayrollRunInput) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "employee_id": row.employee_id,
        "component_code": row.component_code,
        "input_kind": row.input_kind,
        "amount": _serialize_optional_money(row.amount),
        "rate": _serialize_optional_rate(row.rate),
        "reason": row.reason,
        "service_period_start": row.service_period_start,
        "service_period_end": row.service_period_end,
        "version": row.version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _get_period(
    db: AsyncSession,
    *,
    organization_id: UUID,
    period_id: UUID,
) -> PayrollPeriod:
    period = await db.get(PayrollPeriod, period_id)
    if period is None or period.organization_id != organization_id:
        raise NotFoundError("Payroll period not found.")
    return period


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


async def _get_employee(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.organization_id != organization_id:
        raise NotFoundError("Employee not found.")
    return employee


def _require_draft(run: PayrollRun) -> None:
    if run.status != "draft":
        raise ConflictError("Payroll run inputs can only be modified while the run is in draft.")


async def create_period(
    db: AsyncSession,
    *,
    organization_id: UUID,
    body: PayrollPeriodCreate,
) -> dict[str, Any]:
    period = PayrollPeriod(
        organization_id=organization_id,
        period_year=body.period_year,
        period_month=body.period_month,
        status="open",
    )
    db.add(period)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _integrity_is(exc, UniqueViolationError):
            raise ConflictError(
                "A payroll period for this organization, year, and month already exists."
            ) from exc
        _raise_integrity_error(exc)
    return _period_response(period)


async def list_periods(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> list[dict[str, Any]]:
    stmt = (
        sa.select(PayrollPeriod)
        .where(PayrollPeriod.organization_id == organization_id)
        .order_by(PayrollPeriod.period_year.desc(), PayrollPeriod.period_month.desc())
    )
    result = await db.execute(stmt)
    return [_period_response(row) for row in result.scalars().all()]


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    body: PayrollRunCreate,
) -> dict[str, Any]:
    period = await _get_period(db, organization_id=organization_id, period_id=body.period_id)
    run = PayrollRun(
        organization_id=organization_id,
        period_id=period.id,
        run_type=body.run_type.value,
        status="draft",
    )
    db.add(run)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _integrity_is(exc, UniqueViolationError):
            raise ConflictError("A regular payroll run already exists for this period.") from exc
        _raise_integrity_error(exc)
    return _run_list_item(run, period)


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    period_id: UUID | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        sa.select(PayrollRun, PayrollPeriod)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollRun.period_id)
        .where(PayrollRun.organization_id == organization_id)
        .order_by(PayrollRun.created_at.desc())
    )
    if period_id is not None:
        stmt = stmt.where(PayrollRun.period_id == period_id)
    if status is not None:
        stmt = stmt.where(PayrollRun.status == status)
    result = await db.execute(stmt)
    return [_run_list_item(run, period) for run, period in result.all()]


async def get_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> dict[str, Any]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    period = await _get_period(db, organization_id=organization_id, period_id=run.period_id)
    detail = _run_detail(run, period)
    detail["current_version"] = await run_results_service.get_current_version_for_run(
        db,
        organization_id=organization_id,
        run=run,
    )
    return detail


async def upsert_run_input(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    employee_id: UUID,
    component_code: str,
    actor_user_id: UUID,
    body: PayrollRunInputUpsert,
) -> dict[str, Any]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    _require_draft(run)
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)

    code = component_code.strip()
    if not code:
        raise ValidationError("component_code must not be empty.")

    stmt = (
        sa.select(PayrollRunInput)
        .where(PayrollRunInput.organization_id == organization_id)
        .where(PayrollRunInput.run_id == run_id)
        .where(PayrollRunInput.employee_id == employee_id)
        .where(PayrollRunInput.component_code == code)
        .where(PayrollRunInput.input_kind == body.input_kind.value)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is None:
        row = PayrollRunInput(
            organization_id=organization_id,
            run_id=run_id,
            employee_id=employee_id,
            component_code=code,
            input_kind=body.input_kind.value,
            amount=body.amount,
            rate=body.rate,
            reason=body.reason,
            service_period_start=body.service_period_start,
            service_period_end=body.service_period_end,
            version=0,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        db.add(row)
    else:
        if body.expected_version is not None and body.expected_version != existing.version:
            raise StaleRowError()
        existing.amount = body.amount
        existing.rate = body.rate
        existing.reason = body.reason
        existing.service_period_start = body.service_period_start
        existing.service_period_end = body.service_period_end
        existing.version = existing.version + 1
        existing.updated_by = actor_user_id
        existing.updated_at = datetime.now(tz=existing.updated_at.tzinfo)
        row = existing

    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    await db.refresh(row)
    return _input_response(row)


async def list_run_inputs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> list[dict[str, Any]]:
    await _get_run(db, organization_id=organization_id, run_id=run_id)
    stmt = (
        sa.select(PayrollRunInput)
        .where(PayrollRunInput.organization_id == organization_id)
        .where(PayrollRunInput.run_id == run_id)
        .order_by(PayrollRunInput.created_at, PayrollRunInput.component_code)
    )
    result = await db.execute(stmt)
    return [_input_response(row) for row in result.scalars().all()]


async def delete_run_input(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    input_id: UUID,
) -> None:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    _require_draft(run)
    row = await db.get(PayrollRunInput, input_id)
    if row is None or row.organization_id != organization_id or row.run_id != run_id:
        raise NotFoundError("Payroll run input not found.")
    await db.delete(row)
    await db.flush()
    await db.commit()
