"""Payroll period / run / draft-input services (draft-state mutations only)."""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import CheckViolationError, UniqueViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, StaleRowError, ValidationError
from app.models.base import utcnow
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.platform import AuditEvent
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunInput,
    payroll_report_snapshots,
    payroll_run_versions,
)
from app.models.reports import ReportConfiguration
from app.schemas.payroll_runs import (
    PayrollPeriodCreate,
    PayrollRunCreate,
    PayrollRunReportMetadata,
    PayrollRunRosterUpdate,
    PayrollRunInputUpsert,
    _serialize_money,
    _serialize_rate,
)
from app.services import audit_events, run_results as run_results_service
from app.services import versioning


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
        "status": run.status,
        "lock_version": run.lock_version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


INELIGIBLE_NO_PROFILE = "no_active_profile"


def _roster_response(
    employee: Employee,
    *,
    name: str | None,
    sevarth_id: str | None,
    retirement_regime: str | None,
    basic_pay: Decimal | None,
    row: PayrollRunEmployee | None,
    period_days: int,
    default_selected: bool = False,
    eligible: bool = True,
) -> dict[str, Any]:
    return {
        "employee_id": employee.id,
        "employee_number": employee.employee_number,
        "employee_name": name,
        "sevarth_id": sevarth_id,
        "retirement_regime": retirement_regime,
        "basic_pay": _serialize_optional_money(basic_pay),
        "selected": row is not None or default_selected,
        "eligible": eligible,
        "ineligible_reason": None if eligible else INELIGIBLE_NO_PROFILE,
        "payable_days": _serialize_money(row.payable_days if row else Decimal(period_days)),
        "da_percent": _serialize_optional_rate(row.da_percent if row else None),
        "da_difference": _serialize_optional_money(row.da_difference if row else None),
        "hra_percent": _serialize_optional_rate(row.hra_percent if row else None),
        "transport_amount": _serialize_optional_money(row.transport_amount if row else None),
    }


_ROSTER_FIELD_LABELS = {
    "payable_days": "Paid days",
    "da_percent": "DA %",
    "da_difference": "DA difference",
    "hra_percent": "HRA %",
    "transport_amount": "Transport",
}


def _roster_snapshot_item(item: PayrollRunEmployee | Any) -> dict[str, Any]:
    return {
        "employee_id": item.employee_id,
        "payable_days": item.payable_days,
        "da_percent": item.da_percent,
        "da_difference": item.da_difference,
        "hra_percent": item.hra_percent,
        "transport_amount": item.transport_amount,
    }


