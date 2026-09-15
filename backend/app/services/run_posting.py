"""Payroll run post / reverse commands (ADR 0008 §5, ADR 0009).

Single-transaction posting: status transition + PayrollApproval + AuditEvent +
OutboxEvent commit together or not at all.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from asyncpg.exceptions import UniqueViolationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.engine import content_hash_for
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.results import (
    CalculationTrace,
    EmployeeResult,
    RunResult,
    canonical_unrounded_str,
)
from app.domain.payroll.validation import has_blocking, validate_run_result
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_report_snapshots,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.identity import Organization
from app.models.platform import OutboxEvent, PayrollApproval
from app.services.audit_events import entity_snapshot, write_mutation_event
from app.services.db_errors import integrity_is
from app.services.run_workflow import URN_STALE_VERSION
from app.schemas.payroll_runs import PayrollRunReportMetadata

# ADR 0008 §4: maker/checker SoD is submitter ≠ approver only. Poster may equal
# approver (report_releaser posts; payroll_approver approves). Poster ≠ submitter
# is NOT required and is intentionally not checked here.


def _period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _money_from_db(value: Decimal | str | None) -> Money:
    if value is None:
        return Money.zero()
    if isinstance(value, Decimal):
        return Money.from_decimal(value)
    return Money.from_str(str(value))


def _optional_money_from_canonical(value: Any) -> Money | None:
    if value is None:
        return None
    return Money.from_str(str(value))


def _optional_rate_from_canonical(value: Any) -> Rate | None:
    if value is None:
        return None
    return Rate.from_fraction(str(value))


# ``informational`` / ``excluded_from_totals`` are added to ``CalculationTrace``
# alongside the trace-payload write in a parallel change; restore them only when
# the dataclass declares the fields so either landing order keeps working, and
# read with ``.get(name, False)`` so pre-existing payloads without the keys
# still reconstruct.
_TRACE_FLAG_FIELDS = tuple(
    name
    for name in ("informational", "excluded_from_totals")
    if name in CalculationTrace.__dataclass_fields__
)


def _trace_from_row(row: Any) -> CalculationTrace:
    payload = row["trace"] or {}
    classification = payload.get("classification")
    if classification is None:
        # Fallback if trace omitted domain classification.
        db_class = row["classification"]
        classification = "AG_deduction" if db_class == "ag_deduction" else db_class
    basis_raw = payload.get("basis") or []
    source_ids = payload.get("source_version_ids") or []
    return CalculationTrace(
        component=payload.get("component") or row["component_code"],
        classification=str(classification),
        basis=tuple(str(item) for item in basis_raw),
        basis_total=_optional_money_from_canonical(payload.get("basis_total")),
        rate=_optional_rate_from_canonical(payload.get("rate")),
        unrounded_value=canonical_unrounded_str(payload.get("unrounded_value", "0")),
        rounding_rule=str(payload.get("rounding_rule") or "ROUND_NONE"),
        rounded_value=_money_from_db(row["amount"]),
        source_version_ids=tuple(str(item) for item in source_ids),
        calculator_kind=str(payload.get("calculator_kind") or row["calc_kind"]),
        engine_version=str(payload.get("engine_version") or ""),
        employer_transfer=bool(payload.get("employer_transfer", False)),
        transfer_of=(None if payload.get("transfer_of") is None else str(payload["transfer_of"])),
        service_period=(
            None if payload.get("service_period") is None else str(payload["service_period"])
        ),
        reason=(None if payload.get("reason") is None else str(payload["reason"])),
        **{name: bool(payload.get(name, False)) for name in _TRACE_FLAG_FIELDS},
    )


def _is_excluded_from_totals(trace: CalculationTrace) -> bool:
    """Mirror ``ComponentInput.is_excluded_from_aggregates`` for stored lines."""
    return (
        trace.classification == "informational"
        or getattr(trace, "informational", False)
        or getattr(trace, "excluded_from_totals", False)
    )


def _aggregate_from_traces(
    traces: tuple[CalculationTrace, ...],
) -> tuple[Money, Money, Money, Money, Money, Money, Money, Money, Money]:
    earnings: list[Money] = []
    employer_contrib: list[Money] = []
    gross_adj: list[Money] = []
    ag: list[Money] = []
    treasury: list[Money] = []
    external: list[Money] = []

    for trace in traces:
        # Informational / non-bucket classifications are excluded from aggregates.
        if _is_excluded_from_totals(trace):
            continue
        if trace.classification == "earning":
            earnings.append(trace.rounded_value)
        elif trace.classification == "employer_contribution":
            employer_contrib.append(trace.rounded_value)
        elif trace.classification == "gross_adjustment":
            gross_adj.append(trace.rounded_value)
        elif trace.classification == "AG_deduction":
            ag.append(trace.rounded_value)
        elif trace.classification == "treasury_deduction":
            treasury.append(trace.rounded_value)
        elif trace.classification == "external_recovery":
            external.append(trace.rounded_value)

    earnings_total = Money.sum(earnings) if earnings else Money.zero()
    employer_contribution_total = Money.sum(employer_contrib) if employer_contrib else Money.zero()
    gross_adjustment_total = Money.sum(gross_adj) if gross_adj else Money.zero()
    gross_total = earnings_total + employer_contribution_total + gross_adjustment_total
    ag_deduction_total = Money.sum(ag) if ag else Money.zero()
    treasury_deduction_total = Money.sum(treasury) if treasury else Money.zero()
    external_recovery_total = Money.sum(external) if external else Money.zero()
    deductions_total = ag_deduction_total + treasury_deduction_total + external_recovery_total
    net_payable = gross_total - deductions_total
    return (
        earnings_total,
        employer_contribution_total,
        gross_adjustment_total,
        gross_total,
        ag_deduction_total,
        treasury_deduction_total,
        external_recovery_total,
        deductions_total,
        net_payable,
    )


async def _load_run_result(
    db: AsyncSession,
    *,
    organization_id: UUID,
    period: PayrollPeriod,
    version: Any,
) -> RunResult:
    emp_rows = (
        (
            await db.execute(
                sa.select(payroll_employee_results)
                .where(payroll_employee_results.c.organization_id == organization_id)
                .where(payroll_employee_results.c.run_version_id == version["id"])
                .order_by(payroll_employee_results.c.employee_number)
            )
        )
        .mappings()
        .all()
    )

    # One fetch for every employee's lines (was a per-employee query inside the
    # run FOR UPDATE critical section); grouped by employee preserving the
    # per-employee ``sequence`` ordering.
    line_rows = []
    emp_result_ids = [emp["id"] for emp in emp_rows]
    if emp_result_ids:
        line_rows = (
            (
                await db.execute(
                    sa.select(payroll_result_lines)
                    .where(payroll_result_lines.c.organization_id == organization_id)
                    .where(payroll_result_lines.c.employee_result_id.in_(emp_result_ids))
                    .order_by(
                        payroll_result_lines.c.employee_result_id,
                        payroll_result_lines.c.sequence,
                    )
                )
            )
            .mappings()
            .all()
        )
    lines_by_emp: dict[Any, list[Any]] = {}
    for line_row in line_rows:
        lines_by_emp.setdefault(line_row["employee_result_id"], []).append(line_row)

    employees: list[EmployeeResult] = []
    for emp in emp_rows:
        traces = tuple(_trace_from_row(row) for row in lines_by_emp.get(emp["id"], ()))
        (
            earnings_total,
            employer_contribution_total,
            gross_adjustment_total,
            gross_total,
            ag_deduction_total,
            treasury_deduction_total,
            external_recovery_total,
            deductions_total,
            net_payable,
        ) = _aggregate_from_traces(traces)
        employees.append(
            EmployeeResult(
                employee_ref=str(emp["employee_id"]),
                lines=traces,
                earnings_total=earnings_total,
                employer_contribution_total=employer_contribution_total,
                gross_adjustment_total=gross_adjustment_total,
                gross_total=gross_total,
                ag_deduction_total=ag_deduction_total,
                treasury_deduction_total=treasury_deduction_total,
                external_recovery_total=external_recovery_total,
                deductions_total=deductions_total,
                net_payable=net_payable,
                # Off-bill remittance is not derivable from trace lines (the
                # transfer metadata is not part of the hashed trace), so it is
                # read from the persisted snapshot columns.
                offbill_employer_remittance=_money_from_db(emp["offbill_employer_remittance"]),
                disbursement=_money_from_db(emp["disbursement"]),
            )
        )

    employee_tuple = tuple(sorted(employees, key=lambda e: e.employee_ref))
    if employee_tuple:
        run_earnings = Money.sum([e.earnings_total for e in employee_tuple])
        run_employer = Money.sum([e.employer_contribution_total for e in employee_tuple])
        run_gross_adj = Money.sum([e.gross_adjustment_total for e in employee_tuple])
        run_gross = Money.sum([e.gross_total for e in employee_tuple])
        run_ag = Money.sum([e.ag_deduction_total for e in employee_tuple])
        run_treasury = Money.sum([e.treasury_deduction_total for e in employee_tuple])
        run_external = Money.sum([e.external_recovery_total for e in employee_tuple])
        run_deductions = Money.sum([e.deductions_total for e in employee_tuple])
        run_net = Money.sum([e.net_payable for e in employee_tuple])
        run_offbill = Money.sum([e.offbill_employer_remittance for e in employee_tuple])
        run_disbursement = Money.sum([e.disbursement for e in employee_tuple])
    else:
        run_earnings = Money.zero()
        run_employer = Money.zero()
        run_gross_adj = Money.zero()
        run_gross = Money.zero()
        run_ag = Money.zero()
        run_treasury = Money.zero()
        run_external = Money.zero()
        run_deductions = Money.zero()
        run_net = Money.zero()
        run_offbill = Money.zero()
        run_disbursement = Money.zero()

    # Recompute the content hash from the reconstructed lines instead of
    # trusting the stored value; ``post_run`` compares it against the persisted
    # ``content_hash`` before any posting side-effect.
    recomputed_hash = content_hash_for(
        period=_period_label(period.period_year, period.period_month),
        org_ref=str(organization_id),
        engine_version=str(version["engine_version"]),
        employees=employee_tuple,
        earnings_total=run_earnings,
        employer_contribution_total=run_employer,
        gross_adjustment_total=run_gross_adj,
        gross_total=run_gross,
        ag_deduction_total=run_ag,
        treasury_deduction_total=run_treasury,
        external_recovery_total=run_external,
        deductions_total=run_deductions,
        net_payable=run_net,
        offbill_employer_remittance=run_offbill,
        disbursement=run_disbursement,
    )

    return RunResult(
        period=_period_label(period.period_year, period.period_month),
        org_ref=str(organization_id),
        engine_version=version["engine_version"],
        employees=employee_tuple,
        earnings_total=run_earnings,
        employer_contribution_total=run_employer,
        gross_adjustment_total=run_gross_adj,
        gross_total=run_gross,
        ag_deduction_total=run_ag,
        treasury_deduction_total=run_treasury,
        external_recovery_total=run_external,
        deductions_total=run_deductions,
        net_payable=run_net,
        offbill_employer_remittance=run_offbill,
        disbursement=run_disbursement,
        content_hash=recomputed_hash,
    )


def _run_summary(run: PayrollRun, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(run.id),
        "period_id": str(run.period_id),
        "status": run.status,
        "current_version_id": (
            None if run.current_version_id is None else str(run.current_version_id)
        ),
        "lock_version": run.lock_version,
        "original_run_id": (None if run.original_run_id is None else str(run.original_run_id)),
    }
    if extra:
        payload.update(extra)
    return payload


async def post_run(
    db: AsyncSession,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Post an approved run: lock, recheck, then approval+audit+outbox+status."""
    stmt = (
        sa.select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .where(PayrollRun.organization_id == organization_id)
        .with_for_update()
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found.")
    if run.status != "approved":
        raise ConflictError(
            f"Payroll run cannot be posted from status {run.status!r}; status must be approved."
        )
    if run.current_version_id is None:
        raise ConflictError("Payroll run has no current_version_id to post.")

    version = (
        (
            await db.execute(
                sa.select(payroll_run_versions).where(
                    payroll_run_versions.c.id == run.current_version_id,
                    payroll_run_versions.c.organization_id == organization_id,
                    payroll_run_versions.c.run_id == run.id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise ConflictError("Current run version not found.")

    # Recheck under lock: latest approve must bind current version + content hash.
    approval = (
        await db.execute(
            sa.select(PayrollApproval)
            .where(PayrollApproval.organization_id == organization_id)
            .where(PayrollApproval.run_id == run.id)
            .where(PayrollApproval.action == "approve")
            .order_by(PayrollApproval.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if approval is None:
        raise ConflictError("Payroll run has no approve action to post against.")
    if (
        approval.run_version_id != run.current_version_id
        or approval.content_hash != version["content_hash"]
    ):
        raise ConflictError(
            "Approval binding is stale relative to the current run version/content hash."
        )

    period = await db.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != organization_id:
        raise NotFoundError("Payroll period not found.")
    if period.status != "open":
        raise ConflictError(f"Payroll period status must be open to post; found {period.status!r}.")

    result = await _load_run_result(
        db,
        organization_id=organization_id,
        period=period,
        version=version,
    )
    if result.content_hash != version["content_hash"]:
        # Recomputed hash disagrees with the persisted digest: the immutable
        # version rows were tampered with (or predate the canonical shape).
        stale = ConflictError(
            "Persisted run version content_hash does not match the reconstructed result."
        )
        stale.error_code = URN_STALE_VERSION
        raise stale
    findings = validate_run_result(result)
    if has_blocking(findings):
        raise ConflictError("Payroll run result has blocking validation findings.")

    totals = version["totals"]
    content_hash = version["content_hash"]
    version_id = version["id"]
    now = datetime.now(timezone.utc)

    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")
    inputs_snapshot = version["inputs_snapshot"] or {}
    component_catalog = inputs_snapshot.get("component_catalog")
    employee_identity = inputs_snapshot.get("employee_identity")
    report_profile = inputs_snapshot.get("report_profile")
    recovery_sources = inputs_snapshot.get("recovery_sources")
    if (
        not isinstance(component_catalog, list)
        or not isinstance(employee_identity, dict)
        or not isinstance(report_profile, dict)
        or not isinstance(recovery_sources, dict)
    ):
        raise ConflictError(
            "Payroll run was calculated before immutable report snapshots were supported. "
            "Recalculate and approve the run again before posting.",
            details={"error_code": "report_snapshot_inputs_missing"},
        )
    report_metadata = PayrollRunReportMetadata.model_validate(run.report_metadata or {})
    report_snapshot = {
        "component_catalog": list(component_catalog),
        "employee_identity": dict(employee_identity),
        "organization": {"id": str(organization.id), "name": organization.name},
        "report_profile": report_profile,
        "recovery_sources": recovery_sources,
        "run_metadata": report_metadata.model_dump(mode="json"),
    }
    report_snapshot_json = json.dumps(
        report_snapshot,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    source_checksum = hashlib.sha256(report_snapshot_json.encode("utf-8")).hexdigest()

    # uq_payroll_report_snapshots_org_run_version means a pre-existing row
    # (e.g. a workbook/current-master backfill, or a concurrent post) would
    # otherwise brick posting with a 500 on every retry. Adopt an identical
    # row; conflict on divergent contents.
    existing_snapshot = (
        (
            await db.execute(
                sa.select(
                    payroll_report_snapshots.c.source_checksum,
                    payroll_report_snapshots.c.provenance,
                ).where(
                    payroll_report_snapshots.c.organization_id == organization_id,
                    payroll_report_snapshots.c.run_version_id == version_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing_snapshot is None:
        try:
            async with db.begin_nested():
                await db.execute(
                    sa.insert(payroll_report_snapshots).values(
                        organization_id=organization_id,
                        run_version_id=version_id,
                        snapshot=report_snapshot,
                        provenance="posting",
                        source_checksum=source_checksum,
                        created_by=user_id,
                    )
                )
        except IntegrityError as exc:
            if not integrity_is(exc, UniqueViolationError):
                raise
            # Lost the insert race — the savepoint rolled back; re-select the
            # winning row and let the checksum comparison below decide.
            existing_snapshot = (
                (
                    await db.execute(
                        sa.select(
                            payroll_report_snapshots.c.source_checksum,
                            payroll_report_snapshots.c.provenance,
                        ).where(
                            payroll_report_snapshots.c.organization_id == organization_id,
                            payroll_report_snapshots.c.run_version_id == version_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
    if existing_snapshot is not None and existing_snapshot["source_checksum"] != source_checksum:
        raise ConflictError(
            "A payroll report snapshot already exists for this run version with "
            "different contents.",
            details={
                "error_code": "report_snapshot_conflict",
                "provenance": existing_snapshot["provenance"],
            },
        )

    db.add(
        PayrollApproval(
            organization_id=organization_id,
            run_id=run.id,
            run_version_id=version_id,
            content_hash=content_hash,
            action="post",
            actor_user_id=user_id,
        )
    )
    db.add(
        OutboxEvent(
            organization_id=organization_id,
            event_type="payroll_run.posted",
            payload={
                "organization_id": str(organization_id),
                "run_id": str(run.id),
                "run_version_id": str(version_id),
                "content_hash": content_hash,
                "totals": totals,
            },
        )
    )

    before_state = entity_snapshot(run)
    run.status = "posted"
    run.lock_version = run.lock_version + 1
    run.updated_at = now
    await db.flush()
    await write_mutation_event(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        command="payroll_run.post",
        entity_type="payroll_run",
        entity_id=run.id,
        entity_label=f"{_period_label(period.period_year, period.period_month)} payroll run",
        before_state=before_state,
        after_state=entity_snapshot(run),
        summary={
            "status": "posted",
            "run_version_id": str(version_id),
            "content_hash": content_hash,
            "totals": totals,
        },
        idempotency_key=idempotency_key,
    )
    await db.commit()

    return _run_summary(run)


async def reverse_run(
    db: AsyncSession,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    reason: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Reverse a posted run with a linked draft counter-record (snapshot intact)."""
    if reason is None or not str(reason).strip():
        raise ValidationError("reason is required to reverse a payroll run.")

    stmt = (
        sa.select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .where(PayrollRun.organization_id == organization_id)
        .with_for_update()
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found.")
    if run.status != "posted":
        raise ConflictError(
            f"Payroll run cannot be reversed from status {run.status!r}; status must be posted."
        )
    if run.current_version_id is None:
        raise ConflictError("Posted payroll run has no current_version_id.")

    version = (
        (
            await db.execute(
                sa.select(payroll_run_versions).where(
                    payroll_run_versions.c.id == run.current_version_id,
                    payroll_run_versions.c.organization_id == organization_id,
                    payroll_run_versions.c.run_id == run.id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise ConflictError("Current run version not found.")

    now = datetime.now(timezone.utc)
    before_state = entity_snapshot(run)
    reversal = PayrollRun(
        id=uuid4(),
        organization_id=organization_id,
        period_id=run.period_id,
        original_run_id=run.id,
        status="draft",
        current_version_id=None,
        lock_version=0,
    )
    db.add(reversal)

    run.status = "reversed"
    run.lock_version = run.lock_version + 1
    run.updated_at = now

    content_hash = version["content_hash"]
    version_id = version["id"]
    trimmed_reason = str(reason).strip()

    db.add(
        PayrollApproval(
            organization_id=organization_id,
            run_id=run.id,
            run_version_id=version_id,
            content_hash=content_hash,
            action="reverse",
            actor_user_id=user_id,
            reason=trimmed_reason,
        )
    )
    db.add(
        OutboxEvent(
            organization_id=organization_id,
            event_type="payroll_run.reversed",
            payload={
                "organization_id": str(organization_id),
                "run_id": str(run.id),
                "run_version_id": str(version_id),
                "content_hash": content_hash,
                "reversal_run_id": str(reversal.id),
                "reason": trimmed_reason,
            },
        )
    )

    await db.flush()
    period = await db.get(PayrollPeriod, run.period_id)
    period_label = (
        _period_label(period.period_year, period.period_month) if period is not None else "Unknown"
    )
    await write_mutation_event(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        command="payroll_run.reverse",
        entity_type="payroll_run",
        entity_id=run.id,
        entity_label=f"{period_label} payroll run",
        before_state=before_state,
        after_state=entity_snapshot(run),
        summary={
            "status": "reversed",
            "run_version_id": str(version_id),
            "content_hash": content_hash,
            "reversal_run_id": str(reversal.id),
            "reason": trimmed_reason,
        },
        metadata={"reversal_run_id": str(reversal.id), "reason": trimmed_reason},
        idempotency_key=idempotency_key,
    )
    await db.commit()

    return _run_summary(run, extra={"reversal_run_id": str(reversal.id)})
