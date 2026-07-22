"""Office approval note report family.

Maker/checker approval note with signatory blocks for office endorsement of a
posted bill. Totals come from the posted run version; amount-in-words are
generated programmatically from those numeric DTO values (never stored strings).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.identity import User
from app.models.payroll_runs import (
    payroll_employee_results,
)
from app.models.platform import PayrollApproval
from app.models.reports import ReportConfiguration
from app.reports.amount_in_words import amount_in_words
from app.reports.base import (
    ColumnKind,
    ReportColumn,
    ReportContext,
    ReportDTO,
    ReportRegistry,
    TableSection,
    to_json as base_to_json,
)
from app.reports.excel import to_excel as base_to_excel
from app.reports.formatting import format_inr
from app.reports.pdf import to_pdf as base_to_pdf
from app.reports.snapshots import load_report_snapshot
from app.reports.posted_run import (
    DEFAULT_CONTENT_TYPES,
    DEFAULT_FILENAME_PATTERN,
    ZERO,
    load_result_rows,
    money,
    period_label,
    require_posted_run,
)
from app.services.run_workflow import URN_MAKER_CHECKER

# Report type string for orchestrator / registry registration.
REPORT_TYPE_APPROVAL_NOTE = "approval_note"

ApprovalNoteDTO = ReportDTO


_SIGNATORY_SLOTS: tuple[str, ...] = ("maker", "checker", "approving_officer")
_PLACEHOLDER_NAME = "____________________"

FILENAME_PATTERN = DEFAULT_FILENAME_PATTERN


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        return value.isoformat()
    return value.isoformat()


async def _load_headcount(
    session: AsyncSession,
    *,
    organization_id: UUID,
    run_version_id: UUID,
) -> int:
    return int(
        (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(payroll_employee_results)
                .where(
                    payroll_employee_results.c.organization_id == organization_id,
                    payroll_employee_results.c.run_version_id == run_version_id,
                )
            )
        ).scalar_one()
    )


async def _load_workflow_evidence(
    session: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> dict[str, tuple[str, datetime]]:
    """Return action → (actor display name, created_at) for submit/approve/post."""
    rows = (
        await session.execute(
            sa.select(PayrollApproval, User)
            .join(User, User.id == PayrollApproval.actor_user_id)
            .where(
                PayrollApproval.organization_id == organization_id,
                PayrollApproval.run_id == run_id,
                PayrollApproval.action.in_(("submit", "approve", "post")),
            )
            .order_by(PayrollApproval.created_at.asc())
        )
    ).all()

    # Latest event per action (re-submit after withdraw keeps the latest submit).
    by_action: dict[str, tuple[str, datetime, UUID]] = {}
    for approval, user in rows:
        by_action[approval.action] = (user.name, approval.created_at, approval.actor_user_id)

    submit = by_action.get("submit")
    approve = by_action.get("approve")
    if submit is not None and approve is not None and submit[2] == approve[2]:
        err = ConflictError(
            "Approver must be distinct from submitter (maker/checker).",
            details={
                "submitter_user_id": str(submit[2]),
                "approver_user_id": str(approve[2]),
            },
        )
        err.error_code = URN_MAKER_CHECKER
        raise err

    out: dict[str, tuple[str, datetime]] = {}
    for action, packed in by_action.items():
        out[action] = (packed[0], packed[1])
    return out


def _signatory_placeholder(slot: str) -> tuple[str, str]:
    return (_PLACEHOLDER_NAME, slot)


async def _load_signatories(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> tuple[tuple[str, str, str], ...]:
    """Return (slot, name, designation/role) for maker / checker / approving_officer.

    Absent or partial ``report_configurations`` key ``signatories`` yields
    placeholder underscore names with the slot role label — never an error.
    """
    row = (
        await session.execute(
            sa.select(ReportConfiguration).where(
                ReportConfiguration.organization_id == organization_id,
                ReportConfiguration.key == "signatories",
            )
        )
    ).scalar_one_or_none()

    config: dict[str, Any] = {}
    if row is not None and isinstance(row.value, dict):
        config = row.value

    out: list[tuple[str, str, str]] = []
    for slot in _SIGNATORY_SLOTS:
        raw = config.get(slot)
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
            designation = str(raw.get("designation") or raw.get("role") or slot).strip() or slot
            if not name:
                name, designation = _signatory_placeholder(slot)
            out.append((slot, name, designation))
        else:
            name, designation = _signatory_placeholder(slot)
            out.append((slot, name, designation))
    return tuple(out)


def _totals_from_version(version: Any) -> tuple[Decimal, Decimal, Decimal]:
    totals = version["totals"] or {}
    gross = money(totals.get("gross_total", ZERO))
    deductions = money(totals.get("deductions_total", ZERO))
    net = money(totals.get("net_payable", ZERO))
    return gross, deductions, net


class ApprovalNoteBuilder:
    """Build the office approval note DTO from a posted run snapshot."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> ApprovalNoteDTO:
        run, version, period, org = await require_posted_run(session, ctx)
        gross, deductions, net = _totals_from_version(version)
        headcount = await _load_headcount(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        evidence = await _load_workflow_evidence(
            session,
            organization_id=ctx.organization_id,
            run_id=run.id,
        )
        snapshot = None
        header_sections: tuple[TableSection, ...] = ()
        organization_name = org.name
        beneficiary_sections: tuple[TableSection, ...] = ()
        dto_metadata: dict[str, Any] = {}
        if ctx.template_version in {"v2", "v3"}:
            snapshot = await load_report_snapshot(
                session,
                organization_id=ctx.organization_id,
                run_version_id=version["id"],
            )
            profile = snapshot.get("report_profile") or {}
            metadata = snapshot.get("run_metadata") or {}
            signatories = tuple(
                (
                    str(item.get("role") or "signatory"),
                    str(item.get("name") or ""),
                    str(item.get("designation") or item.get("role") or ""),
                )
                for item in profile.get("signatories", [])
                if isinstance(item, dict)
            )
            header_sections = (
                TableSection(
                    title="Bill reference",
                    columns=(ReportColumn("field", "Field"), ReportColumn("value", "Value")),
                    rows=(
                        ("Approval note No.", str(metadata.get("approval_note_number") or "")),
                        ("Approval note date", str(metadata.get("approval_note_date") or "")),
                        ("Bill No.", str(metadata.get("bill_number") or "")),
                        ("Bill date", str(metadata.get("bill_date") or "")),
                        ("DDO code", str(profile.get("ddo_code") or "")),
                    ),
                ),
            )
            organization_name = str((snapshot.get("organization") or {}).get("name") or org.name)
            if ctx.template_version == "v3":
                dto_metadata = {
                    "report_profile": dict(profile),
                    "run_metadata": dict(metadata),
                }
                identities = snapshot.get("employee_identity") or {}
                packed = await load_result_rows(
                    session,
                    organization_id=ctx.organization_id,
                    run_version_id=version["id"],
                )
                beneficiary_sections = (
                    TableSection(
                        title="Beneficiaries",
                        columns=(
                            ReportColumn("employee_number", "Employee No."),
                            ReportColumn("name", "Name"),
                            ReportColumn("designation", "Designation"),
                            ReportColumn("net_payable", "Net Payable", ColumnKind.MONEY),
                        ),
                        rows=tuple(
                            (
                                str(item["result"]["employee_number"]),
                                str(
                                    (identities.get(str(item["result"]["employee_id"])) or {}).get(
                                        "name"
                                    )
                                    or ""
                                ),
                                str(
                                    (identities.get(str(item["result"]["employee_id"])) or {}).get(
                                        "designation"
                                    )
                                    or ""
                                ),
                                money(item["result"]["net_payable"]),
                            )
                            for item in packed
                        ),
                    ),
                )
        else:
            signatories = await _load_signatories(session, organization_id=ctx.organization_id)

        # Words are a pure function of the numeric DTO amounts (never stored).
        gross_words = amount_in_words(gross)
        deductions_words = amount_in_words(deductions)
        net_words = amount_in_words(net)

        period_text = period_label(period.period_year, period.period_month)
        content_hash = str(version["content_hash"])
        version_number = int(version["version_number"])

        def _evidence_line(action: str, label: str) -> tuple[Any, ...]:
            packed = evidence.get(action)
            if packed is None:
                return (label, "", "")
            name, when = packed
            return (label, name, _format_timestamp(when))

        return ReportDTO(
            report_type=REPORT_TYPE_APPROVAL_NOTE,
            template_version=ctx.template_version,
            title="Office Approval Note",
            organization_name=organization_name,
            subtitle=period_text,
            sections=header_sections
            + beneficiary_sections
            + (
                TableSection(
                    title="Run identity",
                    columns=(
                        ReportColumn(key="field", header="Field", kind=ColumnKind.TEXT),
                        ReportColumn(key="value", header="Value", kind=ColumnKind.TEXT),
                    ),
                    rows=(
                        ("Period", period_text),
                        ("Run ID", str(run.id)),
                        ("Version number", str(version_number)),
                        ("Content hash", content_hash),
                        ("Headcount", str(headcount)),
                    ),
                ),
                TableSection(
                    title="Bill totals",
                    columns=(
                        ReportColumn(key="particulars", header="Particulars", kind=ColumnKind.TEXT),
                        ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                        ReportColumn(
                            key="amount_in_words",
                            header="Amount in words",
                            kind=ColumnKind.TEXT,
                        ),
                    ),
                    rows=(
                        ("Gross", gross, gross_words),
                        ("Total deductions", deductions, deductions_words),
                        ("Net payable", net, net_words),
                    ),
                ),
                TableSection(
                    title="Workflow evidence",
                    columns=(
                        ReportColumn(key="step", header="Step", kind=ColumnKind.TEXT),
                        ReportColumn(key="actor", header="Actor", kind=ColumnKind.TEXT),
                        ReportColumn(key="at", header="At", kind=ColumnKind.TEXT),
                    ),
                    rows=(
                        _evidence_line("submit", "Submitted by"),
                        _evidence_line("approve", "Approved by"),
                        _evidence_line("post", "Posted by"),
                    ),
                ),
                TableSection(
                    title="Signatories",
                    columns=(
                        ReportColumn(key="slot", header="Slot", kind=ColumnKind.TEXT),
                        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
                        ReportColumn(
                            key="designation",
                            header="Designation / role",
                            kind=ColumnKind.TEXT,
                        ),
                    ),
                    rows=tuple(
                        (slot, name, designation) for slot, name, designation in signatories
                    ),
                ),
            ),
            metadata=dto_metadata,
        )


# Module-level builder instance for registry wiring.
approval_note_builder = ApprovalNoteBuilder()


def approval_note_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def approval_note_to_pdf(dto: ReportDTO) -> bytes:
    """Primary office-note output (heading, identity, totals, workflow, signatories)."""
    return base_to_pdf(dto)


def _flatten_summary_rows(dto: ReportDTO) -> tuple[tuple[Any, ...], ...]:
    """Flatten multi-section note DTO into label/value rows for a single Excel sheet."""
    rows: list[tuple[Any, ...]] = []
    for section in dto.sections:
        rows.append((f"— {section.title} —", ""))
        keys = [col.key for col in section.columns]
        for row in section.rows:
            cells = dict(zip(keys, row, strict=True))
            if section.title == "Bill totals":
                amount = cells.get("amount")
                amount_display = (
                    format_inr(amount) if isinstance(amount, Decimal) else str(amount or "")
                )
                words = cells.get("amount_in_words") or ""
                value = amount_display if not words else f"{amount_display} ({words})"
                rows.append((str(cells.get("particulars") or ""), value))
            elif section.title == "Workflow evidence":
                actor = cells.get("actor") or ""
                at = cells.get("at") or ""
                value = actor if not at else f"{actor} at {at}"
                rows.append((str(cells.get("step") or ""), value))
            elif section.title == "Signatories":
                name = cells.get("name") or ""
                designation = cells.get("designation") or ""
                value = name if not designation else f"{name} ({designation})"
                rows.append((str(cells.get("slot") or ""), value))
            else:
                # Run identity and any other two-column text sections.
                field = cells.get("field") or cells.get(keys[0]) or ""
                value = cells.get("value") or (cells.get(keys[1]) if len(keys) > 1 else "")
                rows.append((str(field), str(value or "")))
    return tuple(rows)


def approval_note_to_excel(dto: ReportDTO) -> bytes:
    """Minimal single summary sheet for the approval note."""
    summary = ReportDTO(
        report_type=dto.report_type,
        template_version=dto.template_version,
        title=dto.title,
        organization_name=dto.organization_name,
        subtitle=dto.subtitle,
        sections=(
            TableSection(
                title="Summary",
                columns=(
                    ReportColumn(key="item", header="Item", kind=ColumnKind.TEXT),
                    ReportColumn(key="value", header="Value", kind=ColumnKind.TEXT),
                ),
                rows=_flatten_summary_rows(dto),
            ),
        ),
    )
    if dto.template_version == "v3":
        from app.reports.canonical_front_sheets import office_tip_to_excel

        return office_tip_to_excel(dto)
    return base_to_excel(summary)


def register(registry: ReportRegistry) -> None:
    """Register the office approval note on ``registry``."""
    registry.register(
        REPORT_TYPE_APPROVAL_NOTE,
        builder=approval_note_builder,
        to_json=approval_note_to_json,
        to_excel=approval_note_to_excel,
        to_pdf=approval_note_to_pdf,
        content_types=DEFAULT_CONTENT_TYPES,
        filename_pattern=FILENAME_PATTERN,
    )


# Family-local registry so the report is generatable without a central orchestrator.
FAMILY_REGISTRY = ReportRegistry()
register(FAMILY_REGISTRY)
