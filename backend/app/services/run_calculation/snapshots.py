"""Immutable snapshot builders persisted into the run version.

Posted reports must be reproducible from the run version alone; these
builders capture employee identity, the report profile, and recovery
source metadata as-of calculation time (ADR 0007).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.results import RunResult
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.effective import effective_on
from app.models.employees import (
    Employee,
    employee_bank_account_versions,
    employee_posting_versions,
    employee_profile_versions,
)
from app.models.org_structure import Office, Post
from app.models.reports import ReportConfiguration
from app.services import versioning


async def employee_report_identity_snapshot(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_by_ref: Mapping[str, Employee],
    on_date: date,
) -> dict[str, dict[str, Any]]:
    employee_ids = [employee.id for employee in employee_by_ref.values()]
    profiles = await versioning.get_active_versions_map(
        db,
        employee_profile_versions,
        header_ids=employee_ids,
        organization_id=organization_id,
        on_date=on_date,
    )
    postings = await versioning.get_active_versions_map(
        db,
        employee_posting_versions,
        header_ids=employee_ids,
        organization_id=organization_id,
        on_date=on_date,
    )
    bank_rows = (
        (
            await db.execute(
                sa.select(employee_bank_account_versions).where(
                    employee_bank_account_versions.c.organization_id == organization_id,
                    employee_bank_account_versions.c.header_id.in_(employee_ids),
                    effective_on(employee_bank_account_versions.c.validity, on_date),
                    employee_bank_account_versions.c.is_primary_salary.is_(True),
                )
            )
        )
        .mappings()
        .all()
    )
    banks = {row["header_id"]: row for row in bank_rows}
    post_ids = {posting["post_id"] for posting in postings.values()}
    office_ids = {posting["office_id"] for posting in postings.values()}
    posts = (
        {
            post.id: post
            for post in (await db.execute(sa.select(Post).where(Post.id.in_(post_ids)))).scalars()
        }
        if post_ids
        else {}
    )
    offices = (
        {
            office.id: office
            for office in (
                await db.execute(sa.select(Office).where(Office.id.in_(office_ids)))
            ).scalars()
        }
        if office_ids
        else {}
    )

    snapshot: dict[str, dict[str, Any]] = {}
    for employee in employee_by_ref.values():
        profile = profiles.get(employee.id)
        posting = postings.get(employee.id)
        bank = banks.get(employee.id)
        post = None if posting is None else posts.get(posting["post_id"])
        office = None if posting is None else offices.get(posting["office_id"])
        snapshot[str(employee.id)] = {
            "employee_number": employee.employee_number,
            "name": None if profile is None else profile.get("name"),
            "designation": None if post is None else post.designation,
            "pan": None if profile is None else profile.get("pan"),
            "sevarth_id": None if profile is None else profile.get("sevarth_id"),
            "pran": None if profile is None else profile.get("pran"),
            "gpf_account_number": (None if profile is None else profile.get("gpf_account_number")),
            "gpf_jurisdiction": (None if profile is None else profile.get("gpf_jurisdiction")),
            "pension_account": None if profile is None else profile.get("pension_account"),
            "retirement_regime": (None if profile is None else profile.get("retirement_regime")),
            "office_name": None if office is None else office.name,
            "office_jurisdiction": None if office is None else office.jurisdiction,
            "bank_account_number": None if bank is None else bank.get("account_number"),
            "bank_ifsc": None if bank is None else bank.get("ifsc"),
            "bank_name": None if bank is None else bank.get("bank_name"),
            "bank_branch": None if bank is None else bank.get("branch"),
        }
    return snapshot


async def report_profile_snapshot(db: AsyncSession, *, organization_id: UUID) -> dict[str, Any]:
    row = (
        await db.execute(
            sa.select(ReportConfiguration).where(
                ReportConfiguration.organization_id == organization_id,
                ReportConfiguration.key == "payroll_export_profile",
            )
        )
    ).scalar_one_or_none()
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


async def recovery_sources_snapshot(
    db: AsyncSession,
    *,
    organization_id: UUID,
    result: RunResult,
) -> dict[str, dict[str, Any]]:
    source_ids = {
        UUID(source_id)
        for employee in result.employees
        for line in employee.lines
        for source_id in line.source_version_ids
    }
    if not source_ids:
        return {"advance_installments": {}, "accommodation_charges": {}}

    advance_rows = (
        await db.execute(
            sa.select(
                advance_installment_versions.c.id,
                advance_installment_versions.c.installments_total,
                advance_installment_versions.c.installments_recovered_opening,
                AdvanceAccount.advance_type,
                AdvanceAccount.principal,
                AdvanceAccount.reference,
            )
            .join(AdvanceAccount, AdvanceAccount.id == advance_installment_versions.c.header_id)
            .where(
                advance_installment_versions.c.organization_id == organization_id,
                AdvanceAccount.organization_id == organization_id,
                advance_installment_versions.c.id.in_(source_ids),
            )
        )
    ).mappings()
    accommodation_rows = (
        await db.execute(
            sa.select(
                accommodation_charge_versions.c.id,
                AccommodationAssignment.quarters_location,
                AccommodationAssignment.quarters_identifier,
            )
            .join(
                AccommodationAssignment,
                AccommodationAssignment.id == accommodation_charge_versions.c.header_id,
            )
            .where(
                accommodation_charge_versions.c.organization_id == organization_id,
                AccommodationAssignment.organization_id == organization_id,
                accommodation_charge_versions.c.id.in_(source_ids),
            )
        )
    ).mappings()
    return {
        "advance_installments": {
            str(row["id"]): {
                "advance_type": row["advance_type"],
                "principal": str(row["principal"]),
                "reference": row["reference"],
                "installments_total": row["installments_total"],
                "installments_recovered_opening": row["installments_recovered_opening"],
            }
            for row in advance_rows
        },
        "accommodation_charges": {
            str(row["id"]): {
                "quarters_location": row["quarters_location"],
                "quarters_identifier": row["quarters_identifier"],
            }
            for row in accommodation_rows
        },
    }
