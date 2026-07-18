"""Employee header + effective-dated version services (Phase 3)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from asyncpg.exceptions import ExclusionViolationError, UniqueViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.employees import (
    Employee,
    employee_bank_account_versions,
    employee_pay_versions,
    employee_posting_versions,
    employee_profile_versions,
)
from app.models.org_structure import EmployeeGroup, Office, PayrollUnit, Post
from app.schemas.employees import (
    BankInput,
    CreateEmployeeRequest,
    EmployeeDetail,
    EmployeeListPage,
    EmployeeSummary,
    PayInput,
    PostingInput,
    ProfileInput,
    VersionKind,
    bank_from_row,
    pay_from_row,
    posting_from_row,
    profile_from_row,
)
from app.schemas.pagination import page_count, page_offset
from app.services.versioning import get_active_version, insert_version, list_versions

VERSION_TABLES: dict[VersionKind, sa.Table] = {
    "profile": employee_profile_versions,
    "posting": employee_posting_versions,
    "pay": employee_pay_versions,
    "bank": employee_bank_account_versions,
}


def _integrity_is(exc: BaseException, *types: type[BaseException]) -> bool:
    """Walk SQLAlchemy/asyncpg exception wrappers for a concrete PG error type."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, types):
            return True
        current = current.__cause__ or getattr(current, "orig", None)
    return False


def _profile_values(profile: ProfileInput) -> dict[str, Any]:
    return {
        "name": profile.name.strip(),
        "sevarth_id": profile.sevarth_id.strip(),
        "pan": profile.pan,
        "date_of_birth": profile.date_of_birth,
        "date_of_joining": profile.date_of_joining,
        "retirement_regime": profile.retirement_regime.value,
        "gpf_jurisdiction": (
            profile.gpf_jurisdiction.value if profile.gpf_jurisdiction is not None else None
        ),
        "pran": profile.pran,
        "gpf_account_number": profile.gpf_account_number,
        "epf_number": profile.epf_number,
        "pension_account": profile.pension_account,
    }


def _posting_values(posting: PostingInput) -> dict[str, Any]:
    return {
        "office_id": posting.office_id,
        "payroll_unit_id": posting.payroll_unit_id,
        "post_id": posting.post_id,
        "employee_group_id": posting.employee_group_id,
    }


def _pay_values(pay: PayInput) -> dict[str, Any]:
    return {
        "pay_matrix_level": pay.pay_matrix_level.strip(),
        "basic_pay": pay.basic_pay,
    }


def _bank_values(bank: BankInput) -> dict[str, Any]:
    return {
        "account_number": bank.account_number.strip(),
        "ifsc": bank.ifsc.strip(),
        "bank_name": bank.bank_name.strip(),
        "branch": bank.branch.strip(),
        "is_primary_salary": bank.is_primary_salary,
    }


