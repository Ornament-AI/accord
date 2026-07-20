"""Payroll run command routes (calculate).

Register with: ``app.include_router(run_commands.router, prefix="/api")``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id, tenant_user_id
from app.auth.principal import AuthPrincipal
from app.schemas.run_results import CalculateResponse
from app.services import run_calculation as run_calculation_service

router = APIRouter(tags=["payroll-run-commands"])


@router.post(
    "/payroll-runs/{run_id}/calculate",
    response_model=CalculateResponse,
)
async def calculate_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    return await run_calculation_service.calculate_run_command(
        db,
        organization_id=tenant_org_id(tenant),
        run_id=run_id,
        user_id=tenant_user_id(tenant),
    )
