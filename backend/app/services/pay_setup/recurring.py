"""Recurring instruction headers and effective-dated instruction versions."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.recurring_instructions import RecurringInstruction, recurring_instruction_versions
from app.schemas.pay_setup import RecurringInstructionCreate, RecurringInstructionVersionCreate
from app.services import versioning
from app.services.db_errors import raise_integrity_error
from app.services.pay_setup._shared import get_employee, get_pay_component, serialize_version_row


def _instruction_response(header: RecurringInstruction, version: dict[str, Any]) -> dict[str, Any]:
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


async def create_recurring_instruction(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    created_by: UUID,
    body: RecurringInstructionCreate,
) -> dict[str, Any]:
    await get_employee(db, organization_id=organization_id, employee_id=employee_id)
    await get_pay_component(db, organization_id=organization_id, component_id=body.component_id)
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
    version_row = await versioning.insert_version(
        db,
        recurring_instruction_versions,
        organization_id=organization_id,
        header_id=header.id,
        effective_from=body.effective_from,
        values=payload,
        change_reason=None,
        created_by=created_by,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise_integrity_error(exc)
    return _instruction_response(header, serialize_version_row(version_row))


async def list_recurring_instructions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    await get_employee(db, organization_id=organization_id, employee_id=employee_id)
    stmt = (
        sa.select(RecurringInstruction)
        .where(RecurringInstruction.organization_id == organization_id)
        .where(RecurringInstruction.employee_id == employee_id)
        .order_by(RecurringInstruction.created_at)
    )
    headers = (await db.execute(stmt)).scalars().all()
    active_versions = await versioning.get_active_versions_map(
        db,
        recurring_instruction_versions,
        header_ids=[header.id for header in headers],
        organization_id=organization_id,
        on_date=as_of,
    )
    items: list[dict[str, Any]] = []
    for header in headers:
        version_row = active_versions.get(header.id)
        if version_row is None:
            continue
        items.append(_instruction_response(header, serialize_version_row(version_row)))
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
        row = await versioning.terminate_open_version(
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
        row = await versioning.insert_version(
            db,
            recurring_instruction_versions,
            organization_id=organization_id,
            header_id=instruction_id,
            effective_from=body.effective_from,
            values=payload,
            change_reason=body.change_reason,
            created_by=created_by,
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise_integrity_error(exc)
    return serialize_version_row(row)


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
    return [serialize_version_row(row) for row in result.mappings().all()]
