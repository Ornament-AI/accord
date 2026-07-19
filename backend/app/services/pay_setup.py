"""Pay-setup master data services (Phase 3)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import CheckViolationError, ExclusionViolationError, UniqueViolationError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import versioning
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.effective import select_active_version
from app.models.employees import Employee
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.recurring_instructions import RecurringInstruction, recurring_instruction_versions
from app.models.reports import ReportConfiguration
from app.schemas.pay_setup import (
    AccommodationChargeVersionCreate,
    AccommodationCreate,
    AdvanceCreate,
    AdvanceInstallmentVersionCreate,
    ComponentRateVersionCreate,
    PayComponentCreate,
    PayComponentUpdate,
    RecurringInstructionCreate,
    RecurringInstructionVersionCreate,
    REPORT_CONFIG_KEY_RE,
    _serialize_money,
    _serialize_rate,
)


def _validity_bounds(validity: Any) -> tuple[date, date | None]:
    lower = validity.lower
    upper = validity.upper
    if upper is not None and hasattr(upper, "year"):
        return lower, upper
    return lower, None


def _serialize_version_row(row: Mapping[str, Any]) -> dict[str, Any]:
    effective_from, effective_to = _validity_bounds(row["validity"])
    payload: dict[str, Any] = {
        "id": row["id"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "change_reason": row.get("change_reason"),
    }
    for key, value in row.items():
        if key in {
            "id",
            "organization_id",
            "header_id",
            "validity",
            "created_at",
            "created_by",
            "change_reason",
        }:
            continue
        if isinstance(value, Decimal):
            if key == "rate":
                payload[key] = _serialize_rate(value)
            else:
                payload[key] = _serialize_money(value)
        elif key == "basis" and value is not None and not isinstance(value, list):
            payload[key] = list(value)
        else:
            payload[key] = value
    return payload


def _raise_integrity_error(exc: IntegrityError) -> None:
    orig = exc.orig
    if isinstance(orig, UniqueViolationError):
        raise ConflictError("A conflicting record already exists.") from exc
    if isinstance(orig, ExclusionViolationError):
        raise ConflictError("Version periods overlap.") from exc
    if isinstance(orig, CheckViolationError):
        raise ValidationError("Request violates a database constraint.") from exc
    raise ConflictError("Database constraint violation.") from exc


async def _fetch_open_version(
    db: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
) -> Mapping[str, Any] | None:
    stmt = (
        sa.select(version_table)
        .where(version_table.c.organization_id == organization_id)
        .where(version_table.c.header_id == header_id)
        .where(sa.func.upper_inf(version_table.c.validity))
    )
    result = await db.execute(stmt)
    return result.mappings().first()


async def _insert_version(
    db: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
    effective_from: date,
    created_by: UUID,
    payload: dict[str, Any],
    change_reason: str | None = None,
) -> Mapping[str, Any]:
    """Delegate to the shared clip-and-insert helper (ADR 0005)."""
    return await versioning.insert_version(
        db,
        version_table,
        organization_id=organization_id,
        header_id=header_id,
        effective_from=effective_from,
        values=payload,
        change_reason=change_reason,
        created_by=created_by,
    )


async def _terminate_open_version(
    db: AsyncSession,
    version_table: sa.Table,
    *,
    organization_id: UUID,
    header_id: UUID,
    end_on: date,
) -> Mapping[str, Any]:
    open_row = await _fetch_open_version(
        db,
        version_table,
        organization_id=organization_id,
        header_id=header_id,
    )
    if open_row is None:
        raise ConflictError("No open version exists to terminate.")
    old_lower, _ = _validity_bounds(open_row["validity"])
    if end_on <= old_lower:
        raise ValidationError("end_on must be after the open version start.")
    try:
        result = await db.execute(
            sa.update(version_table)
            .where(version_table.c.id == open_row["id"])
            .values(validity=sa.func.daterange(old_lower, end_on, "[)"))
            .returning(version_table)
        )
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    row = result.mappings().one()
    await db.flush()
    return row


async def _get_pay_component(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
) -> PayComponent:
    component = await db.get(PayComponent, component_id)
    if component is None or component.organization_id != organization_id:
        raise NotFoundError("Pay component not found.")
    return component


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


async def _validate_basis_codes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    basis_codes: list[str],
) -> None:
    if not basis_codes:
        return
    stmt = sa.select(PayComponent.code).where(
        PayComponent.organization_id == organization_id,
        PayComponent.code.in_(basis_codes),
    )
    result = await db.execute(stmt)
    found = set(result.scalars().all())
    unknown = sorted(set(basis_codes) - found)
    if unknown:
        raise ValidationError(f"Unknown pay component codes: {', '.join(unknown)}")


def _pay_component_response(component: PayComponent) -> dict[str, Any]:
    return {
        "id": component.id,
        "code": component.code,
        "name": component.name,
        "classification": component.classification,
        "is_active": component.is_active,
        "display_order": component.display_order,
        "employer_transfer": component.employer_transfer,
        "transfer_of": component.transfer_of,
        "created_at": component.created_at,
        "updated_at": component.updated_at,
    }


async def _validate_employer_transfer_metadata(
    db: AsyncSession,
    *,
    organization_id: UUID,
    code: str,
    classification: str,
    employer_transfer: bool,
    transfer_of: str | None,
) -> None:
    if not employer_transfer:
        if transfer_of is not None:
            raise ValidationError("transfer_of requires employer_transfer=true")
        return
    if classification not in {"ag_deduction", "treasury_deduction", "external_recovery"}:
        raise ValidationError("employer_transfer requires a deduction classification")
    if transfer_of is None:
        return
    if transfer_of == code:
        raise ValidationError("An employer transfer cannot reference itself.")
    target = (
        await db.execute(
            sa.select(PayComponent).where(
                PayComponent.organization_id == organization_id,
                PayComponent.code == transfer_of,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise ValidationError(f"Unknown employer contribution code: {transfer_of}")
    if target.classification != "employer_contribution":
        raise ValidationError(
            f"transfer_of must reference an employer_contribution component: {transfer_of}"
        )


async def create_pay_component(
    db: AsyncSession,
    *,
    organization_id: UUID,
    body: PayComponentCreate,
) -> dict[str, Any]:
    await _validate_employer_transfer_metadata(
        db,
        organization_id=organization_id,
        code=body.code.strip(),
        classification=body.classification.value,
        employer_transfer=body.employer_transfer,
        transfer_of=body.transfer_of,
    )
    component = PayComponent(
        organization_id=organization_id,
        code=body.code.strip(),
        name=body.name.strip(),
        classification=body.classification.value,
        display_order=body.display_order,
        employer_transfer=body.employer_transfer,
        transfer_of=body.transfer_of,
        is_active=True,
    )
    db.add(component)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        orig = exc.orig
        if isinstance(orig, UniqueViolationError):
            raise ConflictError("A pay component with this code already exists.") from exc
        if isinstance(orig, CheckViolationError):
            raise ValidationError("Invalid classification value.") from exc
        _raise_integrity_error(exc)
    return _pay_component_response(component)


async def list_pay_components(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> list[dict[str, Any]]:
    stmt = (
        sa.select(PayComponent)
        .where(PayComponent.organization_id == organization_id)
        .order_by(PayComponent.display_order, PayComponent.code)
    )
    result = await db.execute(stmt)
    return [_pay_component_response(row) for row in result.scalars().all()]


async def update_pay_component(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
    body: PayComponentUpdate,
) -> dict[str, Any]:
    component = await _get_pay_component(
        db, organization_id=organization_id, component_id=component_id
    )
    if body.name is not None:
        component.name = body.name.strip()
    if body.display_order is not None:
        component.display_order = body.display_order
    if body.is_active is not None:
        component.is_active = body.is_active
    employer_transfer = (
        body.employer_transfer
        if "employer_transfer" in body.model_fields_set
        else component.employer_transfer
    )
    transfer_of = (
        body.transfer_of if "transfer_of" in body.model_fields_set else component.transfer_of
    )
    await _validate_employer_transfer_metadata(
        db,
        organization_id=organization_id,
        code=component.code,
        classification=component.classification,
        employer_transfer=employer_transfer,
        transfer_of=transfer_of,
    )
    component.employer_transfer = employer_transfer
    component.transfer_of = transfer_of
    component.updated_at = datetime.now(tz=component.updated_at.tzinfo)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return _pay_component_response(component)


async def create_component_rate_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
    created_by: UUID,
    body: ComponentRateVersionCreate,
) -> dict[str, Any]:
    await _get_pay_component(db, organization_id=organization_id, component_id=component_id)
    if body.basis:
        await _validate_basis_codes(db, organization_id=organization_id, basis_codes=body.basis)
    payload: dict[str, Any] = {
        "calc_kind": body.calc_kind.value,
        "rounding_rule": body.rounding_rule.value,
        "rate": body.rate,
        "amount": body.amount,
        "basis": body.basis,
    }
    row = await _insert_version(
        db,
        component_rate_versions,
        organization_id=organization_id,
        header_id=component_id,
        effective_from=body.effective_from,
        created_by=created_by,
        payload=payload,
        change_reason=body.change_reason,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return _serialize_version_row(row)


async def list_component_rate_versions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
) -> list[dict[str, Any]]:
    await _get_pay_component(db, organization_id=organization_id, component_id=component_id)
    stmt = (
        sa.select(component_rate_versions)
        .where(component_rate_versions.c.organization_id == organization_id)
        .where(component_rate_versions.c.header_id == component_id)
        .order_by(sa.func.lower(component_rate_versions.c.validity))
    )
    result = await db.execute(stmt)
    return [_serialize_version_row(row) for row in result.mappings().all()]


async def create_recurring_instruction(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    created_by: UUID,
    body: RecurringInstructionCreate,
) -> dict[str, Any]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    await _get_pay_component(db, organization_id=organization_id, component_id=body.component_id)
    header = RecurringInstruction(
        organization_id=organization_id,
        employee_id=employee_id,
        component_id=body.component_id,
    )
    db.add(header)
    await db.flush()
    payload = {
        "amount": body.amount,
        "rate": body.rate,
        "reason": body.reason,
    }
    version_row = await _insert_version(
        db,
        recurring_instruction_versions,
        organization_id=organization_id,
        header_id=header.id,
        effective_from=body.effective_from,
        created_by=created_by,
        payload=payload,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    version = _serialize_version_row(version_row)
    return {
        "id": header.id,
        "employee_id": header.employee_id,
        "component_id": header.component_id,
        "created_at": header.created_at,
        "updated_at": header.updated_at,
        "version_id": version["id"],
        "effective_from": version["effective_from"],
        "effective_to": version["effective_to"],
        "amount": version.get("amount"),
        "rate": version.get("rate"),
        "reason": version.get("reason"),
    }


async def _get_recurring_instruction(
    db: AsyncSession,
    *,
    organization_id: UUID,
    instruction_id: UUID,
) -> RecurringInstruction:
    instruction = await db.get(RecurringInstruction, instruction_id)
    if instruction is None or instruction.organization_id != organization_id:
        raise NotFoundError("Recurring instruction not found.")
    return instruction


async def list_recurring_instructions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    stmt = (
        sa.select(RecurringInstruction)
        .where(RecurringInstruction.organization_id == organization_id)
        .where(RecurringInstruction.employee_id == employee_id)
        .order_by(RecurringInstruction.created_at)
    )
    result = await db.execute(stmt)
    items: list[dict[str, Any]] = []
    for header in result.scalars().all():
        active = await db.execute(
            select_active_version(
                recurring_instruction_versions,
                header_id=header.id,
                organization_id=organization_id,
                on_date=as_of,
            )
        )
        version_row = active.mappings().first()
        if version_row is None:
            continue
        version = _serialize_version_row(version_row)
        items.append(
            {
                "id": header.id,
                "employee_id": header.employee_id,
                "component_id": header.component_id,
                "created_at": header.created_at,
                "updated_at": header.updated_at,
                "version_id": version["id"],
                "effective_from": version["effective_from"],
                "effective_to": version["effective_to"],
                "amount": version.get("amount"),
                "rate": version.get("rate"),
                "reason": version.get("reason"),
            }
        )
    return items


async def create_recurring_instruction_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    instruction_id: UUID,
    created_by: UUID,
    body: RecurringInstructionVersionCreate,
) -> dict[str, Any]:
    await _get_recurring_instruction(
        db, organization_id=organization_id, instruction_id=instruction_id
    )
    if body.end_on is not None:
        row = await _terminate_open_version(
            db,
            recurring_instruction_versions,
            organization_id=organization_id,
            header_id=instruction_id,
            end_on=body.end_on,
        )
    else:
        assert body.effective_from is not None
        payload = {
            "amount": body.amount,
            "rate": body.rate,
            "reason": body.reason,
        }
        row = await _insert_version(
            db,
            recurring_instruction_versions,
            organization_id=organization_id,
            header_id=instruction_id,
            effective_from=body.effective_from,
            created_by=created_by,
            payload=payload,
            change_reason=body.change_reason,
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return _serialize_version_row(row)


async def list_recurring_instruction_versions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    instruction_id: UUID,
) -> list[dict[str, Any]]:
    await _get_recurring_instruction(
        db, organization_id=organization_id, instruction_id=instruction_id
    )
    stmt = (
        sa.select(recurring_instruction_versions)
        .where(recurring_instruction_versions.c.organization_id == organization_id)
        .where(recurring_instruction_versions.c.header_id == instruction_id)
        .order_by(sa.func.lower(recurring_instruction_versions.c.validity))
    )
    result = await db.execute(stmt)
    return [_serialize_version_row(row) for row in result.mappings().all()]


def _validate_advance_installment(
    *,
    principal: Decimal,
    installment_amount: Decimal,
    installments_total: int,
    installments_recovered_opening: int,
) -> None:
    if installment_amount > principal:
        raise ValidationError("installment_amount must not exceed principal.")
    if installments_total <= 0:
        raise ValidationError("installments_total must be greater than zero.")
    if installments_recovered_opening < 0:
        raise ValidationError("installments_recovered_opening must be non-negative.")
    if installments_recovered_opening > installments_total:
        raise ValidationError("installments_recovered_opening must not exceed installments_total.")


async def create_advance(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    created_by: UUID,
    body: AdvanceCreate,
) -> dict[str, Any]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    inst = body.installment
    _validate_advance_installment(
        principal=body.principal,
        installment_amount=inst.installment_amount,
        installments_total=inst.installments_total,
        installments_recovered_opening=inst.installments_recovered_opening,
    )
    header = AdvanceAccount(
        organization_id=organization_id,
        employee_id=employee_id,
        advance_type=body.advance_type.value,
        principal=body.principal,
        sanctioned_on=body.sanctioned_on,
        reference=body.reference,
    )
    db.add(header)
    await db.flush()
    payload = {
        "installment_amount": inst.installment_amount,
        "installments_total": inst.installments_total,
        "installments_recovered_opening": inst.installments_recovered_opening,
    }
    version_row = await _insert_version(
        db,
        advance_installment_versions,
        organization_id=organization_id,
        header_id=header.id,
        effective_from=inst.effective_from,
        created_by=created_by,
        payload=payload,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if isinstance(exc.orig, CheckViolationError):
            raise ValidationError("Invalid advance_type value.") from exc
        _raise_integrity_error(exc)
    version = _serialize_version_row(version_row)
    return {
        "id": header.id,
        "employee_id": header.employee_id,
        "advance_type": header.advance_type,
        "principal": _serialize_money(header.principal),
        "sanctioned_on": header.sanctioned_on,
        "reference": header.reference,
        "created_at": header.created_at,
        "updated_at": header.updated_at,
        "version_id": version["id"],
        "effective_from": version["effective_from"],
        "effective_to": version["effective_to"],
        "installment_amount": version.get("installment_amount"),
        "installments_total": version.get("installments_total"),
        "installments_recovered_opening": version.get("installments_recovered_opening"),
    }


async def _get_advance(
    db: AsyncSession,
    *,
    organization_id: UUID,
    advance_id: UUID,
) -> AdvanceAccount:
    advance = await db.get(AdvanceAccount, advance_id)
    if advance is None or advance.organization_id != organization_id:
        raise NotFoundError("Advance account not found.")
    return advance


async def list_advances(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    stmt = (
        sa.select(AdvanceAccount)
        .where(AdvanceAccount.organization_id == organization_id)
        .where(AdvanceAccount.employee_id == employee_id)
        .order_by(AdvanceAccount.created_at)
    )
    result = await db.execute(stmt)
    items: list[dict[str, Any]] = []
    for header in result.scalars().all():
        active = await db.execute(
            select_active_version(
                advance_installment_versions,
                header_id=header.id,
                organization_id=organization_id,
                on_date=as_of,
            )
        )
        version_row = active.mappings().first()
        if version_row is None:
            continue
        version = _serialize_version_row(version_row)
        items.append(
            {
                "id": header.id,
                "employee_id": header.employee_id,
                "advance_type": header.advance_type,
                "principal": _serialize_money(header.principal),
                "sanctioned_on": header.sanctioned_on,
                "reference": header.reference,
                "created_at": header.created_at,
                "updated_at": header.updated_at,
                "version_id": version["id"],
                "effective_from": version["effective_from"],
                "effective_to": version["effective_to"],
                "installment_amount": version.get("installment_amount"),
                "installments_total": version.get("installments_total"),
                "installments_recovered_opening": version.get("installments_recovered_opening"),
            }
        )
    return items


async def create_advance_installment_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    advance_id: UUID,
    created_by: UUID,
    body: AdvanceInstallmentVersionCreate,
) -> dict[str, Any]:
    advance = await _get_advance(db, organization_id=organization_id, advance_id=advance_id)
    _validate_advance_installment(
        principal=advance.principal,
        installment_amount=body.installment_amount,
        installments_total=body.installments_total,
        installments_recovered_opening=body.installments_recovered_opening,
    )
    payload = {
        "installment_amount": body.installment_amount,
        "installments_total": body.installments_total,
        "installments_recovered_opening": body.installments_recovered_opening,
    }
    row = await _insert_version(
        db,
        advance_installment_versions,
        organization_id=organization_id,
        header_id=advance_id,
        effective_from=body.effective_from,
        created_by=created_by,
        payload=payload,
        change_reason=body.change_reason,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return _serialize_version_row(row)


async def create_accommodation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    created_by: UUID,
    body: AccommodationCreate,
) -> dict[str, Any]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    charge = body.charge
    header = AccommodationAssignment(
        organization_id=organization_id,
        employee_id=employee_id,
        quarters_location=body.quarters_location.value,
        quarters_identifier=body.quarters_identifier.strip(),
    )
    db.add(header)
    await db.flush()
    payload = {
        "license_fee": charge.license_fee,
        "informational_hra_foregone": charge.informational_hra_foregone,
    }
    version_row = await _insert_version(
        db,
        accommodation_charge_versions,
        organization_id=organization_id,
        header_id=header.id,
        effective_from=charge.effective_from,
        created_by=created_by,
        payload=payload,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if isinstance(exc.orig, CheckViolationError):
            raise ValidationError("Invalid quarters_location value.") from exc
        _raise_integrity_error(exc)
    version = _serialize_version_row(version_row)
    return {
        "id": header.id,
        "employee_id": header.employee_id,
        "quarters_location": header.quarters_location,
        "quarters_identifier": header.quarters_identifier,
        "created_at": header.created_at,
        "updated_at": header.updated_at,
        "version_id": version["id"],
        "effective_from": version["effective_from"],
        "effective_to": version["effective_to"],
        "license_fee": version.get("license_fee"),
        "informational_hra_foregone": version.get("informational_hra_foregone"),
    }


async def _get_accommodation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    assignment_id: UUID,
) -> AccommodationAssignment:
    assignment = await db.get(AccommodationAssignment, assignment_id)
    if assignment is None or assignment.organization_id != organization_id:
        raise NotFoundError("Accommodation assignment not found.")
    return assignment


async def list_accommodation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    stmt = (
        sa.select(AccommodationAssignment)
        .where(AccommodationAssignment.organization_id == organization_id)
        .where(AccommodationAssignment.employee_id == employee_id)
        .order_by(AccommodationAssignment.created_at)
    )
    result = await db.execute(stmt)
    items: list[dict[str, Any]] = []
    for header in result.scalars().all():
        active = await db.execute(
            select_active_version(
                accommodation_charge_versions,
                header_id=header.id,
                organization_id=organization_id,
                on_date=as_of,
            )
        )
        version_row = active.mappings().first()
        if version_row is None:
            continue
        version = _serialize_version_row(version_row)
        items.append(
            {
                "id": header.id,
                "employee_id": header.employee_id,
                "quarters_location": header.quarters_location,
                "quarters_identifier": header.quarters_identifier,
                "created_at": header.created_at,
                "updated_at": header.updated_at,
                "version_id": version["id"],
                "effective_from": version["effective_from"],
                "effective_to": version["effective_to"],
                "license_fee": version.get("license_fee"),
                "informational_hra_foregone": version.get("informational_hra_foregone"),
            }
        )
    return items


async def create_accommodation_charge_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    assignment_id: UUID,
    created_by: UUID,
    body: AccommodationChargeVersionCreate,
) -> dict[str, Any]:
    await _get_accommodation(db, organization_id=organization_id, assignment_id=assignment_id)
    payload = {
        "license_fee": body.license_fee,
        "informational_hra_foregone": body.informational_hra_foregone,
    }
    row = await _insert_version(
        db,
        accommodation_charge_versions,
        organization_id=organization_id,
        header_id=assignment_id,
        effective_from=body.effective_from,
        created_by=created_by,
        payload=payload,
        change_reason=body.change_reason,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return _serialize_version_row(row)


async def list_report_configurations(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> list[dict[str, Any]]:
    stmt = (
        sa.select(ReportConfiguration)
        .where(ReportConfiguration.organization_id == organization_id)
        .order_by(ReportConfiguration.key)
    )
    result = await db.execute(stmt)
    return [
        {
            "key": row.key,
            "value": row.value,
            "updated_at": row.updated_at,
        }
        for row in result.scalars().all()
    ]


def validate_report_config_key(key: str) -> None:
    if not REPORT_CONFIG_KEY_RE.fullmatch(key):
        raise ValidationError(
            "Key must match ^[a-z][a-z0-9_]{1,63}$ (lowercase, starts with a letter)."
        )


async def upsert_report_configuration(
    db: AsyncSession,
    *,
    organization_id: UUID,
    key: str,
    value: Any,
) -> dict[str, Any]:
    validate_report_config_key(key)
    table = ReportConfiguration.__table__
    stmt = (
        pg_insert(table)
        .values(
            organization_id=organization_id,
            key=key,
            value=value,
        )
        .on_conflict_do_update(
            index_elements=["organization_id", "key"],
            set_={
                "value": value,
                "updated_at": sa.func.now(),
            },
        )
        .returning(table.c.key, table.c.value, table.c.updated_at)
    )
    try:
        result = await db.execute(stmt)
        row = result.one()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        _raise_integrity_error(exc)
    return {
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at,
    }
