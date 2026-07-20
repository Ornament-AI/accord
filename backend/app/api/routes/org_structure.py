"""Organization-structure master data routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.principal import AuthPrincipal
from app.schemas.org_structure import (
    OfficeCreate,
    OfficeResponse,
    OfficeUpdate,
    PostCreate,
    PostResponse,
    PostUpdate,
)
from app.services.org_structure import (
    create_office,
    create_post,
    list_offices,
    list_posts,
    post_to_response,
    update_office,
    update_post,
)

router = APIRouter(tags=["org-structure"])


@router.post("/offices", response_model=OfficeResponse, status_code=status.HTTP_201_CREATED)
async def create_office_route(
    body: OfficeCreate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> OfficeResponse:
    return await create_office(
        db,
        UUID(ctx.organization_id),
        name=body.name,
        jurisdiction=body.jurisdiction,
    )


@router.get("/offices", response_model=list[OfficeResponse])
async def list_offices_route(
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
) -> list[OfficeResponse]:
    return await list_offices(db, UUID(ctx.organization_id))


@router.patch("/offices/{office_id}", response_model=OfficeResponse)
async def update_office_route(
    office_id: UUID,
    body: OfficeUpdate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> OfficeResponse:
    return await update_office(
        db,
        UUID(ctx.organization_id),
        office_id,
        name=body.name,
        jurisdiction=body.jurisdiction,
    )


@router.post("/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post_route(
    body: PostCreate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> PostResponse:
    post = await create_post(
        db,
        UUID(ctx.organization_id),
        designation=body.designation,
        class_name=body.class_name,
    )
    return post_to_response(post)


@router.get("/posts", response_model=list[PostResponse])
async def list_posts_route(
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
) -> list[PostResponse]:
    posts = await list_posts(db, UUID(ctx.organization_id))
    return [post_to_response(post) for post in posts]


@router.patch("/posts/{post_id}", response_model=PostResponse)
async def update_post_route(
    post_id: UUID,
    body: PostUpdate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> PostResponse:
    post = await update_post(
        db,
        UUID(ctx.organization_id),
        post_id,
        designation=body.designation,
        class_name=body.class_name,
    )
    return post_to_response(post)