async def _get_employee(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.organization_id != organization_id:
        raise NotFoundError("Employee not found.")
    return employee


async def _require_org_entity(
    db: AsyncSession,
    model: type[Any],
    *,
    organization_id: UUID,
    entity_id: UUID,
    label: str,
) -> None:
    row = await db.get(model, entity_id)
    if row is None or getattr(row, "organization_id", None) != organization_id:
        raise NotFoundError(f"{label} not found.")


async def _validate_posting_fks(
    db: AsyncSession,
    *,
    organization_id: UUID,
    posting: PostingInput,
) -> None:
    await _require_org_entity(
        db, Office, organization_id=organization_id, entity_id=posting.office_id, label="Office"
    )
    await _require_org_entity(
        db,
        PayrollUnit,
        organization_id=organization_id,
        entity_id=posting.payroll_unit_id,
        label="Payroll unit",
    )
    await _require_org_entity(
        db, Post, organization_id=organization_id, entity_id=posting.post_id, label="Post"
    )
    if posting.employee_group_id is not None:
        await _require_org_entity(
            db,
            EmployeeGroup,
            organization_id=organization_id,
            entity_id=posting.employee_group_id,
            label="Employee group",
        )


def _parse_kind(kind: str) -> VersionKind:
    if kind not in VERSION_TABLES:
        raise ValidationError("kind must be one of: profile, posting, pay, bank")
    return kind  # type: ignore[return-value]


async def create_employee(
    db: AsyncSession,
    *,
    organization_id: UUID,
    created_by: UUID,
    body: CreateEmployeeRequest,
) -> EmployeeDetail:
    """Create employee header + initial profile (and optional posting/pay/bank) versions."""
    if body.posting is not None:
        await _validate_posting_fks(db, organization_id=organization_id, posting=body.posting)

    employee = Employee(
        organization_id=organization_id,
        employee_number=body.employee_number.strip(),
    )
    db.add(employee)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _integrity_is(exc, UniqueViolationError):
            raise ConflictError(
                "An employee with this employee_number already exists in this organization."
            ) from exc
        raise ConflictError("Could not create employee.") from exc

    try:
        await insert_version(
            db,
            employee_profile_versions,
            organization_id=organization_id,
            header_id=employee.id,
            effective_from=body.effective_from,
            values=_profile_values(body.profile),
            change_reason=body.change_reason,
            created_by=created_by,
        )
        if body.posting is not None:
            await insert_version(
                db,
                employee_posting_versions,
                organization_id=organization_id,
                header_id=employee.id,
                effective_from=body.effective_from,
                values=_posting_values(body.posting),
                change_reason=body.change_reason,
                created_by=created_by,
            )
        if body.pay is not None:
            await insert_version(
                db,
                employee_pay_versions,
                organization_id=organization_id,
                header_id=employee.id,
                effective_from=body.effective_from,
                values=_pay_values(body.pay),
                change_reason=body.change_reason,
                created_by=created_by,
            )
        if body.bank is not None:
            await insert_version(
                db,
                employee_bank_account_versions,
                organization_id=organization_id,
                header_id=employee.id,
                effective_from=body.effective_from,
                values=_bank_values(body.bank),
                change_reason=body.change_reason,
                created_by=created_by,
            )
        detail = await get_employee_detail(
            db,
            organization_id=organization_id,
            employee_id=employee.id,
            as_of=body.effective_from,
            reveal=False,
        )
        await db.commit()
        return detail
    except (ConflictError, NotFoundError, ValidationError):
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        if _integrity_is(exc, ExclusionViolationError):
            raise ConflictError("Version periods overlap.") from exc
        raise ConflictError("Could not create employee versions.") from exc


async def list_employees(
    db: AsyncSession,
    *,
    organization_id: UUID,
    as_of: date,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    reveal: bool = False,
) -> EmployeeListPage:
    """List employees with active profile as-of, optional ILIKE search, pagination."""
    del reveal  # list items expose name/sevarth only; no sensitive fields
    profile = employee_profile_versions
    offset = page_offset(page=page, page_size=page_size)

    base_from = (
        sa.select(
            Employee.id.label("id"),
            Employee.employee_number.label("employee_number"),
            profile.c.name.label("name"),
            profile.c.sevarth_id.label("sevarth_id"),
            profile.c.retirement_regime.label("retirement_regime"),
        )
        .select_from(Employee)
        .outerjoin(
            profile,
            sa.and_(
                profile.c.header_id == Employee.id,
                profile.c.organization_id == organization_id,
                profile.c.validity.contains(as_of),
            ),
        )
        .where(Employee.organization_id == organization_id)
    )

    if search:
        pattern = f"%{search}%"
        base_from = base_from.where(
            sa.or_(
                Employee.employee_number.ilike(pattern),
                profile.c.name.ilike(pattern),
                profile.c.sevarth_id.ilike(pattern),
            )
        )

    count_stmt = sa.select(sa.func.count()).select_from(base_from.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    page_stmt = base_from.order_by(Employee.employee_number.asc()).limit(page_size).offset(offset)
    rows = (await db.execute(page_stmt)).mappings().all()
    items = [
        EmployeeSummary(
            id=row["id"],
            employee_number=row["employee_number"],
            name=row["name"],
            sevarth_id=row["sevarth_id"],
            retirement_regime=row["retirement_regime"],
        )
        for row in rows
    ]
    return EmployeeListPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=page_count(total=total, page_size=page_size),
    )


async def get_employee_detail(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
    reveal: bool = False,
) -> EmployeeDetail:
    employee = await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    profile_row = await get_active_version(
        db,
        employee_profile_versions,
        header_id=employee.id,
        organization_id=organization_id,
        on_date=as_of,
    )
    posting_row = await get_active_version(
        db,
        employee_posting_versions,
        header_id=employee.id,
        organization_id=organization_id,
        on_date=as_of,
    )
    pay_row = await get_active_version(
        db,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=organization_id,
        on_date=as_of,
    )
    bank_row = await get_active_version(
        db,
        employee_bank_account_versions,
        header_id=employee.id,
        organization_id=organization_id,
        on_date=as_of,
    )
    return EmployeeDetail(
        id=employee.id,
        employee_number=employee.employee_number,
        organization_id=employee.organization_id,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
        as_of=as_of,
        profile=profile_from_row(profile_row, reveal=reveal) if profile_row else None,
        posting=posting_from_row(posting_row) if posting_row else None,
        pay=pay_from_row(pay_row) if pay_row else None,
        bank=bank_from_row(bank_row, reveal=reveal) if bank_row else None,
    )


async def get_employee_versions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    kind: str,
    reveal: bool = False,
) -> list[Any]:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    parsed = _parse_kind(kind)
    table = VERSION_TABLES[parsed]
    rows = await list_versions(
        db,
        table,
        header_id=employee_id,
        organization_id=organization_id,
        order="desc",
    )
    if parsed == "profile":
        return [profile_from_row(row, reveal=reveal) for row in rows]
    if parsed == "posting":
        return [posting_from_row(row) for row in rows]
    if parsed == "pay":
        return [pay_from_row(row) for row in rows]
    return [bank_from_row(row, reveal=reveal) for row in rows]


