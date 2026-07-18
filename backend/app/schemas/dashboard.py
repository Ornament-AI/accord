"""Pydantic schemas for the payroll dashboard summary API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RegimeBreakdown(BaseModel):
    gpf: int
    nps: int
    epf: int


class HeadcountSummary(BaseModel):
    active_employees: int
    by_regime: RegimeBreakdown


class CurrentPeriodRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    version_number: int | None


class CurrentPeriodSummary(BaseModel):
    year: int
    month: int
    run: CurrentPeriodRun | None


class PeriodYearMonth(BaseModel):
    year: int
    month: int


class PostedTotals(BaseModel):
    earnings: str
    employer_contribution: str
    gross: str
    deductions: str
    net: str


class PostedRunSummary(BaseModel):
    run_id: UUID
    period: PeriodYearMonth
    totals: PostedTotals
    posted_at: datetime


class VarianceSummary(BaseModel):
    gross_delta: str
    net_delta: str


class PipelineSummary(BaseModel):
    """Counts of ``PayrollRun`` rows by status.

    ``calculating`` runs are omitted from this map (not rolled into another
    bucket).
    """

    draft: int
    calculated: int
    submitted: int
    approved: int
    posted: int
    rejected: int
    reversed: int


class RecentArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_type: str
    created_at: datetime


class DashboardResponse(BaseModel):
    headcount: HeadcountSummary
    current_period: CurrentPeriodSummary | None
    latest_posted: PostedRunSummary | None
    previous_posted: PostedRunSummary | None
    variance: VarianceSummary | None
    pipeline: PipelineSummary
    recent_artifacts: list[RecentArtifactSummary]
