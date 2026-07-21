"""Pay component catalog and component rate versions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import CheckViolationError, UniqueViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.pay_components import PayComponent, component_rate_versions
from app.schemas.pay_setup import (
    ComponentRateVersionCreate,
    PayComponentCreate,
    PayComponentUpdate,
)
from app.services import versioning
from app.services.db_errors import raise_integrity_error
from app.services.pay_setup._shared import get_pay_component, serialize_version_row


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
        "is_standard": component.is_standard,
        "schedule_kind": component.schedule_kind,
        "schedule_title": component.schedule_title,
        "schedule_account_head": component.schedule_account_head,
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
        schedule_kind=None if body.schedule_kind is None else body.schedule_kind.value,
        schedule_title=body.schedule_title,
        schedule_account_head=body.schedule_account_head,
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
        raise_integrity_error(exc)
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
    component = await get_pay_component(
        db, organization_id=organization_id, component_id=component_id
    )
    if body.name is not None:
        component.name = body.name.strip()
    if body.display_order is not None:
        component.display_order = body.display_order
    if body.is_active is not None:
        if component.is_standard and body.is_active is False:
            raise ConflictError("Standard pay components cannot be deactivated.")
        component.is_active = body.is_active
    if component.is_standard:
        if (
            "employer_transfer" in body.model_fields_set
            and body.employer_transfer != component.employer_transfer
        ) or ("transfer_of" in body.model_fields_set and body.transfer_of != component.transfer_of):
            raise ConflictError(
                "Standard pay-component transfer rules are application-owned and cannot be changed."
            )
    if "schedule_kind" in body.model_fields_set:
        component.schedule_kind = None if body.schedule_kind is None else body.schedule_kind.value
    if "schedule_title" in body.model_fields_set:
        component.schedule_title = body.schedule_title
    if "schedule_account_head" in body.model_fields_set:
        component.schedule_account_head = body.schedule_account_head
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
    component.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise_integrity_error(exc)
    return _pay_component_response(component)


async def create_component_rate_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
    created_by: UUID,
    body: ComponentRateVersionCreate,
) -> dict[str, Any]:
    await get_pay_component(db, organization_id=organization_id, component_id=component_id)
    if body.basis:
        await _validate_basis_codes(db, organization_id=organization_id, basis_codes=body.basis)
    payload: dict[str, Any] = {
        "calc_kind": body.calc_kind.value,
        "rounding_rule": body.rounding_rule.value,
        "rate": body.rate,
        "amount": body.amount,
        "basis": body.basis,
    }
    row = await versioning.insert_version(
        db,
        component_rate_versions,
        organization_id=organization_id,
        header_id=component_id,
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


async def list_component_rate_versions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
) -> list[dict[str, Any]]:
    await get_pay_component(db, organization_id=organization_id, component_id=component_id)
    stmt = (
        sa.select(component_rate_versions)
        .where(component_rate_versions.c.organization_id == organization_id)
        .where(component_rate_versions.c.header_id == component_id)
        .order_by(sa.func.lower(component_rate_versions.c.validity))
    )
    result = await db.execute(stmt)
    return [serialize_version_row(row) for row in result.mappings().all()]
