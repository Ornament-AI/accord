"""Export artifact routes (ADR 0010).

Register with: ``app.include_router(artifacts.router, prefix="/api")``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import Session, TenantCtx, require_capability, tenant_org_id, tenant_user_id
from app.api.responses import export_content_disposition
from app.auth.principal import AuthPrincipal
from app.models.platform import ExportArtifact
from app.schemas.artifacts import ArtifactListPage, ArtifactResponse
from app.services import artifacts as artifacts_service
from app.storage.protocol import ObjectStorage

router = APIRouter(tags=["artifacts"])

_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "text/csv": "csv",
    "text/plain": "txt",
    "application/json": "json",
    "application/pdf": "pdf",
    "application/xml": "xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/zip": "zip",
}


def get_object_storage(request: Request) -> ObjectStorage:
    """Resolve object storage from app state (wired by the orchestrator / tests)."""
    storage = getattr(request.app.state, "object_storage", None)
    if storage is None:
        raise RuntimeError("Object storage is not configured on application state")
    return storage


ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]


def _download_content_disposition(artifact: ExportArtifact) -> str:
    """Build Content-Disposition from report_type / template_version."""
    slug = f"{artifact.report_type}-{artifact.template_version}".replace("/", "-")
    extension = _CONTENT_TYPE_EXTENSIONS.get(artifact.content_type, "bin")
    return export_content_disposition(slug, extension)


@router.get("/artifacts", response_model=ArtifactListPage)
async def list_artifacts(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
    report_type: str | None = Query(default=None),
    posted_run_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ArtifactListPage:
    return await artifacts_service.list_artifacts(
        db,
        organization_id=tenant_org_id(tenant),
        report_type=report_type,
        posted_run_id=posted_run_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> ArtifactResponse:
    row = await artifacts_service.get_artifact(
        db,
        organization_id=tenant_org_id(tenant),
        artifact_id=artifact_id,
    )
    return ArtifactResponse.model_validate(row)


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID,
    tenant: TenantCtx,
    db: Session,
    storage: ObjectStorageDep,
    # generate_reports is used deliberately for downloading own-org artifacts:
    # ADR 0010 streams bytes through the API with per-request org/capability
    # checks and artifact.download audit; the same capability that authorizes
    # report generation also authorizes retrieving the resulting artifact.
    _: AuthPrincipal = Depends(require_capability("generate_reports")),
) -> StreamingResponse:
    download = await artifacts_service.stream_download(
        db,
        storage,
        organization_id=tenant_org_id(tenant),
        artifact_id=artifact_id,
        actor_user_id=tenant_user_id(tenant),
    )
    artifact = download.artifact
    return StreamingResponse(
        download.chunks,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": _download_content_disposition(artifact),
            "Content-Length": str(artifact.size_bytes),
        },
    )
