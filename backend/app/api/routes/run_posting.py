"""Payroll run post / reverse command routes.

Register with: ``app.include_router(run_posting.router, prefix="/api")``.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, field_validator

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id, tenant_user_id
from app.auth.principal import AuthPrincipal
from app.services import run_posting as run_posting_service
from app.services.idempotency import idempotent_command

router = APIRouter(tags=["payroll-run-posting"])


class ReverseRunRequest(BaseModel):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason is required")
        return value


@router.post("/payroll-runs/{run_id}/post")
async def post_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _: AuthPrincipal = Depends(require_capability("post_run")),
) -> dict[str, Any]:
    org_id = tenant_org_id(tenant)
    user_id = tenant_user_id(tenant)

    async def _execute() -> dict[str, Any]:
        return await run_posting_service.post_run(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    return await idempotent_command(
        db,
        organization_id=org_id,
        key=idempotency_key,
        request_payload={"command": "post", "run_id": str(run_id)},
        executor=_execute,
    )


@router.post("/payroll-runs/{run_id}/reverse")
async def reverse_payroll_run(
    run_id: UUID,
    body: ReverseRunRequest,
    tenant: TenantCtx,
    db: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    _: AuthPrincipal = Depends(require_capability("post_run")),
) -> dict[str, Any]:
    org_id = tenant_org_id(tenant)
    user_id = tenant_user_id(tenant)

    async def _execute() -> dict[str, Any]:
        return await run_posting_service.reverse_run(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
            reason=body.reason,
            idempotency_key=idempotency_key,
        )

    return await idempotent_command(
        db,
        organization_id=org_id,
        key=idempotency_key,
        request_payload={
            "command": "reverse",
            "run_id": str(run_id),
            "reason": body.reason,
        },
        executor=_execute,
    )
