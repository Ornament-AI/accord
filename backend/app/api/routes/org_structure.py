"""Organization-structure master data routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.principal import AuthPrincipal
from app.schemas.org_structure import (
    EmployeeGroupCreate,
    EmployeeGroupResponse,
    EmployeeGroupUpdate,
    OfficeCreate,
    OfficeResponse,
    OfficeUpdate,
    PayrollUnitCreate,
    PayrollUnitResponse,
    PayrollUnitUpdate,
    PostCreate,
    PostResponse,
    PostUpdate,
)
from app.services.org_structure import (
    create_employee_group,
    create_office,
    create_payroll_unit,
    create_post,
    list_employee_groups,
    list_offices,
    list_payroll_units,
    list_posts,
    post_to_response,
    update_employee_group,
    update_office,
    update_payroll_unit,
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
        code=body.code,
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
        code=body.code,
        jurisdiction=body.jurisdiction,
    )


@router.post(
    "/payroll-units",
    response_model=PayrollUnitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payroll_unit_route(
    body: PayrollUnitCreate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> PayrollUnitResponse:
    return await create_payroll_unit(
        db,
        UUID(ctx.organization_id),
        name=body.name,
        code=body.code,
    )


@router.get("/payroll-units", response_model=list[PayrollUnitResponse])
async def list_payroll_units_route(
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
) -> list[PayrollUnitResponse]:
    return await list_payroll_units(db, UUID(ctx.organization_id))


@router.patch("/payroll-units/{payroll_unit_id}", response_model=PayrollUnitResponse)
async def update_payroll_unit_route(
    payroll_unit_id: UUID,
    body: PayrollUnitUpdate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> PayrollUnitResponse:
    return await update_payroll_unit(
        db,
        UUID(ctx.organization_id),
        payroll_unit_id,
        name=body.name,
        code=body.code,
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


@router.post(
    "/employee-groups",
    response_model=EmployeeGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_group_route(
    body: EmployeeGroupCreate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> EmployeeGroupResponse:
    return await create_employee_group(
        db,
        UUID(ctx.organization_id),
        name=body.name,
        code=body.code,
    )


@router.get("/employee-groups", response_model=list[EmployeeGroupResponse])
async def list_employee_groups_route(
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
) -> list[EmployeeGroupResponse]:
    return await list_employee_groups(db, UUID(ctx.organization_id))


@router.patch("/employee-groups/{employee_group_id}", response_model=EmployeeGroupResponse)
async def update_employee_group_route(
    employee_group_id: UUID,
    body: EmployeeGroupUpdate,
    ctx: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> EmployeeGroupResponse:
    return await update_employee_group(
        db,
        UUID(ctx.organization_id),
        employee_group_id,
        name=body.name,
        code=body.code,
    )
