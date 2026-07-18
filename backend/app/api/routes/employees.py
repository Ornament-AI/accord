"""Employee master-data routes (Phase 3).

Register with: ``app.include_router(employees.router, prefix="/api")``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.errors import CapabilityDeniedError
from app.auth.principal import AuthPrincipal
from app.exceptions import ValidationError
from app.schemas.employees import (
    CreateBankVersionRequest,
    CreateEmployeeRequest,
    CreatePayVersionRequest,
    CreatePostingVersionRequest,
    CreateProfileVersionRequest,
    EmployeeDetail,
    EmployeeListPage,
)
from app.services import employees as employees_service
from app.timezone import current_ist_date

router = APIRouter(prefix="/employees", tags=["employees"])


def _org_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.organization_id)


def _user_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.user_id)


def _require_reveal(
    principal: AuthPrincipal,
    *,
    reveal: bool,
) -> None:
    if reveal and "reveal_sensitive_fields" not in principal.capabilities:
        raise CapabilityDeniedError("reveal_sensitive_fields")


@router.post("", response_model=EmployeeDetail, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=EmployeeDetail, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: CreateEmployeeRequest,
    tenant: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
) -> EmployeeDetail:
    return await employees_service.create_employee(
        db,
        organization_id=_org_id(tenant),
        created_by=_user_id(tenant),
        body=body,
    )


@router.get("", response_model=EmployeeListPage)
@router.get("/", response_model=EmployeeListPage)
async def list_employees(
    tenant: TenantCtx,
    db: Session,
    principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
    as_of: date | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    reveal: bool = False,
) -> EmployeeListPage:
    _require_reveal(principal, reveal=reveal)
    return await employees_service.list_employees(
        db,
        organization_id=_org_id(tenant),
        as_of=as_of or current_ist_date(),
        search=search,
        page=page,
        page_size=size,
        reveal=reveal,
    )


@router.get("/{employee_id}", response_model=EmployeeDetail)
async def get_employee(
    employee_id: UUID,
    tenant: TenantCtx,
    db: Session,
    principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
    as_of: date | None = None,
    reveal: bool = False,
) -> EmployeeDetail:
    _require_reveal(principal, reveal=reveal)
    return await employees_service.get_employee_detail(
        db,
        organization_id=_org_id(tenant),
        employee_id=employee_id,
        as_of=as_of or current_ist_date(),
        reveal=reveal,
    )


@router.get("/{employee_id}/versions/{kind}")
async def list_employee_versions(
    employee_id: UUID,
    kind: str,
    tenant: TenantCtx,
    db: Session,
    principal: Annotated[AuthPrincipal, Depends(require_capability("view_master_data"))],
    reveal: bool = False,
) -> list[Any]:
    _require_reveal(principal, reveal=reveal)
    return await employees_service.get_employee_versions(
        db,
        organization_id=_org_id(tenant),
        employee_id=employee_id,
        kind=kind,
        reveal=reveal,
    )


@router.post(
    "/{employee_id}/versions/{kind}",
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_version(
    employee_id: UUID,
    kind: str,
    tenant: TenantCtx,
    db: Session,
    _principal: Annotated[AuthPrincipal, Depends(require_capability("manage_master_data"))],
    body: dict[str, Any],
) -> Any:
    """Append a new version for ``kind`` ∈ profile|posting|pay|bank."""
    organization_id = _org_id(tenant)
    created_by = _user_id(tenant)

    def _validate(model_cls: type[Any], payload: dict[str, Any]) -> Any:
        try:
            return model_cls.model_validate(payload)
        except PydanticValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

    if kind == "profile":
        parsed = _validate(CreateProfileVersionRequest, body)
        return await employees_service.create_employee_version(
            db,
            organization_id=organization_id,
            employee_id=employee_id,
            kind=kind,
            created_by=created_by,
            effective_from=parsed.effective_from,
            change_reason=parsed.change_reason,
            profile=parsed,
        )
    if kind == "posting":
        parsed_posting = _validate(CreatePostingVersionRequest, body)
        return await employees_service.create_employee_version(
            db,
            organization_id=organization_id,
            employee_id=employee_id,
            kind=kind,
            created_by=created_by,
            effective_from=parsed_posting.effective_from,
            change_reason=parsed_posting.change_reason,
            posting=parsed_posting,
        )
    if kind == "pay":
        parsed_pay = _validate(CreatePayVersionRequest, body)
        return await employees_service.create_employee_version(
            db,
            organization_id=organization_id,
            employee_id=employee_id,
            kind=kind,
            created_by=created_by,
            effective_from=parsed_pay.effective_from,
            change_reason=parsed_pay.change_reason,
            pay=parsed_pay,
        )
    if kind == "bank":
        parsed_bank = _validate(CreateBankVersionRequest, body)
        return await employees_service.create_employee_version(
            db,
            organization_id=organization_id,
            employee_id=employee_id,
            kind=kind,
            created_by=created_by,
            effective_from=parsed_bank.effective_from,
            change_reason=parsed_bank.change_reason,
            bank=parsed_bank,
        )

    raise ValidationError("kind must be one of: profile, posting, pay, bank")
