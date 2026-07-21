"""Calculated payroll run result read routes.

Register with: ``app.include_router(run_results.router, prefix="/api")``.

Error conventions for version resolution (see service docstring):
missing run → 404; no calculated version / unknown version_number → 409.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id
from app.auth.principal import AuthPrincipal
from app.schemas.run_results import EmployeeResultDetail, RunResultsResponse
from app.services import run_results as run_results_service

router = APIRouter(tags=["payroll-run-results"])


@router.get(
    "/payroll-runs/{run_id}/results",
    response_model=RunResultsResponse,
)
async def get_payroll_run_results(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    version_number: int | None = Query(default=None),
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> dict[str, Any]:
    return await run_results_service.get_run_results(
        db,
        organization_id=tenant_org_id(tenant),
        run_id=run_id,
        version_number=version_number,
    )


@router.get(
    "/payroll-runs/{run_id}/results/{employee_id}",
    response_model=EmployeeResultDetail,
)
async def get_payroll_run_employee_result(
    run_id: UUID,
    employee_id: UUID,
    tenant: TenantCtx,
    db: Session,
    version_number: int | None = Query(default=None),
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> dict[str, Any]:
    return await run_results_service.get_employee_result(
        db,
        organization_id=tenant_org_id(tenant),
        run_id=run_id,
        employee_id=employee_id,
        version_number=version_number,
    )
