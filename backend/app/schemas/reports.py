"""Pydantic schemas for report generation API."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportTypeItem(BaseModel):
    """One registered report type and the formats it supports."""

    model_config = ConfigDict(extra="forbid")

    report_type: str
    title: str | None = None
    formats: list[str]
    product_sheet: bool = False
    template_version: str | None = None


class ReportTypeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReportTypeItem]


class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: str = Field(min_length=1)
    posted_run_id: UUID
    format: Literal["excel", "pdf", "json"]
    template_version: str | None = None
    variant_key: str | None = Field(default=None, min_length=1)


class GenerateReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str


class ExportReportsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posted_run_id: UUID
    template_version: str | None = None


class ExportReportsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str


class ReportJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str
    result: dict[str, Any] | None = None
    last_error: str | None = None


class ReportPreviewResponse(BaseModel):
    """Synchronous JSON preview of a report (``to_json`` shape)."""

    model_config = ConfigDict(extra="forbid")

    report_type: str
    template_version: str
    title: str
    organization_name: str
    subtitle: str
    sections: list[dict[str, Any]]
