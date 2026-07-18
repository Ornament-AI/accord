"""Pydantic schemas for report generation API."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportTypeItem(BaseModel):
    """One registered report type and the formats it supports."""

    model_config = ConfigDict(extra="forbid")

    report_type: str
    formats: list[str]


class ReportTypeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReportTypeItem]


class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: str = Field(min_length=1)
    posted_run_id: UUID
    format: Literal["excel", "pdf", "json"]
    template_version: str | None = None


class GenerateReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str


class ReportJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str
    result: dict[str, Any] | None = None
    last_error: str | None = None
