"""Organization-structure master data services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.org_structure import EmployeeGroup, Office, PayrollUnit, Post
from app.schemas.org_structure import PostResponse


def post_to_response(post: Post) -> PostResponse:
    """Map ORM ``class_`` to API ``class_name``."""
    return PostResponse(
        id=post.id,
        designation=post.designation,
        class_name=post.class_,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


async def create_office(
    db: AsyncSession,
    organization_id: UUID,
    *,
    name: str,
    code: str,
    jurisdiction: str,
) -> Office:
    office = Office(
        organization_id=organization_id,
        name=name,
        code=code,
        jurisdiction=jurisdiction,
    )
    db.add(office)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "An office with this code already exists for this organization."
        ) from exc
    return office


async def list_offices(db: AsyncSession, organization_id: UUID) -> list[Office]:
    result = await db.execute(
        select(Office).where(Office.organization_id == organization_id).order_by(Office.code)
    )
    return list(result.scalars().all())


async def update_office(
    db: AsyncSession,
    organization_id: UUID,
    office_id: UUID,
    *,
    name: str | None = None,
    code: str | None = None,
    jurisdiction: str | None = None,
) -> Office:
    result = await db.execute(
        select(Office).where(
            Office.id == office_id,
            Office.organization_id == organization_id,
        )
    )
    office = result.scalar_one_or_none()
    if office is None:
        raise NotFoundError("Office not found.")

    if code is not None and code != office.code:
        raise ConflictError("Office code cannot be changed.")

    if name is not None:
        office.name = name
    if jurisdiction is not None:
        office.jurisdiction = jurisdiction

    await db.flush()
    await db.commit()
    return office


async def create_payroll_unit(
    db: AsyncSession,
    organization_id: UUID,
    *,
    name: str,
    code: str,
) -> PayrollUnit:
    payroll_unit = PayrollUnit(
        organization_id=organization_id,
        name=name,
        code=code,
    )
    db.add(payroll_unit)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "A payroll unit with this code already exists for this organization."
        ) from exc
    return payroll_unit


async def list_payroll_units(
    db: AsyncSession,
    organization_id: UUID,
) -> list[PayrollUnit]:
    result = await db.execute(
        select(PayrollUnit)
        .where(PayrollUnit.organization_id == organization_id)
        .order_by(PayrollUnit.code)
    )
    return list(result.scalars().all())


async def update_payroll_unit(
    db: AsyncSession,
    organization_id: UUID,
    payroll_unit_id: UUID,
    *,
    name: str | None = None,
    code: str | None = None,
) -> PayrollUnit:
    result = await db.execute(
        select(PayrollUnit).where(
            PayrollUnit.id == payroll_unit_id,
            PayrollUnit.organization_id == organization_id,
        )
    )
    payroll_unit = result.scalar_one_or_none()
    if payroll_unit is None:
        raise NotFoundError("Payroll unit not found.")

    if code is not None and code != payroll_unit.code:
        raise ConflictError("Payroll unit code cannot be changed.")

    if name is not None:
        payroll_unit.name = name

    await db.flush()
    await db.commit()
    return payroll_unit


async def create_post(
    db: AsyncSession,
    organization_id: UUID,
    *,
    designation: str,
    class_name: str,
) -> Post:
    post = Post(
        organization_id=organization_id,
        designation=designation,
        class_=class_name,
    )
    db.add(post)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "A post with this designation already exists for this organization."
        ) from exc
    return post


async def list_posts(db: AsyncSession, organization_id: UUID) -> list[Post]:
    result = await db.execute(
        select(Post).where(Post.organization_id == organization_id).order_by(Post.designation)
    )
    return list(result.scalars().all())


async def update_post(
    db: AsyncSession,
    organization_id: UUID,
    post_id: UUID,
    *,
    designation: str | None = None,
    class_name: str | None = None,
) -> Post:
    result = await db.execute(
        select(Post).where(
            Post.id == post_id,
            Post.organization_id == organization_id,
        )
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise NotFoundError("Post not found.")

    if designation is not None and designation != post.designation:
        raise ConflictError("Post designation cannot be changed.")

    if class_name is not None:
        post.class_ = class_name

    await db.flush()
    await db.commit()
    return post


async def create_employee_group(
    db: AsyncSession,
    organization_id: UUID,
    *,
    name: str,
    code: str,
) -> EmployeeGroup:
    employee_group = EmployeeGroup(
        organization_id=organization_id,
        name=name,
        code=code,
    )
    db.add(employee_group)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "An employee group with this code already exists for this organization."
        ) from exc
    return employee_group


async def list_employee_groups(
    db: AsyncSession,
    organization_id: UUID,
) -> list[EmployeeGroup]:
    result = await db.execute(
        select(EmployeeGroup)
        .where(EmployeeGroup.organization_id == organization_id)
        .order_by(EmployeeGroup.code)
    )
    return list(result.scalars().all())


async def update_employee_group(
    db: AsyncSession,
    organization_id: UUID,
    employee_group_id: UUID,
    *,
    name: str | None = None,
    code: str | None = None,
) -> EmployeeGroup:
    result = await db.execute(
        select(EmployeeGroup).where(
            EmployeeGroup.id == employee_group_id,
            EmployeeGroup.organization_id == organization_id,
        )
    )
    employee_group = result.scalar_one_or_none()
    if employee_group is None:
        raise NotFoundError("Employee group not found.")

    if code is not None and code != employee_group.code:
        raise ConflictError("Employee group code cannot be changed.")

    if name is not None:
        employee_group.name = name

    await db.flush()
    await db.commit()
    return employee_group
