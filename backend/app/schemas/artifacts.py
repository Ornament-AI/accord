"""Pydantic schemas for export-artifact API (ADR 0010)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.pagination import PaginatedResponse


class ArtifactResponse(BaseModel):
    """Public metadata for an export artifact (object key is storage-internal)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    posted_run_id: UUID | None = None
    report_type: str
    template_version: str
    engine_version: str | None = None
    checksum_sha256: str
    content_type: str
    size_bytes: int
    object_version: str | None = None
    status: str
    requested_by: UUID
    retention_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


ArtifactListPage = PaginatedResponse[ArtifactResponse]
