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

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.schemas.pay_setup import (
    AdvanceCreate,
    AdvanceInstallmentVersionCreate,
)
from app.schemas.money import serialize_money
from app.services import versioning
from app.services.audit_events import entity_snapshot, row_snapshot, write_mutation_event
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
    # Scheduled remaining recovery may not exceed what was lent (T1.6).
    remaining = installment_amount * Decimal(installments_total - installments_recovered_opening)
    if remaining > principal:
        raise ValidationError("scheduled remaining recovery must not exceed principal.")


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
    employee = await get_employee(db, organization_id=organization_id, employee_id=employee_id)
    inst = body.installment
    # M-data-7: two advance accounts of the same type with overlapping
    # installment versions resolve to duplicate recovery component codes at
    # calculate time. Reject at write time.
    overlap_stmt = (
        sa.select(advance_installment_versions.c.id)
        .join(
            AdvanceAccount,
            advance_installment_versions.c.header_id == AdvanceAccount.id,
        )
        .where(AdvanceAccount.organization_id == organization_id)
        .where(AdvanceAccount.employee_id == employee_id)
        .where(AdvanceAccount.advance_type == body.advance_type.value)
        .where(
            sa.or_(
                sa.func.upper_inf(advance_installment_versions.c.validity),
                sa.func.upper(advance_installment_versions.c.validity) > inst.effective_from,
            )
        )
    )
    if (await db.execute(overlap_stmt)).first() is not None:
        raise ConflictError(
            "An active advance account of this type already exists for this "
            "employee; end the existing series first."
        )
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
        await write_mutation_event(
            db,
            organization_id=organization_id,
            actor_user_id=created_by,
            command="advance_account.create",
            entity_type="advance_account",
            entity_id=header.id,
            entity_label=(f"{header.advance_type} advance for {employee.employee_number}"),
            before_state={},
            after_state={
                "account": entity_snapshot(header),
                "installment_version": row_snapshot(version_row),
            },
            summary={
                "employee_id": employee.id,
                "advance_type": header.advance_type,
                "principal": header.principal,
                "version_id": version_row["id"],
                "effective_from": inst.effective_from,
            },
        )
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
    headers = (await db.execute(stmt)).scalars().all()
    active_versions = await versioning.get_active_versions_map(
        db,
        advance_installment_versions,
        header_ids=[header.id for header in headers],
        organization_id=organization_id,
        on_date=as_of,
    )
    items: list[dict[str, Any]] = []
    for header in headers:
        version_row = active_versions.get(header.id)
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
    open_row = await versioning.get_open_version(
        db,
        advance_installment_versions,
        organization_id=organization_id,
        header_id=advance_id,
    )
    terminating = body.end_on is not None
    if terminating:
        # T1.6: terminate mode — close the open installment version so the
        # recovery stops emitting lines from ``end_on``.
        row = await versioning.terminate_open_version(
            db,
            advance_installment_versions,
            organization_id=organization_id,
            header_id=advance_id,
            end_on=body.end_on,
        )
    else:
        if (
            body.effective_from is None
            or body.installment_amount is None
            or body.installments_total is None
            or body.installments_recovered_opening is None
        ):
            raise ValidationError(
                "effective_from and all installment fields are required for a new version."
            )
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
        await write_mutation_event(
            db,
            organization_id=organization_id,
            actor_user_id=created_by,
            command=(
                "advance_account.installment_version.terminate"
                if terminating
                else "advance_account.installment_version.append"
            ),
            entity_type="advance_account",
            entity_id=advance.id,
            entity_label=(f"{advance.advance_type} advance for employee {advance.employee_id}"),
            before_state=row_snapshot(open_row) if open_row is not None else {},
            after_state=row_snapshot(row),
            summary={
                "version_id": row["id"],
                "effective_from": body.effective_from,
                "end_on": body.end_on,
                "change_reason": body.change_reason,
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise_integrity_error(exc)
    return serialize_version_row(row)
