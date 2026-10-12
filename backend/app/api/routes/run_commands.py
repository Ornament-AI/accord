"""Payroll run command routes (calculate).

Register with: ``app.include_router(run_commands.router, prefix="/api")``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id, tenant_user_id
from app.auth.principal import AuthPrincipal
from app.middleware.rate_limit import limiter
from app.schemas.run_results import CalculateResponse
from app.services import run_calculation as run_calculation_service
from app.services.idempotency import idempotent_command

router = APIRouter(tags=["payroll-run-commands"])


@router.post(
    "/payroll-runs/{run_id}/calculate",
    response_model=CalculateResponse,
)
@limiter.limit("10/minute")
async def calculate_payroll_run(
    request: Request,
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    org_id = tenant_org_id(tenant)
    user_id = tenant_user_id(tenant)

    async def _execute() -> dict[str, Any]:
        return await run_calculation_service.calculate_run_command(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
        )

    if not idempotency_key:
        return await _execute()
    return await idempotent_command(
        db,
        organization_id=org_id,
        key=idempotency_key,
        request_payload={
            "command": "calculate",
            "run_id": str(run_id),
            "actor_user_id": str(user_id),
        },
        executor=_execute,
    )
