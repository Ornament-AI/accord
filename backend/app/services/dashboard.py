"""Payroll dashboard summary service (tenant-scoped aggregates)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.money import Money
from app.models.effective import effective_on
from app.models.employees import employee_profile_versions
from app.models.payroll_runs import PayrollPeriod, PayrollRun, payroll_run_versions
from app.models.platform import ExportArtifact, PayrollApproval

# Pipeline response omits ``calculating`` intentionally — those rows are not
# rolled into another status bucket.
_PIPELINE_STATUSES = (
    "draft",
    "calculated",
    "submitted",
    "approved",
    "posted",
    "rejected",
    "reversed",
)

_ZERO_PIPELINE = {status: 0 for status in _PIPELINE_STATUSES}
_ZERO_REGIME = {"gpf": 0, "nps": 0, "epf": 0}


def _money_canonical(value: Any) -> str:
    if value is None or value == "":
        return Money.zero().to_canonical_str()
    return Money.from_decimal(Decimal(str(value))).to_canonical_str()


def _money_delta(left: str, right: str) -> str:
    return Money.from_decimal(Decimal(left) - Decimal(right)).to_canonical_str()


def _map_totals(totals: dict[str, Any] | None) -> dict[str, str]:
    raw = totals or {}
    return {
        "earnings": _money_canonical(raw.get("earnings_total")),
        "employer_contribution": _money_canonical(raw.get("employer_contribution_total")),
        "gross": _money_canonical(raw.get("gross_total")),
        "deductions": _money_canonical(raw.get("deductions_total")),
        "net": _money_canonical(raw.get("net_payable")),
    }


async def _headcount(db: AsyncSession, *, organization_id: UUID) -> dict[str, Any]:
    today = date.today()
    stmt = (
        sa.select(
            employee_profile_versions.c.retirement_regime,
            sa.func.count().label("count"),
        )
        .where(
            employee_profile_versions.c.organization_id == organization_id,
            effective_on(employee_profile_versions.c.validity, today),
        )
        .group_by(employee_profile_versions.c.retirement_regime)
    )
    by_regime = dict(_ZERO_REGIME)
    total = 0
    for regime, count in (await db.execute(stmt)).all():
        key = str(regime)
        if key in by_regime:
            by_regime[key] = int(count)
            total += int(count)
    return {"active_employees": total, "by_regime": by_regime}


async def _current_period(db: AsyncSession, *, organization_id: UUID) -> dict[str, Any] | None:
    period = (
        await db.execute(
            sa.select(PayrollPeriod)
            .where(PayrollPeriod.organization_id == organization_id)
            .order_by(PayrollPeriod.period_year.desc(), PayrollPeriod.period_month.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if period is None:
        return None

    run = (
        await db.execute(
            sa.select(PayrollRun)
            .where(
                PayrollRun.organization_id == organization_id,
                PayrollRun.period_id == period.id,
                PayrollRun.run_type == "regular",
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    run_payload: dict[str, Any] | None = None
    if run is not None:
        version_number: int | None = None
        if run.current_version_id is not None:
            version_number = (
                await db.execute(
                    sa.select(payroll_run_versions.c.version_number).where(
                        payroll_run_versions.c.id == run.current_version_id,
                        payroll_run_versions.c.organization_id == organization_id,
                    )
                )
            ).scalar_one_or_none()
            if version_number is not None:
                version_number = int(version_number)
        run_payload = {
            "id": run.id,
            "status": run.status,
            "version_number": version_number,
        }

    return {
        "year": int(period.period_year),
        "month": int(period.period_month),
        "run": run_payload,
    }


async def _posted_runs(
    db: AsyncSession, *, organization_id: UUID, limit: int = 2
) -> list[dict[str, Any]]:
    post_times = (
        sa.select(
            PayrollApproval.run_id.label("run_id"),
            sa.func.max(PayrollApproval.created_at).label("posted_at"),
        )
        .where(
            PayrollApproval.organization_id == organization_id,
            PayrollApproval.action == "post",
        )
        .group_by(PayrollApproval.run_id)
    ).subquery()

    stmt = (
        sa.select(
            PayrollRun.id.label("run_id"),
            PayrollPeriod.period_year,
            PayrollPeriod.period_month,
            payroll_run_versions.c.totals,
            post_times.c.posted_at,
        )
        .join(PayrollPeriod, PayrollPeriod.id == PayrollRun.period_id)
        .join(post_times, post_times.c.run_id == PayrollRun.id)
        .outerjoin(
            payroll_run_versions,
            sa.and_(
                payroll_run_versions.c.id == PayrollRun.current_version_id,
                payroll_run_versions.c.organization_id == organization_id,
            ),
        )
        .where(
            PayrollRun.organization_id == organization_id,
            PayrollRun.status == "posted",
            PayrollPeriod.organization_id == organization_id,
        )
        .order_by(PayrollPeriod.period_year.desc(), PayrollPeriod.period_month.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).mappings().all()
    return [
        {
            "run_id": row["run_id"],
            "period": {"year": int(row["period_year"]), "month": int(row["period_month"])},
            "totals": _map_totals(row["totals"]),
            "posted_at": row["posted_at"],
        }
        for row in rows
    ]


async def _pipeline(db: AsyncSession, *, organization_id: UUID) -> dict[str, int]:
    stmt = (
        sa.select(PayrollRun.status, sa.func.count().label("count"))
        .where(PayrollRun.organization_id == organization_id)
        .group_by(PayrollRun.status)
    )
    counts = dict(_ZERO_PIPELINE)
    for status, count in (await db.execute(stmt)).all():
        key = str(status)
        if key in counts:
            counts[key] = int(count)
    return counts


async def _recent_artifacts(db: AsyncSession, *, organization_id: UUID) -> list[dict[str, Any]]:
    stmt = (
        sa.select(
            ExportArtifact.id,
            ExportArtifact.report_type,
            ExportArtifact.created_at,
        )
        .where(
            ExportArtifact.organization_id == organization_id,
            ExportArtifact.status == "finalized",
        )
        .order_by(ExportArtifact.created_at.desc())
        .limit(5)
    )
    return [
        {
            "id": row.id,
            "report_type": row.report_type,
            "created_at": row.created_at,
        }
        for row in (await db.execute(stmt)).all()
    ]


async def get_dashboard_summary(db: AsyncSession, *, organization_id: UUID) -> dict[str, Any]:
    """Return the payroll dashboard summary for one organization."""
    headcount = await _headcount(db, organization_id=organization_id)
    current_period = await _current_period(db, organization_id=organization_id)
    posted = await _posted_runs(db, organization_id=organization_id, limit=2)
    latest_posted = posted[0] if posted else None
    previous_posted = posted[1] if len(posted) > 1 else None

    variance: dict[str, str] | None = None
    if latest_posted is not None and previous_posted is not None:
        variance = {
            "gross_delta": _money_delta(
                latest_posted["totals"]["gross"],
                previous_posted["totals"]["gross"],
            ),
            "net_delta": _money_delta(
                latest_posted["totals"]["net"],
                previous_posted["totals"]["net"],
            ),
        }

    return {
        "headcount": headcount,
        "current_period": current_period,
        "latest_posted": latest_posted,
        "previous_posted": previous_posted,
        "variance": variance,
        "pipeline": await _pipeline(db, organization_id=organization_id),
        "recent_artifacts": await _recent_artifacts(db, organization_id=organization_id),
    }
