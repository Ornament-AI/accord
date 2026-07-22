"""Organization-structure master data services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.org_structure import Office, Post
from app.schemas.org_structure import PostResponse, PostUpdate


def post_to_response(post: Post) -> PostResponse:
    """Map ORM ``class_`` to API ``class_name``."""
    return PostResponse(
        id=post.id,
        designation=post.designation,
        pay_bill_heading=post.pay_bill_heading,
        class_name=post.class_,
        sanctioned_strength=post.sanctioned_strength,
        vacant_count=post.vacant_count,
        pay_scale=post.pay_scale,
        display_order=post.display_order,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


async def create_office(
    db: AsyncSession,
    organization_id: UUID,
    *,
    name: str,
    jurisdiction: str,
) -> Office:
    office = Office(
        organization_id=organization_id,
        name=name,
        jurisdiction=jurisdiction,
    )
    db.add(office)
    await db.flush()
    await db.commit()
    return office


async def list_offices(db: AsyncSession, organization_id: UUID) -> list[Office]:
    result = await db.execute(
        select(Office).where(Office.organization_id == organization_id).order_by(Office.name)
    )
    return list(result.scalars().all())


async def update_office(
    db: AsyncSession,
    organization_id: UUID,
    office_id: UUID,
    *,
    name: str | None = None,
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

    if name is not None:
        office.name = name
    if jurisdiction is not None:
        office.jurisdiction = jurisdiction

    await db.flush()
    await db.commit()
    return office


async def create_post(
    db: AsyncSession,
    organization_id: UUID,
    *,
    designation: str,
    class_name: str,
    pay_bill_heading: str | None = None,
    sanctioned_strength: int | None = None,
    vacant_count: int | None = None,
    pay_scale: str | None = None,
    display_order: int | None = None,
) -> Post:
    post = Post(
        organization_id=organization_id,
        designation=designation,
        pay_bill_heading=pay_bill_heading,
        class_=class_name,
        sanctioned_strength=sanctioned_strength,
        vacant_count=vacant_count,
        pay_scale=pay_scale,
        display_order=display_order,
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
        select(Post)
        .where(Post.organization_id == organization_id)
        .order_by(Post.display_order.asc().nulls_last(), Post.designation)
    )
    return list(result.scalars().all())


async def update_post(
    db: AsyncSession,
    organization_id: UUID,
    post_id: UUID,
    *,
    body: PostUpdate,
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

    if body.designation is not None and body.designation != post.designation:
        raise ConflictError("Post designation cannot be changed.")

    if body.class_name is not None:
        post.class_ = body.class_name
    if "pay_bill_heading" in body.model_fields_set:
        post.pay_bill_heading = body.pay_bill_heading

    sanctioned_strength = (
        body.sanctioned_strength
        if "sanctioned_strength" in body.model_fields_set
        else post.sanctioned_strength
    )
    vacant_count = (
        body.vacant_count if "vacant_count" in body.model_fields_set else post.vacant_count
    )
    if vacant_count is not None and sanctioned_strength is None:
        raise ValidationError("sanctioned_strength is required when vacant_count is provided")
    if (
        vacant_count is not None
        and sanctioned_strength is not None
        and vacant_count > sanctioned_strength
    ):
        raise ValidationError("vacant_count must not exceed sanctioned_strength")

    if "sanctioned_strength" in body.model_fields_set:
        post.sanctioned_strength = body.sanctioned_strength
    if "vacant_count" in body.model_fields_set:
        post.vacant_count = body.vacant_count
    if "pay_scale" in body.model_fields_set:
        post.pay_scale = body.pay_scale
    if "display_order" in body.model_fields_set:
        post.display_order = body.display_order

    await db.flush()
    await db.commit()
    return post
