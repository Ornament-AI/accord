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
from app.models.base import utcnow
from app.schemas.pay_setup import (
    AccommodationChargeVersionCreate,
    AccommodationCreate,
    AccommodationUpdate,
)
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
        "quarters_address": header.quarters_address,
        "created_at": header.created_at,
        "updated_at": header.updated_at,
        "version_id": version["id"],
        "effective_from": version["effective_from"],
        "effective_to": version["effective_to"],
        "license_fee": version.get("license_fee"),
        "house_rent": version.get("house_rent"),
        "service_charge": version.get("service_charge"),
        "parking_charge": version.get("parking_charge"),
        "additional_parking_charge": version.get("additional_parking_charge"),
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
        quarters_address=(
            body.quarters_address.strip() if body.quarters_address is not None else None
        ),
    )
    db.add(header)
    await db.flush()
    payload = {
        "license_fee": charge.license_fee,
        "house_rent": charge.house_rent,
        "service_charge": charge.service_charge,
        "parking_charge": charge.parking_charge,
        "additional_parking_charge": charge.additional_parking_charge,
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
    headers = (await db.execute(stmt)).scalars().all()
    active_versions = await versioning.get_active_versions_map(
        db,
        accommodation_charge_versions,
        header_ids=[header.id for header in headers],
        organization_id=organization_id,
        on_date=as_of,
    )
    items: list[dict[str, Any]] = []
    for header in headers:
        version_row = active_versions.get(header.id)
        if version_row is None:
            continue
        items.append(_accommodation_response(header, serialize_version_row(version_row)))
    return items


async def update_accommodation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    assignment_id: UUID,
    body: AccommodationUpdate,
) -> dict[str, Any]:
    assignment = await _get_accommodation(
        db,
        organization_id=organization_id,
        assignment_id=assignment_id,
    )
    if "quarters_identifier" in body.model_fields_set:
        assert body.quarters_identifier is not None
        assignment.quarters_identifier = body.quarters_identifier.strip()
    if "quarters_address" in body.model_fields_set:
        assignment.quarters_address = (
            body.quarters_address.strip() if body.quarters_address is not None else None
        )
    assignment.updated_at = utcnow()
    latest = (
        (
            await db.execute(
                sa.select(accommodation_charge_versions)
                .where(accommodation_charge_versions.c.organization_id == organization_id)
                .where(accommodation_charge_versions.c.header_id == assignment_id)
                .order_by(sa.func.lower(accommodation_charge_versions.c.validity).desc())
                .limit(1)
            )
        )
        .mappings()
        .one()
    )
    await db.commit()
    return _accommodation_response(assignment, serialize_version_row(latest))


async def create_accommodation_charge_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    assignment_id: UUID,
    created_by: UUID,
    body: AccommodationChargeVersionCreate,
) -> dict[str, Any]:
    assignment = await _get_accommodation(
        db, organization_id=organization_id, assignment_id=assignment_id
    )
    try:
        body.validate_for_location(assignment.quarters_location)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    payload = {
        "license_fee": body.license_fee,
        "house_rent": body.house_rent,
        "service_charge": body.service_charge,
        "parking_charge": body.parking_charge,
        "additional_parking_charge": body.additional_parking_charge,
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
