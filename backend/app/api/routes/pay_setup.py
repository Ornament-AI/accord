"""Pay-setup master data routes (Phase 3)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id, tenant_user_id
from app.auth.principal import AuthPrincipal
from app.exceptions import ConflictError
from app.timezone import current_ist_date
from app.schemas.pay_setup import (
    AccommodationChargeVersionCreate,
    AccommodationChargeVersionResponse,
    AccommodationCreate,
    AccommodationResponse,
    AccommodationUpdate,
    AdvanceCreate,
    AdvanceInstallmentVersionCreate,
    AdvanceInstallmentVersionResponse,
    AdvanceResponse,
    ComponentRateVersionCreate,
    ComponentRateVersionResponse,
    PayComponentCreate,
    PayComponentResponse,
    PayrollExportProfile,
    PayrollExportProfileResponse,
    PayComponentUpdate,
    RecurringInstructionCreate,
    RecurringInstructionResponse,
    RecurringInstructionVersionCreate,
    RecurringInstructionVersionResponse,
    ReportConfigurationResponse,
    ReportConfigurationUpsert,
)
from app.services import pay_setup as pay_setup_service

router = APIRouter(tags=["pay-setup"])


@router.post(
    "/pay-components",
    response_model=PayComponentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pay_component(
    body: PayComponentCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_pay_component(
        db,
        organization_id=tenant_org_id(tenant),
        body=body,
    )


@router.get("/pay-components", response_model=list[PayComponentResponse])
async def list_pay_components(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_pay_components(
        db,
        organization_id=tenant_org_id(tenant),
    )


@router.patch("/pay-components/{component_id}", response_model=PayComponentResponse)
async def update_pay_component(
    component_id: UUID,
    tenant: TenantCtx,
    db: Session,
    body: dict[str, Any] = Body(...),
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    if "code" in body or "classification" in body:
        raise ConflictError("code and classification are immutable after creation.")
    try:
        update = PayComponentUpdate.model_validate(body)
    except PydanticValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    return await pay_setup_service.update_pay_component(
        db,
        organization_id=tenant_org_id(tenant),
        component_id=component_id,
        body=update,
    )


@router.post(
    "/pay-components/{component_id}/rate-versions",
    response_model=ComponentRateVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_component_rate_version(
    component_id: UUID,
    body: ComponentRateVersionCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_component_rate_version(
        db,
        organization_id=tenant_org_id(tenant),
        component_id=component_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.get(
    "/pay-components/{component_id}/rate-versions",
    response_model=list[ComponentRateVersionResponse],
)
async def list_component_rate_versions(
    component_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_component_rate_versions(
        db,
        organization_id=tenant_org_id(tenant),
        component_id=component_id,
    )


@router.post(
    "/employees/{employee_id}/recurring-instructions",
    response_model=RecurringInstructionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring_instruction(
    employee_id: UUID,
    body: RecurringInstructionCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_recurring_instruction(
        db,
        organization_id=tenant_org_id(tenant),
        employee_id=employee_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.get(
    "/employees/{employee_id}/recurring-instructions",
    response_model=list[RecurringInstructionResponse],
)
async def list_recurring_instructions(
    employee_id: UUID,
    tenant: TenantCtx,
    db: Session,
    as_of: date | None = Query(default=None),
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_recurring_instructions(
        db,
        organization_id=tenant_org_id(tenant),
        employee_id=employee_id,
        as_of=as_of or current_ist_date(),
    )


@router.post(
    "/recurring-instructions/{instruction_id}/versions",
    response_model=RecurringInstructionVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring_instruction_version(
    instruction_id: UUID,
    body: RecurringInstructionVersionCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_recurring_instruction_version(
        db,
        organization_id=tenant_org_id(tenant),
        instruction_id=instruction_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.get(
    "/recurring-instructions/{instruction_id}/versions",
    response_model=list[RecurringInstructionVersionResponse],
)
async def list_recurring_instruction_versions(
    instruction_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_recurring_instruction_versions(
        db,
        organization_id=tenant_org_id(tenant),
        instruction_id=instruction_id,
    )


@router.post(
    "/employees/{employee_id}/advances",
    response_model=AdvanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_advance(
    employee_id: UUID,
    body: AdvanceCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_advance(
        db,
        organization_id=tenant_org_id(tenant),
        employee_id=employee_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.get(
    "/employees/{employee_id}/advances",
    response_model=list[AdvanceResponse],
)
async def list_advances(
    employee_id: UUID,
    tenant: TenantCtx,
    db: Session,
    as_of: date | None = Query(default=None),
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_advances(
        db,
        organization_id=tenant_org_id(tenant),
        employee_id=employee_id,
        as_of=as_of or current_ist_date(),
    )


@router.post(
    "/advances/{advance_id}/installment-versions",
    response_model=AdvanceInstallmentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_advance_installment_version(
    advance_id: UUID,
    body: AdvanceInstallmentVersionCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_advance_installment_version(
        db,
        organization_id=tenant_org_id(tenant),
        advance_id=advance_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.post(
    "/employees/{employee_id}/accommodation",
    response_model=AccommodationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_accommodation(
    employee_id: UUID,
    body: AccommodationCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_accommodation(
        db,
        organization_id=tenant_org_id(tenant),
        employee_id=employee_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.get(
    "/employees/{employee_id}/accommodation",
    response_model=list[AccommodationResponse],
)
async def list_accommodation(
    employee_id: UUID,
    tenant: TenantCtx,
    db: Session,
    as_of: date | None = Query(default=None),
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_accommodation(
        db,
        organization_id=tenant_org_id(tenant),
        employee_id=employee_id,
        as_of=as_of or current_ist_date(),
    )


@router.patch(
    "/accommodation/{assignment_id}",
    response_model=AccommodationResponse,
)
async def update_accommodation(
    assignment_id: UUID,
    body: AccommodationUpdate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.update_accommodation(
        db,
        organization_id=tenant_org_id(tenant),
        assignment_id=assignment_id,
        body=body,
    )


@router.post(
    "/accommodation/{assignment_id}/charge-versions",
    response_model=AccommodationChargeVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_accommodation_charge_version(
    assignment_id: UUID,
    body: AccommodationChargeVersionCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.create_accommodation_charge_version(
        db,
        organization_id=tenant_org_id(tenant),
        assignment_id=assignment_id,
        created_by=tenant_user_id(tenant),
        body=body,
    )


@router.get(
    "/report-configurations",
    response_model=list[ReportConfigurationResponse],
)
async def list_report_configurations(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await pay_setup_service.list_report_configurations(
        db,
        organization_id=tenant_org_id(tenant),
    )


@router.put(
    "/report-configurations/{key}",
    response_model=ReportConfigurationResponse,
)
async def upsert_report_configuration(
    key: str,
    body: ReportConfigurationUpsert,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_organization")),
) -> dict[str, Any]:
    return await pay_setup_service.upsert_report_configuration(
        db,
        organization_id=tenant_org_id(tenant),
        key=key,
        value=body.value,
    )


@router.get("/report-profile", response_model=PayrollExportProfileResponse)
async def get_payroll_export_profile(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> dict[str, Any]:
    return await pay_setup_service.get_payroll_export_profile(
        db,
        organization_id=tenant_org_id(tenant),
    )


@router.put("/report-profile", response_model=PayrollExportProfileResponse)
async def upsert_payroll_export_profile(
    body: PayrollExportProfile,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("manage_organization")),
) -> dict[str, Any]:
    return await pay_setup_service.upsert_payroll_export_profile(
        db,
        organization_id=tenant_org_id(tenant),
        profile=body,
    )
