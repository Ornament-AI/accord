"""Payroll run workflow commands: validate / submit / withdraw / approve / reject / reopen.

ADR 0008 transition matrix adapted to persisted statuses
(``draft|calculating|calculated|submitted|approved|rejected|posted|reversed``):
there is no separate ``validated`` / ``withdrawn`` status — validate is a read
against ``calculated``, withdraw returns ``submitted`` → ``calculated``, and
reopen returns ``calculated``|``rejected`` → ``draft`` so the same run can be
corrected (run versions stay append-only; no ``original_run_id`` supersession).

Editing draft inputs after submit is invalidated in the payroll_runs input
service (NOT this module); here the content_hash binding at submit/approve
makes stale approvals impossible.

Post / reverse belong to a parallel lane and are not implemented here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.results import RunResult
from app.domain.payroll.validation import (
    ValidationFinding,
    has_blocking,
    validate_run_result,
)
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.identity import OrganizationMembership
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_run_versions,
)
from app.models.platform import PayrollApproval
from app.services.audit_events import entity_snapshot, write_mutation_event
from app.services.run_reconstruction import load_run_result

# Problem-detail ``error`` URNs for workflow conflicts (ADR 0008 HTTP mapping).
URN_ILLEGAL_TRANSITION = "urn:accord:workflow:illegal_transition"
URN_MAKER_CHECKER = "urn:accord:workflow:maker_checker"
URN_STALE_VERSION = "urn:accord:workflow:stale_version"
URN_BLOCKING_VALIDATION = "urn:accord:workflow:blocking_validation"
URN_WITHDRAW_FORBIDDEN = "urn:accord:workflow:withdraw_forbidden"


def _conflict(message: str, *, error_code: str, details: dict | None = None) -> ConflictError:
    err = ConflictError(message, details)
    err.error_code = error_code
    return err


def _forbidden(message: str, *, error_code: str) -> ForbiddenError:
    err = ForbiddenError(message)
    err.error_code = error_code
    return err


def _finding_dict(finding: ValidationFinding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "employee_ref": finding.employee_ref,
        "component_code": finding.component_code,
        "message": finding.message,
        "context": dict(finding.context),
    }


async def _lock_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> PayrollRun:
    stmt = (
        sa.select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .where(PayrollRun.organization_id == organization_id)
        .with_for_update()
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found.")
    return run


async def _load_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    version_id: UUID,
) -> Any:
    stmt = sa.select(payroll_run_versions).where(
        payroll_run_versions.c.id == version_id,
        payroll_run_versions.c.organization_id == organization_id,
    )
    row = (await db.execute(stmt)).mappings().one_or_none()
    if row is None:
        raise NotFoundError("Payroll run version not found.")
    return row


async def _reconstruct_run_result(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run: PayrollRun,
    version: Any,
) -> RunResult:
    period = await db.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != organization_id:
        raise NotFoundError("Payroll period not found.")
    return await load_run_result(
        db, organization_id=organization_id, period=period, version=version
    )


async def _run_summary(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run: PayrollRun,
) -> dict[str, Any]:
    version_number: int | None = None
    content_hash: str | None = None
    if run.current_version_id is not None:
        version = await _load_version(
            db,
            organization_id=organization_id,
            version_id=run.current_version_id,
        )
        version_number = int(version["version_number"])
        content_hash = str(version["content_hash"])
    return {
        "id": str(run.id),
        "status": run.status,
        "current_version_number": version_number,
        "content_hash": content_hash,
    }


async def _compute_findings(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run: PayrollRun,
) -> tuple[tuple[ValidationFinding, ...], bool, Any]:
    if run.current_version_id is None:
        raise _conflict(
            "Payroll run has no current calculated version.",
            error_code=URN_ILLEGAL_TRANSITION,
        )
    version = await _load_version(
        db,
        organization_id=organization_id,
        version_id=run.current_version_id,
    )
    result = await _reconstruct_run_result(
        db,
        organization_id=organization_id,
        run=run,
        version=version,
    )
    findings = validate_run_result(result)
    # Integrity: the hash recomputed from stored lines must equal the persisted
    # content_hash — a mismatch means the immutable version was tampered with.
    if result.content_hash != str(version["content_hash"]):
        raise _conflict(
            "Persisted run version content_hash is inconsistent.",
            error_code=URN_STALE_VERSION,
        )
    return findings, has_blocking(findings), version


async def _latest_submit_approval(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> PayrollApproval | None:
    stmt = (
        sa.select(PayrollApproval)
        .where(
            PayrollApproval.organization_id == organization_id,
            PayrollApproval.run_id == run_id,
            PayrollApproval.action == "submit",
        )
        .order_by(PayrollApproval.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _is_org_admin(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> bool:
    stmt = sa.select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.is_active.is_(True),
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    return membership is not None and membership.role == "organization_administrator"


async def _write_approval_and_audit(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run: PayrollRun,
    user_id: UUID,
    action: str,
    from_status: str,
    to_status: str,
    version: Any,
    reason: str | None,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    idempotency_key: str | None,
) -> None:
    db.add(
        PayrollApproval(
            organization_id=organization_id,
            run_id=run.id,
            run_version_id=version["id"],
            content_hash=str(version["content_hash"]),
            action=action,
            actor_user_id=user_id,
            reason=reason,
        )
    )
    period = await db.get(PayrollPeriod, run.period_id)
    period_label = (
        f"{period.period_year:04d}-{period.period_month:02d}" if period is not None else "Unknown"
    )
    await write_mutation_event(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        command=action,
        entity_type="payroll_run",
        entity_id=run.id,
        entity_label=f"{period_label} payroll run",
        before_state=before_state,
        after_state=after_state,
        summary={
            "from_status": from_status,
            "to_status": to_status,
            "run_version_id": str(version["id"]),
            "version_number": int(version["version_number"]),
            "content_hash": str(version["content_hash"]),
        },
        metadata={"reason": reason} if reason else {},
        idempotency_key=idempotency_key,
    )


async def _transition(
    db: AsyncSession,
    *,
    run: PayrollRun,
    to_status: str,
) -> None:
    run.status = to_status
    run.lock_version = run.lock_version + 1
    run.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def validate_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> dict[str, Any]:
    """Read-only validation against the current calculated version.

    No status change, no PayrollApproval row, and no AuditEvent (it is a read).
    """
    stmt = sa.select(PayrollRun).where(
        PayrollRun.id == run_id,
        PayrollRun.organization_id == organization_id,
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found.")
    if run.status != "calculated":
        raise _conflict(
            f"Payroll run cannot be validated from status {run.status!r}; "
            "required status is calculated.",
            error_code=URN_ILLEGAL_TRANSITION,
            details={"from_status": run.status, "command": "validate"},
        )

    findings, blocking, _version = await _compute_findings(
        db,
        organization_id=organization_id,
        run=run,
    )
    summary = await _run_summary(db, organization_id=organization_id, run=run)
    return {
        **summary,
        "findings": [_finding_dict(f) for f in findings],
        "blocking": blocking,
    }


async def submit_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """calculated → submitted; bind current version + content_hash."""
    run = await _lock_run(db, organization_id=organization_id, run_id=run_id)
    if run.status != "calculated":
        raise _conflict(
            f"Payroll run cannot be submitted from status {run.status!r}; "
            "required status is calculated.",
            error_code=URN_ILLEGAL_TRANSITION,
            details={"from_status": run.status, "command": "submit"},
        )
    if run.current_version_id is None:
        raise _conflict(
            "Payroll run cannot be submitted without a current calculated version.",
            error_code=URN_ILLEGAL_TRANSITION,
        )

    findings, blocking, version = await _compute_findings(
        db,
        organization_id=organization_id,
        run=run,
    )
    if blocking:
        raise _conflict(
            "Payroll run has blocking validation findings and cannot be submitted.",
            error_code=URN_BLOCKING_VALIDATION,
            details={"findings": [_finding_dict(f) for f in findings]},
        )

    from_status = run.status
    before_state = entity_snapshot(run)
    await _transition(db, run=run, to_status="submitted")
    await _write_approval_and_audit(
        db,
        organization_id=organization_id,
        run=run,
        user_id=user_id,
        action="submit",
        from_status=from_status,
        to_status="submitted",
        version=version,
        reason=reason,
        before_state=before_state,
        after_state=entity_snapshot(run),
        idempotency_key=idempotency_key,
    )
    summary = await _run_summary(db, organization_id=organization_id, run=run)
    await db.commit()
    return summary


async def withdraw_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """submitted → calculated; original submitter or organization_administrator."""
    run = await _lock_run(db, organization_id=organization_id, run_id=run_id)
    if run.status != "submitted":
        raise _conflict(
            f"Payroll run cannot be withdrawn from status {run.status!r}; "
            "required status is submitted.",
            error_code=URN_ILLEGAL_TRANSITION,
            details={"from_status": run.status, "command": "withdraw"},
        )
    if run.current_version_id is None:
        raise _conflict(
            "Payroll run cannot be withdrawn without a current calculated version.",
            error_code=URN_ILLEGAL_TRANSITION,
        )

    submit_approval = await _latest_submit_approval(
        db,
        organization_id=organization_id,
        run_id=run.id,
    )
    if submit_approval is None:
        raise _conflict(
            "Payroll run has no submit approval to withdraw.",
            error_code=URN_ILLEGAL_TRANSITION,
        )

    is_submitter = submit_approval.actor_user_id == user_id
    is_admin = await _is_org_admin(
        db,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not is_submitter and not is_admin:
        raise _forbidden(
            "Only the original submitter or an organization_administrator may withdraw.",
            error_code=URN_WITHDRAW_FORBIDDEN,
        )

    version = await _load_version(
        db,
        organization_id=organization_id,
        version_id=run.current_version_id,
    )
    from_status = run.status
    before_state = entity_snapshot(run)
    await _transition(db, run=run, to_status="calculated")
    await _write_approval_and_audit(
        db,
        organization_id=organization_id,
        run=run,
        user_id=user_id,
        action="withdraw",
        from_status=from_status,
        to_status="calculated",
        version=version,
        reason=reason,
        before_state=before_state,
        after_state=entity_snapshot(run),
        idempotency_key=idempotency_key,
    )
    summary = await _run_summary(db, organization_id=organization_id, run=run)
    await db.commit()
    return summary


async def approve_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """submitted → approved; maker/checker + stale-version guard."""
    run = await _lock_run(db, organization_id=organization_id, run_id=run_id)
    if run.status != "submitted":
        raise _conflict(
            f"Payroll run cannot be approved from status {run.status!r}; "
            "required status is submitted.",
            error_code=URN_ILLEGAL_TRANSITION,
            details={"from_status": run.status, "command": "approve"},
        )
    if run.current_version_id is None:
        raise _conflict(
            "Payroll run cannot be approved without a current calculated version.",
            error_code=URN_ILLEGAL_TRANSITION,
        )

    submit_approval = await _latest_submit_approval(
        db,
        organization_id=organization_id,
        run_id=run.id,
    )
    if submit_approval is None:
        raise _conflict(
            "Payroll run has no submit approval to approve against.",
            error_code=URN_ILLEGAL_TRANSITION,
        )
    if submit_approval.actor_user_id == user_id:
        raise _conflict(
            "Maker/checker separation: the submitter cannot approve their own submission.",
            error_code=URN_MAKER_CHECKER,
        )

    version = await _load_version(
        db,
        organization_id=organization_id,
        version_id=run.current_version_id,
    )
    if submit_approval.run_version_id != version["id"] or submit_approval.content_hash != str(
        version["content_hash"]
    ):
        raise _conflict(
            "Submitted version/content_hash does not match the current run version "
            "(stale version).",
            error_code=URN_STALE_VERSION,
            details={
                "submitted_run_version_id": str(submit_approval.run_version_id),
                "submitted_content_hash": submit_approval.content_hash,
                "current_run_version_id": str(version["id"]),
                "current_content_hash": str(version["content_hash"]),
            },
        )

    from_status = run.status
    before_state = entity_snapshot(run)
    await _transition(db, run=run, to_status="approved")
    await _write_approval_and_audit(
        db,
        organization_id=organization_id,
        run=run,
        user_id=user_id,
        action="approve",
        from_status=from_status,
        to_status="approved",
        version=version,
        reason=reason,
        before_state=before_state,
        after_state=entity_snapshot(run),
        idempotency_key=idempotency_key,
    )
    summary = await _run_summary(db, organization_id=organization_id, run=run)
    await db.commit()
    return summary


async def reopen_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """calculated|rejected → draft; reopen the same run for correction.

    Unlike withdraw there is no submitter check: reopen is a draft-state
    recovery available to any caller holding the route's ``create_run``
    capability. No new run_version is created; ``current_version_id`` keeps
    pointing at the last calculated version until the next calculate.
    """
    run = await _lock_run(db, organization_id=organization_id, run_id=run_id)
    if run.status not in {"calculated", "rejected"}:
        raise _conflict(
            f"Payroll run cannot be reopened from status {run.status!r}; "
            "required status is calculated or rejected.",
            error_code=URN_ILLEGAL_TRANSITION,
            details={"from_status": run.status, "command": "reopen"},
        )
    if run.current_version_id is None:
        raise _conflict(
            "Payroll run cannot be reopened without a current calculated version.",
            error_code=URN_ILLEGAL_TRANSITION,
        )

    version = await _load_version(
        db,
        organization_id=organization_id,
        version_id=run.current_version_id,
    )
    from_status = run.status
    before_state = entity_snapshot(run)
    await _transition(db, run=run, to_status="draft")
    await _write_approval_and_audit(
        db,
        organization_id=organization_id,
        run=run,
        user_id=user_id,
        action="reopen",
        from_status=from_status,
        to_status="draft",
        version=version,
        reason=reason,
        before_state=before_state,
        after_state=entity_snapshot(run),
        idempotency_key=idempotency_key,
    )
    summary = await _run_summary(db, organization_id=organization_id, run=run)
    await db.commit()
    return summary


async def reject_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """submitted → rejected; approver ≠ submitter (same SoD as approve).

    ``rejected`` is reopenable: ``reopen_run`` returns the same run to
    ``draft`` for correction and resubmission.
    """
    run = await _lock_run(db, organization_id=organization_id, run_id=run_id)
    if run.status != "submitted":
        raise _conflict(
            f"Payroll run cannot be rejected from status {run.status!r}; "
            "required status is submitted.",
            error_code=URN_ILLEGAL_TRANSITION,
            details={"from_status": run.status, "command": "reject"},
        )
    if run.current_version_id is None:
        raise _conflict(
            "Payroll run cannot be rejected without a current calculated version.",
            error_code=URN_ILLEGAL_TRANSITION,
        )

    submit_approval = await _latest_submit_approval(
        db,
        organization_id=organization_id,
        run_id=run.id,
    )
    if submit_approval is None:
        raise _conflict(
            "Payroll run has no submit approval to reject against.",
            error_code=URN_ILLEGAL_TRANSITION,
        )
    if submit_approval.actor_user_id == user_id:
        raise _conflict(
            "Maker/checker separation: the submitter cannot reject their own submission.",
            error_code=URN_MAKER_CHECKER,
        )

    version = await _load_version(
        db,
        organization_id=organization_id,
        version_id=run.current_version_id,
    )
    from_status = run.status
    before_state = entity_snapshot(run)
    await _transition(db, run=run, to_status="rejected")
    await _write_approval_and_audit(
        db,
        organization_id=organization_id,
        run=run,
        user_id=user_id,
        action="reject",
        from_status=from_status,
        to_status="rejected",
        version=version,
        reason=reason,
        before_state=before_state,
        after_state=entity_snapshot(run),
        idempotency_key=idempotency_key,
    )
    summary = await _run_summary(db, organization_id=organization_id, run=run)
    await db.commit()
    return summary
