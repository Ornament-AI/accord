"""Payroll run calculate command: resolve master data → engine → immutable version."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.engine import calculate_run
from app.domain.payroll.validation import has_blocking, validate_run_inputs
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.audit_events import entity_snapshot, write_mutation_event
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.services.run_calculation._convert import (
    month_end,
    serialize_catalog,
    serialize_run_calc_input,
    to_db_classification,
    totals_payload,
    trace_payload,
)
from app.services.run_calculation.resolution import (
    assert_roster_calculable,
    load_component_catalog,
    resolve_run_calc_input,
)
from app.services.run_calculation.snapshots import (
    employee_report_identity_snapshot,
    recovery_sources_snapshot,
    report_profile_snapshot,
)

_ALLOWED_CALCULATE_STATUSES = frozenset({"draft", "calculated"})


async def calculate_run_command(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    """Resolve inputs, run the engine, and append an immutable run version."""
    stmt = (
        sa.select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .where(PayrollRun.organization_id == organization_id)
        .with_for_update()
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found.")
    if run.status not in _ALLOWED_CALCULATE_STATUSES:
        raise ConflictError(
            f"Payroll run cannot be calculated from status {run.status!r}; "
            "allowed statuses are draft and calculated."
        )
    # Draft runs require an explicit saved roster. Legacy non-draft runs may still
    # recalculate with roster_initialized=false (pre-roster migration), which
    # falls back to all organization employees in resolve_run_calc_input.
    if run.status == "draft" and not run.roster_initialized:
        raise ConflictError("Payroll run roster must be saved before calculation.")

    run_before = entity_snapshot(run)

    period = await db.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != organization_id:
        raise NotFoundError("Payroll period not found.")

    # Roster-to-calculation integrity: every saved roster member must resolve
    # to an active profile at period month-end, before the status transition
    # or any version row is created. This turns silent partial calculations
    # into explicit failures the operator can act on.
    if run.roster_initialized:
        await assert_roster_calculable(
            db, organization_id=organization_id, run_id=run.id, period=period
        )

    run.status = "calculating"
    await db.flush()

    run_input, employee_by_ref = await resolve_run_calc_input(
        db,
        organization_id=organization_id,
        period=period,
        run_id=run.id,
    )
    if not run_input.employees:
        # Covers the legacy roster_initialized=false fallback; the roster path
        # is already guarded by assert_roster_calculable above. The raised
        # error rolls back the transaction, restoring the pre-call status.
        raise ConflictError("No calculable employees resolved for this run; nothing to calculate.")

    # Pre-calculation structural checks (T1.4): error-severity findings such
    # as negative amounts on non-adjustment kinds or missing amount/rate block
    # calculation instead of flowing through to a posted version.
    input_findings = validate_run_inputs(run_input)
    if has_blocking(input_findings):
        raise ValidationError(
            "Run inputs failed validation; resolve the reported findings and recalculate.",
            details={
                "findings": [
                    {
                        "code": finding.code,
                        "severity": finding.severity.value,
                        "employee_ref": finding.employee_ref,
                        "component_code": finding.component_code,
                        "message": finding.message,
                    }
                    for finding in input_findings
                ]
            },
        )
    result = calculate_run(run_input)

    max_version_stmt = sa.select(
        sa.func.coalesce(sa.func.max(payroll_run_versions.c.version_number), 0)
    ).where(
        payroll_run_versions.c.organization_id == organization_id,
        payroll_run_versions.c.run_id == run.id,
    )
    next_version = int((await db.execute(max_version_stmt)).scalar_one()) + 1
    version_id = uuid.uuid4()
    calculated_at = datetime.now(timezone.utc)
    inputs_snapshot = serialize_run_calc_input(run_input)
    catalog = await load_component_catalog(db, organization_id=organization_id)
    inputs_snapshot["component_catalog"] = serialize_catalog(catalog)
    inputs_snapshot["employee_identity"] = await employee_report_identity_snapshot(
        db,
        organization_id=organization_id,
        employee_by_ref=employee_by_ref,
        on_date=month_end(period.period_year, period.period_month),
    )
    inputs_snapshot["report_profile"] = await report_profile_snapshot(
        db, organization_id=organization_id
    )
    inputs_snapshot["recovery_sources"] = await recovery_sources_snapshot(
        db,
        organization_id=organization_id,
        result=result,
    )
    totals = totals_payload(result)

    await db.execute(
        sa.insert(payroll_run_versions).values(
            id=version_id,
            organization_id=organization_id,
            run_id=run.id,
            version_number=next_version,
            engine_version=result.engine_version,
            content_hash=result.content_hash,
            calculated_at=calculated_at,
            calculated_by=user_id,
            inputs_snapshot=inputs_snapshot,
            totals=totals,
        )
    )

    for emp_result in result.employees:
        employee = employee_by_ref.get(emp_result.employee_ref)
        if employee is None:
            raise ValidationError(
                f"Engine returned unknown employee_ref {emp_result.employee_ref!r}."
            )
        employee_result_id = uuid.uuid4()
        await db.execute(
            sa.insert(payroll_employee_results).values(
                id=employee_result_id,
                organization_id=organization_id,
                run_version_id=version_id,
                employee_id=employee.id,
                employee_number=employee.employee_number,
                earnings_total=emp_result.earnings_total.amount,
                employer_contribution_total=emp_result.employer_contribution_total.amount,
                gross_total=emp_result.gross_total.amount,
                deductions_total=emp_result.deductions_total.amount,
                net_payable=emp_result.net_payable.amount,
                offbill_employer_remittance=emp_result.offbill_employer_remittance.amount,
                disbursement=emp_result.disbursement.amount,
            )
        )
        line_rows: list[dict[str, Any]] = []
        for sequence, trace in enumerate(emp_result.lines, start=1):
            line_rows.append(
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "employee_result_id": employee_result_id,
                    "component_code": trace.component,
                    "classification": to_db_classification(trace.classification),
                    "calc_kind": trace.calculator_kind,
                    "amount": trace.rounded_value.amount,
                    "sequence": sequence,
                    "trace": trace_payload(trace),
                }
            )
        if line_rows:
            await db.execute(sa.insert(payroll_result_lines).values(line_rows))

    run.current_version_id = version_id
    run.status = "calculated"
    run.lock_version = run.lock_version + 1
    run.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await write_mutation_event(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        command="payroll_run.calculate",
        entity_type="payroll_run",
        entity_id=run.id,
        entity_label=f"Payroll run {run.id}",
        before_state=run_before,
        after_state=entity_snapshot(run),
        summary={
            "version_id": version_id,
            "version_number": next_version,
            "content_hash": result.content_hash,
            "engine_version": result.engine_version,
            "employee_count": len(result.employees),
        },
        metadata={"totals": totals},
    )
    await db.commit()

    return {
        "run_id": run.id,
        "version_id": version_id,
        "version_number": next_version,
        "content_hash": result.content_hash,
        "engine_version": result.engine_version,
        "totals": totals,
    }
