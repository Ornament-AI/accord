"""Accommodation assignments and effective-dated charge versions."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import CheckViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError, ValidationError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.effective import select_active_version
from app.schemas.pay_setup import AccommodationChargeVersionCreate, AccommodationCreate
from app.services import versioning
from app.services.db_errors import raise_integrity_error
from app.services.pay_setup._shared import get_employee, serialize_version_row


def _accommodation_response(
    header: AccommodationAssignment, version: dict[str, Any]
) -> dict[str, Any]:
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


async def create_accommodation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    created_by: UUID,
    body: AccommodationCreate,
) -> dict[str, Any]:
    await get_employee(db, organization_id=organization_id, employee_id=employee_id)
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
    version_row = await versioning.insert_version(
        db,
        accommodation_charge_versions,
        organization_id=organization_id,
        header_id=header.id,
        effective_from=charge.effective_from,
        values=payload,
        change_reason=None,
        created_by=created_by,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if isinstance(exc.orig, CheckViolationError):
            raise ValidationError("Invalid quarters_location value.") from exc
        raise_integrity_error(exc)
    return _accommodation_response(header, serialize_version_row(version_row))


async def list_accommodation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    await get_employee(db, organization_id=organization_id, employee_id=employee_id)
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
        items.append(_accommodation_response(header, serialize_version_row(version_row)))
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
    row = await versioning.insert_version(
        db,
        accommodation_charge_versions,
        organization_id=organization_id,
        header_id=assignment_id,
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
