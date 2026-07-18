"""Report generation routes (ADR 0010).

Register with: ``app.include_router(reports.router, prefix="/api")``.

App-state wiring (orchestrator / tests)
---------------------------------------
* ``request.app.state.report_registry`` — :class:`~app.reports.base.ReportRegistry`
* ``request.app.state.job_queue`` — :class:`~app.jobs.protocol.JobQueue`
* ``request.app.state.object_storage`` — used by the worker handler seam, not
  these routes directly

Each missing attribute raises ``RuntimeError``.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.principal import AuthPrincipal
from app.jobs.protocol import JobQueue
from app.reports.base import ReportRegistry
from app.schemas.reports import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportJobResponse,
    ReportTypeItem,
    ReportTypeListResponse,
)
from app.services import report_generation as report_generation_service
from app.services.idempotency import idempotent_command

router = APIRouter(tags=["reports"])


def get_report_registry(request: Request) -> ReportRegistry:
    """Resolve report registry from app state (wired by the orchestrator / tests)."""
    registry = getattr(request.app.state, "report_registry", None)
    if registry is None:
        raise RuntimeError("Report registry is not configured on application state")
    return registry


def get_job_queue(request: Request) -> JobQueue:
    """Resolve job queue from app state (wired by the orchestrator / tests)."""
    queue = getattr(request.app.state, "job_queue", None)
    if queue is None:
        raise RuntimeError("Job queue is not configured on application state")
    return queue


ReportRegistryDep = Annotated[ReportRegistry, Depends(get_report_registry)]
JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]


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


@router.get("/reports", response_model=ReportTypeListResponse)
async def list_reports(
    tenant: TenantCtx,
    registry: ReportRegistryDep,
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> ReportTypeListResponse:
    _ = tenant
    items = report_generation_service.list_registered_reports(registry)
    return ReportTypeListResponse(
        items=[
            ReportTypeItem(report_type=item.report_type, formats=list(item.formats))
            for item in items
        ]
    )


@router.post(
    "/reports/generate",
    response_model=GenerateReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_report(
    body: GenerateReportRequest,
    tenant: TenantCtx,
    db: Session,
    registry: ReportRegistryDep,
    queue: JobQueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> GenerateReportResponse:
    org_id = _org_id(tenant)
    user_id = _user_id(tenant)
    request_payload = {
        "command": "generate_report",
        "report_type": body.report_type,
        "posted_run_id": str(body.posted_run_id),
        "format": body.format,
        "template_version": body.template_version,
    }

    async def _execute() -> dict[str, Any]:
        job = await report_generation_service.request_report(
            db,
            queue,
            organization_id=org_id,
            report_type=body.report_type,
            posted_run_id=body.posted_run_id,
            format=body.format,
            template_version=body.template_version,
            requested_by=user_id,
            registry=registry,
        )
        return {"job_id": str(job.id), "status": str(job.status)}

    result = await _maybe_idempotent(
        db,
        organization_id=org_id,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        executor=_execute,
    )
    return GenerateReportResponse(job_id=UUID(result["job_id"]), status=result["status"])


@router.get("/reports/jobs/{job_id}", response_model=ReportJobResponse)
async def get_report_job(
    job_id: UUID,
    tenant: TenantCtx,
    db: Session,
    queue: JobQueueDep,
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> ReportJobResponse:
    info = await report_generation_service.get_report_job(
        db,
        queue,
        organization_id=_org_id(tenant),
        job_id=job_id,
    )
    return ReportJobResponse(
        job_id=info.job_id,
        status=info.status,
        result=info.result,
        last_error=info.last_error,
    )