def _roster_change_summary(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> tuple[int, list[str]]:
    before_by_employee = {item["employee_id"]: item for item in before}
    after_by_employee = {item["employee_id"]: item for item in after}
    changed_employees = 0
    changed_fields: set[str] = set()
    for employee_id in before_by_employee.keys() | after_by_employee.keys():
        previous = before_by_employee.get(employee_id)
        current = after_by_employee.get(employee_id)
        if previous is None or current is None:
            changed_employees += 1
            changed_fields.add("Employees")
            continue
        employee_changed = False
        for field, label in _ROSTER_FIELD_LABELS.items():
            if previous[field] != current[field]:
                employee_changed = True
                changed_fields.add(label)
        if employee_changed:
            changed_employees += 1
    return changed_employees, sorted(changed_fields)


def _run_detail(run: PayrollRun, period: PayrollPeriod) -> dict[str, Any]:
    return {
        "id": run.id,
        "period_id": run.period_id,
        "period_year": period.period_year,
        "period_month": period.period_month,
        "period_status": period.status,
        "status": run.status,
        "current_version": None,
        "lock_version": run.lock_version,
        "roster_initialized": run.roster_initialized,
        "report_metadata": run.report_metadata,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


async def get_run_report_metadata(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> dict[str, Any]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    return PayrollRunReportMetadata.model_validate(run.report_metadata or {}).model_dump(
        mode="json"
    )


async def update_run_report_metadata(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    body: PayrollRunReportMetadata,
) -> dict[str, Any]:
    run = await _get_run_for_update(db, organization_id=organization_id, run_id=run_id)
    if run.status not in {"draft", "calculated"}:
        raise ConflictError(
            "Payroll run report metadata is immutable after the run is submitted. "
            "Withdraw it before making changes."
        )
    run.report_metadata = body.model_dump(mode="json")
    run.lock_version += 1
    run.updated_at = utcnow()
    await db.commit()
    return body.model_dump(mode="json")


async def get_report_readiness(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> dict[str, Any]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    metadata = PayrollRunReportMetadata.model_validate(run.report_metadata or {})
    profile: dict[str, Any] = {}
    if run.current_version_id is not None:
        version_inputs = (
            await db.execute(
                sa.select(payroll_run_versions.c.inputs_snapshot).where(
                    payroll_run_versions.c.organization_id == organization_id,
                    payroll_run_versions.c.id == run.current_version_id,
                )
            )
        ).scalar_one_or_none()
        if isinstance(version_inputs, dict) and isinstance(
            version_inputs.get("report_profile"), dict
        ):
            profile = version_inputs["report_profile"]
        if run.status in {"posted", "reversed"}:
            posted_snapshot = (
                await db.execute(
                    sa.select(payroll_report_snapshots.c.snapshot).where(
                        payroll_report_snapshots.c.organization_id == organization_id,
                        payroll_report_snapshots.c.run_version_id == run.current_version_id,
                    )
                )
            ).scalar_one_or_none()
            if isinstance(posted_snapshot, dict) and isinstance(
                posted_snapshot.get("report_profile"), dict
            ):
                profile = posted_snapshot["report_profile"]
    if not profile and run.current_version_id is None:
        profile_row = (
            await db.execute(
                sa.select(ReportConfiguration).where(
                    ReportConfiguration.organization_id == organization_id,
                    ReportConfiguration.key == "payroll_export_profile",
                )
            )
        ).scalar_one_or_none()
        profile = (
            profile_row.value
            if profile_row is not None and isinstance(profile_row.value, dict)
            else {}
        )
    issues = report_readiness_issues(metadata=metadata, profile=profile)
    return {"ready": not issues, "issues": issues}


def report_readiness_issues(
    *,
    metadata: PayrollRunReportMetadata,
    profile: dict[str, Any],
) -> list[dict[str, str]]:
    """Return missing fields that would make final report exports incomplete."""
    heads = profile.get("head_of_account") or {}
    issues: list[dict[str, str]] = []
    for field, code, label in (
        (metadata.bill_number, "bill_number_missing", "Bill number"),
        (metadata.bill_date, "bill_date_missing", "Bill date"),
        (
            metadata.demand_number or heads.get("demand_number"),
            "demand_number_missing",
            "Demand number",
        ),
        (metadata.major_head or heads.get("major_head"), "major_head_missing", "Major head"),
        (metadata.sub_head or heads.get("sub_head"), "sub_head_missing", "Sub head"),
        (
            metadata.detailed_head or heads.get("detailed_head"),
            "detailed_head_missing",
            "Detailed head",
        ),
    ):
        if field is None or (isinstance(field, str) and not field.strip()):
            issues.append(
                {
                    "report_type": "treasury_face",
                    "code": code,
                    "message": f"{label} is required for final Treasury Face export.",
                }
            )
    for field, report_type, code, label in (
        (profile.get("ddo_code"), "treasury_face", "ddo_code_missing", "DDO code"),
        (
            (profile.get("bank_advice_recipient") or {}).get("bank_name"),
            "bank_rtgs_advice",
            "advice_bank_missing",
            "Advice recipient bank",
        ),
    ):
        if not field:
            issues.append(
                {
                    "report_type": report_type,
                    "code": code,
                    "message": f"{label} is required for a complete export.",
                }
            )
    signatories = {
        str(item.get("role")): item
        for item in profile.get("signatories", [])
        if isinstance(item, dict)
    }
    for role, label in (
        ("maker", "Maker signatory"),
        ("checker", "Checker signatory"),
        ("approving_officer", "Approving officer signatory"),
    ):
        signatory = signatories.get(role) or {}
        if (
            not str(signatory.get("name") or "").strip()
            or not str(signatory.get("designation") or "").strip()
        ):
            issues.append(
                {
                    "report_type": "approval_note",
                    "code": f"{role}_signatory_missing",
                    "message": f"{label} name and designation are required.",
                }
            )
    return issues


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


async def _get_run_for_update(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> PayrollRun:
    """Load a payroll run with a row lock for draft mutations that race calculate."""
    run = (
        await db.execute(
            sa.select(PayrollRun)
            .where(PayrollRun.id == run_id)
            .where(PayrollRun.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
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
        status="draft",
    )
    db.add(run)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _integrity_is(exc, UniqueViolationError):
            raise ConflictError("A payroll run already exists for this period.") from exc
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
        .where(
            PayrollRun.organization_id == organization_id,
            PayrollRun.original_run_id.is_(None),
        )
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


async def list_run_roster(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> list[dict[str, Any]]:
    run = await _get_run(db, organization_id=organization_id, run_id=run_id)
    period = await _get_period(db, organization_id=organization_id, period_id=run.period_id)
    period_days = calendar.monthrange(period.period_year, period.period_month)[1]
    on_date = date(period.period_year, period.period_month, period_days)

    employees = list(
        (
            await db.execute(
                sa.select(Employee)
                .where(Employee.organization_id == organization_id)
                .order_by(Employee.employee_number)
            )
        )
        .scalars()
        .all()
    )
    roster_rows = list(
        (
            await db.execute(
                sa.select(PayrollRunEmployee)
                .where(PayrollRunEmployee.organization_id == organization_id)
                .where(PayrollRunEmployee.run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    roster_by_employee = {row.employee_id: row for row in roster_rows}

    employee_ids = [employee.id for employee in employees]
    profiles = await versioning.get_active_versions_map(
        db,
        employee_profile_versions,
        header_ids=employee_ids,
        organization_id=organization_id,
        on_date=on_date,
    )
    pays = await versioning.get_active_versions_map(
        db,
        employee_pay_versions,
        header_ids=employee_ids,
        organization_id=organization_id,
        on_date=on_date,
    )

    result: list[dict[str, Any]] = []
    for employee in employees:
        profile = profiles.get(employee.id)
        row = roster_by_employee.get(employee.id)
        if profile is None and row is None:
            # Never selectable and nothing saved to surface — omit entirely.
            continue
        pay = pays.get(employee.id)
        result.append(
            _roster_response(
                employee,
                name=profile.get("name") if profile is not None else None,
                sevarth_id=profile.get("sevarth_id") if profile is not None else None,
                retirement_regime=(
                    profile.get("retirement_regime") if profile is not None else None
                ),
                basic_pay=(
                    Decimal(pay["basic_pay"])
                    if pay is not None and pay.get("basic_pay") is not None
                    else None
                ),
                row=row,
                period_days=period_days,
                default_selected=not run.roster_initialized and run.status != "draft",
                eligible=profile is not None,
            )
        )
    return result


async def replace_run_roster(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    actor_user_id: UUID,
    body: PayrollRunRosterUpdate,
) -> list[dict[str, Any]]:
    run = await _get_run_for_update(db, organization_id=organization_id, run_id=run_id)
    _require_draft(run)
    was_initialized = run.roster_initialized
    period = await _get_period(db, organization_id=organization_id, period_id=run.period_id)
    period_days = calendar.monthrange(period.period_year, period.period_month)[1]
    employee_ids = [item.employee_id for item in body.employees]
    if not employee_ids:
        raise ValidationError("Select at least one employee for this pay run.")
    if len(employee_ids) != len(set(employee_ids)):
        raise ValidationError("Each employee can appear only once in a payroll run.")
    if any(item.payable_days > period_days for item in body.employees):
        raise ValidationError(f"Payable days cannot exceed {period_days} for this period.")

    if employee_ids:
        valid_ids = set(
            (
                await db.execute(
                    sa.select(Employee.id)
                    .where(Employee.organization_id == organization_id)
                    .where(Employee.id.in_(employee_ids))
                )
            )
            .scalars()
            .all()
        )
        if valid_ids != set(employee_ids):
            raise NotFoundError("One or more employees were not found.")

    # Reject saves containing employees with no active profile at month-end:
    # they would be silently dropped from calculation (see run_calculation).
    on_date = date(period.period_year, period.period_month, period_days)
    profiles = await versioning.get_active_versions_map(
        db,
        employee_profile_versions,
        header_ids=employee_ids,
        organization_id=organization_id,
        on_date=on_date,
    )
    ineligible_ids = [eid for eid in employee_ids if eid not in profiles]
    if ineligible_ids:
        numbers = (
            (
                await db.execute(
                    sa.select(Employee.employee_number)
                    .where(Employee.id.in_(ineligible_ids))
                    .order_by(Employee.employee_number)
                )
            )
            .scalars()
            .all()
        )
        raise ValidationError(
            "These employees have no active profile on "
            f"{on_date.isoformat()} and cannot be part of this pay run: "
            f"{', '.join(numbers)}. Remove them from the roster."
        )

    existing_rows = list(
        (
            await db.execute(
                sa.select(PayrollRunEmployee)
                .where(PayrollRunEmployee.organization_id == organization_id)
                .where(PayrollRunEmployee.run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    before = [_roster_snapshot_item(row) for row in existing_rows]
    after = [_roster_snapshot_item(item) for item in body.employees]
    changed_employees, changed_fields = _roster_change_summary(before, after)

    # Semantic no-op: a save that changes nothing must not mint new row ids,
    # bump lock_version, write audit history, or perturb calculation hashes.
    # (Decimal comparison in _roster_change_summary is numeric, so 31 == 31.00.)
    if was_initialized and changed_employees == 0:
        response = await list_run_roster(db, organization_id=organization_id, run_id=run_id)
        await db.commit()
        return response

    # Apply as a diff: update retained rows in place (preserving row UUIDs),
    # insert new selections, delete removals.
    existing_by_employee = {row.employee_id: row for row in existing_rows}
    submitted_ids = set(employee_ids)
    for row in existing_rows:
        if row.employee_id not in submitted_ids:
            await db.delete(row)
    for item in body.employees:
        row = existing_by_employee.get(item.employee_id)
        if row is None:
            db.add(
                PayrollRunEmployee(
                    organization_id=organization_id,
                    run_id=run_id,
                    employee_id=item.employee_id,
                    payable_days=item.payable_days,
                    da_percent=item.da_percent,
                    da_difference=item.da_difference,
                    hra_percent=item.hra_percent,
                    transport_amount=item.transport_amount,
                )
            )
            continue
        if (
            row.payable_days != item.payable_days
            or row.da_percent != item.da_percent
            or row.da_difference != item.da_difference
            or row.hra_percent != item.hra_percent
            or row.transport_amount != item.transport_amount
        ):
            row.payable_days = item.payable_days
            row.da_percent = item.da_percent
            row.da_difference = item.da_difference
            row.hra_percent = item.hra_percent
            row.transport_amount = item.transport_amount
            row.updated_at = utcnow()
    run.roster_initialized = True
    run.lock_version += 1
    if changed_employees > 0:
        await audit_events.write_mutation_event(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            command="payroll_run.roster.update",
            entity_type="payroll_run_roster",
            entity_id=run_id,
            entity_label=f"Payroll roster {period.period_year}-{period.period_month:02d}",
            before_state={"employees": before},
            after_state={"employees": after},
            summary={
                "action": "Created roster" if not was_initialized else "Updated roster",
                "changed_employees": changed_employees,
                "selected_employees": len(after),
                "changed_fields": changed_fields,
            },
        )
    await db.flush()
    response = await list_run_roster(db, organization_id=organization_id, run_id=run_id)
    await db.commit()
    return response


async def list_run_roster_history(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> list[dict[str, Any]]:
    await _get_run(db, organization_id=organization_id, run_id=run_id)
    rows = list(
        (
            await db.execute(
                sa.select(AuditEvent)
                .where(AuditEvent.organization_id == organization_id)
                .where(AuditEvent.entity_type == "payroll_run_roster")
                .where(AuditEvent.entity_id == run_id)
                .where(AuditEvent.command == "payroll_run.roster.update")
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "action": str(row.summary.get("action") or "Updated roster"),
            "changed_employees": int(row.summary.get("changed_employees") or 0),
            "selected_employees": int(row.summary.get("selected_employees") or 0),
            "changed_fields": list(row.summary.get("changed_fields") or []),
            "actor_name": str((row.actor_snapshot or {}).get("name") or "Unknown user"),
            "created_at": row.created_at,
        }
        for row in rows
    ]


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
        # Build the response BEFORE commit: the commit ends the transaction and
        # clears SET LOCAL tenant GUCs, so a post-commit refresh SELECT runs
        # blind under forced RLS and raises InvalidRequestError.
        response = _input_response(row)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return response


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
