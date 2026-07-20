"""Internal helpers shared by the pay-setup aggregate modules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.employees import Employee
from app.models.pay_components import PayComponent
from app.schemas.money import serialize_money, serialize_rate


def validity_bounds(validity: Any) -> tuple[date, date | None]:
    """Return ``(effective_from, effective_to)`` from a Postgres daterange."""
    lower = validity.lower
    upper = validity.upper
    if upper is not None and hasattr(upper, "year"):
        return lower, upper
    return lower, None


def serialize_version_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize an effective-dated version row to its wire shape.

    Money columns become canonical strings; the ``rate`` column uses rate
    serialization; ``basis`` arrays become plain lists.
    """
    effective_from, effective_to = validity_bounds(row["validity"])
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
                payload[key] = serialize_rate(value)
            else:
                payload[key] = serialize_money(value)
        elif key == "basis" and value is not None and not isinstance(value, list):
            payload[key] = list(value)
        else:
            payload[key] = value
    return payload


async def get_employee(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.organization_id != organization_id:
        raise NotFoundError("Employee not found.")
    return employee


async def get_pay_component(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
) -> PayComponent:
    component = await db.get(PayComponent, component_id)
    if component is None or component.organization_id != organization_id:
        raise NotFoundError("Pay component not found.")
    return component
