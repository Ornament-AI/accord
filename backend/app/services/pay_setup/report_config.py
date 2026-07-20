"""Report configuration key/value store and the typed payroll export profile."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ValidationError
from app.models.reports import ReportConfiguration
from app.schemas.pay_setup import REPORT_CONFIG_KEY_RE, PayrollExportProfile
from app.services.db_errors import raise_integrity_error


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


async def _upsert_report_configuration(
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
        raise_integrity_error(exc)
    return {
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at,
    }


async def upsert_report_configuration(
    db: AsyncSession,
    *,
    organization_id: UUID,
    key: str,
    value: Any,
) -> dict[str, Any]:
    if key == "payroll_export_profile":
        raise ValidationError(
            "payroll_export_profile is reserved; use the typed /api/report-profile endpoint."
        )
    return await _upsert_report_configuration(
        db,
        organization_id=organization_id,
        key=key,
        value=value,
    )


async def get_payroll_export_profile(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> dict[str, Any]:
    row = (
        await db.execute(
            sa.select(ReportConfiguration).where(
                ReportConfiguration.organization_id == organization_id,
                ReportConfiguration.key == "payroll_export_profile",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"value": PayrollExportProfile().model_dump(mode="json"), "updated_at": None}
    value = PayrollExportProfile.model_validate(row.value)
    return {"value": value.model_dump(mode="json"), "updated_at": row.updated_at}


async def upsert_payroll_export_profile(
    db: AsyncSession,
    *,
    organization_id: UUID,
    profile: PayrollExportProfile,
) -> dict[str, Any]:
    row = await _upsert_report_configuration(
        db,
        organization_id=organization_id,
        key="payroll_export_profile",
        value=profile.model_dump(mode="json"),
    )
    return {"value": row["value"], "updated_at": row["updated_at"]}
