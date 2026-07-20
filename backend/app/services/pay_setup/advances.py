"""Advance accounts and effective-dated installment versions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import CheckViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError, ValidationError
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.effective import select_active_version
from app.schemas.pay_setup import (
    AdvanceCreate,
    AdvanceInstallmentVersionCreate,
)
from app.schemas.money import serialize_money
from app.services import versioning
from app.services.db_errors import raise_integrity_error
from app.services.pay_setup._shared import get_employee, serialize_version_row


def _advance_response(header: AdvanceAccount, version: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": header.id,
        "employee_id": header.employee_id,
        "advance_type": header.advance_type,
        "principal": serialize_money(header.principal),
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


async def create_advance(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    created_by: UUID,
    body: AdvanceCreate,
) -> dict[str, Any]:
    await get_employee(db, organization_id=organization_id, employee_id=employee_id)
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
    version_row = await versioning.insert_version(
        db,
        advance_installment_versions,
        organization_id=organization_id,
        header_id=header.id,
        effective_from=inst.effective_from,
        values=payload,
        change_reason=None,
        created_by=created_by,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if isinstance(exc.orig, CheckViolationError):
            raise ValidationError("Invalid advance_type value.") from exc
        raise_integrity_error(exc)
    return _advance_response(header, serialize_version_row(version_row))


async def list_advances(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    await get_employee(db, organization_id=organization_id, employee_id=employee_id)
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
        items.append(_advance_response(header, serialize_version_row(version_row)))
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
    row = await versioning.insert_version(
        db,
        advance_installment_versions,
        organization_id=organization_id,
        header_id=advance_id,
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
