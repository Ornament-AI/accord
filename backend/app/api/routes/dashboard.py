"""Payroll dashboard summary route.

Register with: ``app.include_router(dashboard.router, prefix="/api")``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.principal import AuthPrincipal
from app.schemas.dashboard import DashboardResponse
from app.services import dashboard as dashboard_service

router = APIRouter(tags=["dashboard"])


def _org_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.organization_id)


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
)
async def get_dashboard(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> dict[str, Any]:
    return await dashboard_service.get_dashboard_summary(
        db,
        organization_id=_org_id(tenant),
    )
