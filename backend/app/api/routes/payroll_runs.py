"""Payroll period / run / draft-input routes.

Register with: ``app.include_router(payroll_runs.router, prefix="/api")``.

Input upsert returns HTTP 200 for both create and update (documented choice).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import Session, TenantCtx, require_any_capability, require_capability
from app.auth.principal import AuthPrincipal
from app.schemas.payroll_runs import (
    PayrollPeriodCreate,
    PayrollPeriodResponse,
    PayrollRunCreate,
    PayrollRunDetail,
    PayrollRunInputResponse,
    PayrollRunInputUpsert,
    PayrollRunEmployeeResponse,
    PayrollRunRosterHistoryResponse,
    PayrollRunRosterUpdate,
    PayrollRunReportMetadata,
    ReportReadinessResponse,
    PayrollRunListItem,
)
from app.services import payroll_runs as payroll_runs_service

router = APIRouter(tags=["payroll-runs"])


def _org_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.organization_id)


def _user_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.user_id)


@router.post(
    "/payroll-periods",
    response_model=PayrollPeriodResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payroll_period(
    body: PayrollPeriodCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    return await payroll_runs_service.create_period(
        db,
        organization_id=_org_id(tenant),
        body=body,
    )


@router.get("/payroll-periods", response_model=list[PayrollPeriodResponse])
async def list_payroll_periods(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await payroll_runs_service.list_periods(
        db,
        organization_id=_org_id(tenant),
    )


@router.post(
    "/payroll-runs",
    response_model=PayrollRunListItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_payroll_run(
    body: PayrollRunCreate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    return await payroll_runs_service.create_run(
        db,
        organization_id=_org_id(tenant),
        body=body,
    )


@router.get("/payroll-runs", response_model=list[PayrollRunListItem])
async def list_payroll_runs(
    tenant: TenantCtx,
    db: Session,
    period_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    # Readable by every run-lifecycle participant, incl. approver/releaser who
    # lack view_master_data but must load runs they approve/post (maker-checker).
    _: AuthPrincipal = Depends(
        require_any_capability(
            "view_master_data",
            "create_run",
            "submit_run",
            "approve_run",
            "post_run",
        )
    ),
) -> list[dict[str, Any]]:
    return await payroll_runs_service.list_runs(
        db,
        organization_id=_org_id(tenant),
        period_id=period_id,
        status=status_filter,
    )


@router.get("/payroll-runs/{run_id}", response_model=PayrollRunDetail)
async def get_payroll_run(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    # Readable by every run-lifecycle participant, incl. approver/releaser who
    # lack view_master_data but must load runs they approve/post (maker-checker).
    _: AuthPrincipal = Depends(
        require_any_capability(
            "view_master_data",
            "create_run",
            "submit_run",
            "approve_run",
            "post_run",
        )
    ),
) -> dict[str, Any]:
    return await payroll_runs_service.get_run(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
    )


@router.get(
    "/payroll-runs/{run_id}/report-metadata",
    response_model=PayrollRunReportMetadata,
)
async def get_payroll_run_report_metadata(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> dict[str, Any]:
    return await payroll_runs_service.get_run_report_metadata(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
    )


@router.put(
    "/payroll-runs/{run_id}/report-metadata",
    response_model=PayrollRunReportMetadata,
)
async def update_payroll_run_report_metadata(
    run_id: UUID,
    body: PayrollRunReportMetadata,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    return await payroll_runs_service.update_run_report_metadata(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
        body=body,
    )


@router.get(
    "/payroll-runs/{run_id}/report-readiness",
    response_model=ReportReadinessResponse,
)
async def get_payroll_run_report_readiness(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> dict[str, Any]:
    return await payroll_runs_service.get_report_readiness(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
    )


@router.get(
    "/payroll-runs/{run_id}/roster",
    response_model=list[PayrollRunEmployeeResponse],
)
async def list_payroll_run_roster(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    # Match run detail: approvers/releasers must see roster content without
    # view_master_data.
    _: AuthPrincipal = Depends(
        require_any_capability(
            "view_master_data",
            "create_run",
            "submit_run",
            "approve_run",
            "post_run",
        )
    ),
) -> list[dict[str, Any]]:
    return await payroll_runs_service.list_run_roster(
        db, organization_id=_org_id(tenant), run_id=run_id
    )


@router.put(
    "/payroll-runs/{run_id}/roster",
    response_model=list[PayrollRunEmployeeResponse],
)
async def replace_payroll_run_roster(
    run_id: UUID,
    body: PayrollRunRosterUpdate,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> list[dict[str, Any]]:
    return await payroll_runs_service.replace_run_roster(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
        actor_user_id=_user_id(tenant),
        body=body,
    )


@router.get(
    "/payroll-runs/{run_id}/roster-history",
    response_model=list[PayrollRunRosterHistoryResponse],
)
async def list_payroll_run_roster_history(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(
        require_any_capability(
            "view_master_data",
            "create_run",
            "submit_run",
            "approve_run",
            "post_run",
        )
    ),
) -> list[dict[str, Any]]:
    return await payroll_runs_service.list_run_roster_history(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
    )


@router.put(
    "/payroll-runs/{run_id}/inputs/{employee_id}/{component_code}",
    response_model=PayrollRunInputResponse,
)
async def upsert_payroll_run_input(
    run_id: UUID,
    employee_id: UUID,
    component_code: str,
    body: PayrollRunInputUpsert,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> dict[str, Any]:
    # 200 for both create and update (upsert semantics).
    return await payroll_runs_service.upsert_run_input(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
        employee_id=employee_id,
        component_code=component_code,
        actor_user_id=_user_id(tenant),
        body=body,
    )


@router.get(
    "/payroll-runs/{run_id}/inputs",
    response_model=list[PayrollRunInputResponse],
)
async def list_payroll_run_inputs(
    run_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_master_data")),
) -> list[dict[str, Any]]:
    return await payroll_runs_service.list_run_inputs(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
    )


@router.delete(
    "/payroll-runs/{run_id}/inputs/{input_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_payroll_run_input(
    run_id: UUID,
    input_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("create_run")),
) -> Response:
    await payroll_runs_service.delete_run_input(
        db,
        organization_id=_org_id(tenant),
        run_id=run_id,
        input_id=input_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
