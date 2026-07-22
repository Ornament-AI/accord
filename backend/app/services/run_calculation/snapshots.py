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
    post_ids = {
        post_id
        for posting in postings.values()
        for post_id in (posting["post_id"], posting.get("pay_bill_post_id"))
        if post_id is not None
    }
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
        pay_bill_post = (
            None
            if posting is None
            else posts.get(posting.get("pay_bill_post_id") or posting["post_id"])
        )
        office = None if posting is None else offices.get(posting["office_id"])
        snapshot[str(employee.id)] = {
            "employee_number": employee.employee_number,
            "name": None if profile is None else profile.get("name"),
            "designation": None if post is None else post.designation,
            "post": (
                None
                if post is None
                else {
                    "id": str(post.id),
                    "designation": post.designation,
                    "class_name": post.class_,
                    "sanctioned_strength": post.sanctioned_strength,
                    "vacant_count": post.vacant_count,
                    "pay_scale": post.pay_scale,
                    "display_order": post.display_order,
                }
            ),
            "pay_bill_post": (
                None
                if pay_bill_post is None
                else {
                    "id": str(pay_bill_post.id),
                    "heading": pay_bill_post.pay_bill_heading or pay_bill_post.designation,
                    "designation": pay_bill_post.designation,
                    "sanctioned_strength": pay_bill_post.sanctioned_strength,
                    "vacant_count": pay_bill_post.vacant_count,
                    "pay_scale": pay_bill_post.pay_scale,
                    "display_order": pay_bill_post.display_order,
                }
            ),
            "pan": None if profile is None else profile.get("pan"),
            "sevarth_id": None if profile is None else profile.get("sevarth_id"),
            "pran": None if profile is None else profile.get("pran"),
            "gpf_account_number": (None if profile is None else profile.get("gpf_account_number")),
            "gpf_jurisdiction": (None if profile is None else profile.get("gpf_jurisdiction")),
            "epf_number": None if profile is None else profile.get("epf_number"),
            "pension_account": None if profile is None else profile.get("pension_account"),
            "payroll_export_remark": (
                None if profile is None else profile.get("payroll_export_remark")
            ),
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
                advance_installment_versions.c.installment_amount,
                AdvanceAccount.advance_type,
                AdvanceAccount.principal,
                AdvanceAccount.sanctioned_on,
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
                AccommodationAssignment.id.label("assignment_id"),
                AccommodationAssignment.quarters_identifier,
                AccommodationAssignment.quarters_address,
                accommodation_charge_versions.c.license_fee,
                accommodation_charge_versions.c.house_rent,
                accommodation_charge_versions.c.service_charge,
                accommodation_charge_versions.c.parking_charge,
                accommodation_charge_versions.c.additional_parking_charge,
                accommodation_charge_versions.c.informational_hra_foregone,
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
                "sanctioned_on": row["sanctioned_on"].isoformat(),
                "reference": row["reference"],
                "installment_amount": str(row["installment_amount"]),
                "installments_total": row["installments_total"],
                "installments_recovered_opening": row["installments_recovered_opening"],
            }
            for row in advance_rows
        },
        "accommodation_charges": {
            str(row["id"]): {
                "assignment_id": str(row["assignment_id"]),
                "quarters_location": row["quarters_location"],
                "quarters_identifier": row["quarters_identifier"],
                "quarters_address": row["quarters_address"],
                "license_fee": str(row["license_fee"]),
                "house_rent": None if row["house_rent"] is None else str(row["house_rent"]),
                "service_charge": (
                    None if row["service_charge"] is None else str(row["service_charge"])
                ),
                "parking_charge": (
                    None if row["parking_charge"] is None else str(row["parking_charge"])
                ),
                "additional_parking_charge": (
                    None
                    if row["additional_parking_charge"] is None
                    else str(row["additional_parking_charge"])
                ),
                "informational_hra_foregone": (
                    None
                    if row["informational_hra_foregone"] is None
                    else str(row["informational_hra_foregone"])
                ),
            }
            for row in accommodation_rows
        },
    }
