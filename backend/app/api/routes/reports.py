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

from fastapi import APIRouter, Depends, Header, Query, Request, status

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id, tenant_user_id
from app.auth.principal import AuthPrincipal
from app.jobs.protocol import JobQueue
from app.reports.base import ReportRegistry
from app.schemas.reports import (
    ExportReportsRequest,
    ExportReportsResponse,
    GenerateReportRequest,
    GenerateReportResponse,
    ReportJobResponse,
    ReportPreviewResponse,
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
            ReportTypeItem(
                report_type=item.report_type,
                title=item.title,
                formats=list(item.formats),
                product_sheet=item.product_sheet,
                template_version=item.template_version,
            )
            for item in items
        ]
    )


@router.post(
    "/reports/export",
    response_model=ExportReportsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_reports(
    body: ExportReportsRequest,
    tenant: TenantCtx,
    db: Session,
    registry: ReportRegistryDep,
    queue: JobQueueDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> ExportReportsResponse:
    org_id = tenant_org_id(tenant)
    user_id = tenant_user_id(tenant)
    request_payload = {
        "command": "export_reports",
        "posted_run_id": str(body.posted_run_id),
        "template_version": body.template_version,
    }

    async def _execute() -> dict[str, Any]:
        job = await report_generation_service.request_consolidated_export(
            db,
            queue,
            organization_id=org_id,
            posted_run_id=body.posted_run_id,
            requested_by=user_id,
            registry=registry,
            template_version=body.template_version,
        )
        return {"job_id": str(job.id), "status": str(job.status)}

    result = await _maybe_idempotent(
        db,
        organization_id=org_id,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        executor=_execute,
    )
    return ExportReportsResponse(job_id=UUID(result["job_id"]), status=result["status"])


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
    org_id = tenant_org_id(tenant)
    user_id = tenant_user_id(tenant)
    request_payload = {
        "command": "generate_report",
        "report_type": body.report_type,
        "posted_run_id": str(body.posted_run_id),
        "format": body.format,
        "template_version": body.template_version,
        "variant_key": body.variant_key,
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
            variant_key=body.variant_key,
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
        organization_id=tenant_org_id(tenant),
        job_id=job_id,
    )
    return ReportJobResponse(
        job_id=info.job_id,
        status=info.status,
        result=info.result,
        last_error=info.last_error,
    )


@router.get(
    "/reports/{report_type}/preview",
    response_model=ReportPreviewResponse,
)
async def preview_report(
    report_type: str,
    tenant: TenantCtx,
    db: Session,
    registry: ReportRegistryDep,
    posted_run_id: UUID = Query(...),
    template_version: str | None = Query(default=None),
    variant_key: str | None = Query(default=None),
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> ReportPreviewResponse:
    """Sync JSON preview. Declared after static ``/reports/...`` paths."""
    payload = await report_generation_service.preview_report(
        db,
        organization_id=tenant_org_id(tenant),
        report_type=report_type,
        posted_run_id=posted_run_id,
        template_version=template_version,
        variant_key=variant_key,
        registry=registry,
        actor_user_id=tenant_user_id(tenant),
    )
    return ReportPreviewResponse.model_validate(payload)