async def create_employee_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    kind: str,
    created_by: UUID,
    effective_from: date,
    change_reason: str | None,
    profile: ProfileInput | None = None,
    posting: PostingInput | None = None,
    pay: PayInput | None = None,
    bank: BankInput | None = None,
) -> Any:
    await _get_employee(db, organization_id=organization_id, employee_id=employee_id)
    parsed = _parse_kind(kind)
    table = VERSION_TABLES[parsed]

    if parsed == "profile":
        if profile is None:
            raise ValidationError("profile fields are required for kind=profile")
        values = _profile_values(profile)
    elif parsed == "posting":
        if posting is None:
            raise ValidationError("posting fields are required for kind=posting")
        await _validate_posting_fks(db, organization_id=organization_id, posting=posting)
        values = _posting_values(posting)
    elif parsed == "pay":
        if pay is None:
            raise ValidationError("pay fields are required for kind=pay")
        values = _pay_values(pay)
    else:
        if bank is None:
            raise ValidationError("bank fields are required for kind=bank")
        values = _bank_values(bank)

    try:
        row = await insert_version(
            db,
            table,
            organization_id=organization_id,
            header_id=employee_id,
            effective_from=effective_from,
            values=values,
            change_reason=change_reason,
            created_by=created_by,
        )
        await db.commit()
    except ConflictError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        if _integrity_is(exc, ExclusionViolationError):
            if parsed == "bank":
                raise ConflictError(
                    "Primary salary bank account versions overlap for this employee."
                ) from exc
            raise ConflictError("Version periods overlap.") from exc
        raise ConflictError("Could not create version.") from exc

    if parsed == "profile":
        return profile_from_row(row, reveal=False)
    if parsed == "posting":
        return posting_from_row(row)
    if parsed == "pay":
        return pay_from_row(row)
    return bank_from_row(row, reveal=False)
