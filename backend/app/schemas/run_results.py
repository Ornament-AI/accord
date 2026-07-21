"""Pydantic schemas for calculated payroll run results and calculate response."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from app.schemas.money import MoneyAmount


class CurrentVersion(BaseModel):
    """Immutable calculated version summary (run detail + results list)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    content_hash: str
    engine_version: str
    calculated_at: datetime
    totals: dict[str, str]


class CalculateResponse(BaseModel):
    """Response body for POST /payroll-runs/{run_id}/calculate."""

    run_id: UUID
    version_id: UUID
    version_number: int
    content_hash: str
    engine_version: str
    totals: dict[str, str]


class EmployeeResultSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    employee_number: str
    earnings_total: MoneyAmount
    employer_contribution_total: MoneyAmount
    gross_total: MoneyAmount
    deductions_total: MoneyAmount
    net_payable: MoneyAmount
    # Employee disbursement is reconciled separately from treasury-face net
    # payable: disbursement = net_payable + offbill_employer_remittance
    # (docs/payroll-domain.md "Resolved").
    offbill_employer_remittance: MoneyAmount
    disbursement: MoneyAmount


class RunResultsResponse(BaseModel):
    version: CurrentVersion
    totals: dict[str, str]
    employees: list[EmployeeResultSummary]


class ResultLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_code: str
    classification: str
    calc_kind: str
    amount: MoneyAmount
    trace: dict[str, Any]


class EmployeeResultDetail(BaseModel):
    employee_id: UUID
    employee_number: str
    earnings_total: MoneyAmount
    employer_contribution_total: MoneyAmount
    gross_total: MoneyAmount
    deductions_total: MoneyAmount
    net_payable: MoneyAmount
    # Employee disbursement is reconciled separately from treasury-face net
    # payable: disbursement = net_payable + offbill_employer_remittance
    # (docs/payroll-domain.md "Resolved").
    offbill_employer_remittance: MoneyAmount
    disbursement: MoneyAmount
    lines: list[ResultLine]
