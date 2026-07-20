"""Shared helpers for initializing payroll-run rosters in tests."""

from __future__ import annotations

import calendar
from decimal import Decimal
from uuid import UUID

from app.models.payroll_runs import PayrollRun, PayrollRunEmployee


def initialize_run_roster(
    *,
    organization_id: UUID,
    run: PayrollRun,
    employee_ids: list[UUID],
    period_year: int,
    period_month: int,
) -> list[PayrollRunEmployee]:
    """Mark a run's roster initialized with full-period payable days for each employee."""
    payable_days = Decimal(str(calendar.monthrange(period_year, period_month)[1]))
    run.roster_initialized = True
    rows = [
        PayrollRunEmployee(
            organization_id=organization_id,
            run_id=run.id,
            employee_id=employee_id,
            payable_days=payable_days,
        )
        for employee_id in employee_ids
    ]
    return rows
