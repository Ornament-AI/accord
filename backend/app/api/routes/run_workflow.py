"""Payroll run workflow command routes (validate / submit / withdraw / approve / reject).

Register with: ``app.include_router(run_workflow.router, prefix="/api")``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header
from pydantic import BaseModel, Field

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.principal import AuthPrincipal
from app.services import run_workflow as run_workflow_service
from app.services.idempotency import idempotent_command

router = APIRouter(tags=["payroll-run-workflow"])


class ReasonBody(BaseModel):
    reason: str | None = Field(default=None)


def _org_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.organization_id)


def _user_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.user_id)


async def _maybe_idempotent(
    db: Session,
    *,
    organization_id: UUID,
    idempotency_key: str | None,
    request_payload: dict[str, Any],
    executor,
) -> dict[str, Any]:
    if idempotency_key:
        return await idempotent_command(
            db,
            organization_id=organization_id,
            key=idempotency_key,
            request_payload=request_payload,
            executor=executor,
        )
    return await executor()


@router.post("/payroll-runs/{run_id}/validate")
async def validate_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    return await run_workflow_service.validate_run(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
    )


@router.post("/payroll-runs/{run_id}/submit")
async def submit_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    body: ReasonBody | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("submit_run")),
) -> dict[str, Any]:
    reason = None if body is None else body.reason
    org_id = _org_id(tenant)
    user_id = _user_id(tenant)
    payload = {
        "command": "submit",
        "run_id": str(run_id),
        "reason": reason,
    }

    async def _execute() -> dict[str, Any]:
        return await run_workflow_service.submit_run(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    return await _maybe_idempotent(
        db,
        organization_id=org_id,
        idempotency_key=idempotency_key,
        request_payload=payload,
        executor=_execute,
    )


@router.post("/payroll-runs/{run_id}/withdraw")
async def withdraw_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    body: ReasonBody | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("submit_run")),
) -> dict[str, Any]:
    reason = None if body is None else body.reason
    org_id = _org_id(tenant)
    user_id = _user_id(tenant)
    payload = {
        "command": "withdraw",
        "run_id": str(run_id),
        "reason": reason,
    }

    async def _execute() -> dict[str, Any]:
        return await run_workflow_service.withdraw_run(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    return await _maybe_idempotent(
        db,
        organization_id=org_id,
        idempotency_key=idempotency_key,
        request_payload=payload,
        executor=_execute,
    )


@router.post("/payroll-runs/{run_id}/approve")
async def approve_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    body: ReasonBody | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("approve_run")),
) -> dict[str, Any]:
    reason = None if body is None else body.reason
    org_id = _org_id(tenant)
    user_id = _user_id(tenant)
    payload = {
        "command": "approve",
        "run_id": str(run_id),
        "reason": reason,
    }

    async def _execute() -> dict[str, Any]:
        return await run_workflow_service.approve_run(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    return await _maybe_idempotent(
        db,
        organization_id=org_id,
        idempotency_key=idempotency_key,
        request_payload=payload,
        executor=_execute,
    )


@router.post("/payroll-runs/{run_id}/reject")
async def reject_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    body: ReasonBody | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("approve_run")),
) -> dict[str, Any]:
    reason = None if body is None else body.reason
    org_id = _org_id(tenant)
    user_id = _user_id(tenant)
    payload = {
        "command": "reject",
        "run_id": str(run_id),
        "reason": reason,
    }

    async def _execute() -> dict[str, Any]:
        return await run_workflow_service.reject_run(
            db,
            organization_id=org_id,
            run_id=run_id,
            user_id=user_id,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    return await _maybe_idempotent(
        db,
        organization_id=org_id,
        idempotency_key=idempotency_key,
        request_payload=payload,
        executor=_execute,
    )
