"""Golden tests for the office approval note report family.

Uses a posted June 2026 world seeded from fixture totals (same aggregates as
``fixtures/sanitized/june-2026/expected_totals.json``) with distinct
maker / approver / poster actors on ``PayrollApproval`` rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.employees import Employee
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_run_versions,
)
from app.models.platform import PayrollApproval
from app.models.reports import ReportConfiguration
from app.reports.amount_in_words import amount_in_words
from app.reports.base import ReportContext, ReportRegistry
from app.reports.families.approval_note import (
    FAMILY_REGISTRY,
    FILENAME_PATTERN,
    REPORT_TYPE_APPROVAL_NOTE,
    ApprovalNoteBuilder,
    approval_note_builder,
    approval_note_to_excel,
    approval_note_to_json,
    approval_note_to_pdf,
    register,
)
from app.reports.formatting import format_inr
from app.services.run_workflow import URN_MAKER_CHECKER
from app.tenancy import bind_tenant_context
from tests.e2e.fixture_loader import load_june_fixture
from tests.identity_helpers import seed_organization, seed_user

_GROSS = Decimal("5102985.00")
_DEDUCTIONS = Decimal("1264890.00")
_NET = Decimal("3838095.00")
_HEADCOUNT = 32
_CONTENT_HASH = "june-2026-posted-content-hash-v1"
_TEMPLATE_VERSION = "v1"
_ENGINE_VERSION = "test-engine-1.0"


async def _bind(session: AsyncSession, org_id, user_id) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_posted_june_world(
    session: AsyncSession,
    *,
    with_signatories: bool = True,
    run_status: str = "posted",
    same_maker_approver: bool = False,
) -> dict:
    """Seed a posted (or unposted) June world with fixture totals + 3 distinct actors."""
    if session.in_transaction():
        await session.rollback()

    fixture = load_june_fixture()
    org = await seed_organization(
        session,
        name=fixture.organization.name,
        slug=f"approval-note-{uuid4().hex[:10]}",
    )
    maker = await seed_user(
        session,
        email=f"maker-{uuid4().hex[:8]}@approval-note.test",
        name="Approval Note Maker",
    )
    approver = (
        maker
        if same_maker_approver
        else await seed_user(
            session,
            email=f"approver-{uuid4().hex[:8]}@approval-note.test",
            name="Approval Note Approver",
        )
    )
    poster = await seed_user(
        session,
        email=f"poster-{uuid4().hex[:8]}@approval-note.test",
        name="Approval Note Poster",
    )
    await session.commit()

    await _bind(session, org.id, maker.id)

    period = PayrollPeriod(
        organization_id=org.id,
        period_year=2026,
        period_month=6,
        status="open",
    )
    session.add(period)
    await session.flush()

    run = PayrollRun(
        organization_id=org.id,
        period_id=period.id,
        status=run_status if run_status != "posted" else "approved",
    )
    session.add(run)
    await session.flush()

    version_id = uuid4()
    await session.execute(
        sa.insert(payroll_run_versions).values(
            id=version_id,
            organization_id=org.id,
            run_id=run.id,
            version_number=1,
            engine_version=_ENGINE_VERSION,
            content_hash=_CONTENT_HASH,
            calculated_at=datetime(2026, 6, 28, 9, 0, tzinfo=UTC),
            calculated_by=maker.id,
            inputs_snapshot={"employees": [], "source": "june-2026-fixture-totals"},
            totals={
                "earnings_total": "5073200.00",
                "employer_contribution_total": "29785.00",
                "gross_adjustment_total": "0.00",
                "gross_total": "5102985.00",
                "ag_deduction_total": "0.00",
                "treasury_deduction_total": "0.00",
                "external_recovery_total": "0.00",
                "deductions_total": "1264890.00",
                "net_payable": "3838095.00",
            },
        )
    )

    employees: list[Employee] = []
    for index in range(1, _HEADCOUNT + 1):
        emp = Employee(
            organization_id=org.id,
            employee_number=f"AN-{index:03d}",
        )
        session.add(emp)
        employees.append(emp)
    await session.flush()

    for emp in employees:
        await session.execute(
            sa.insert(payroll_employee_results).values(
                id=uuid4(),
                organization_id=org.id,
                run_version_id=version_id,
                employee_id=emp.id,
                employee_number=emp.employee_number,
                earnings_total=Decimal("0.00"),
                employer_contribution_total=Decimal("0.00"),
                gross_total=Decimal("0.00"),
                deductions_total=Decimal("0.00"),
                net_payable=Decimal("0.00"),
                offbill_employer_remittance=Decimal("0.00"),
                disbursement=Decimal("0.00"),
            )
        )

    run.current_version_id = version_id
    if run_status == "posted":
        run.status = "posted"

    submit_at = datetime(2026, 6, 28, 10, 0, tzinfo=UTC)
    approve_at = datetime(2026, 6, 28, 11, 0, tzinfo=UTC)
    post_at = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)

    session.add(
        PayrollApproval(
            organization_id=org.id,
            run_id=run.id,
            run_version_id=version_id,
            content_hash=_CONTENT_HASH,
            action="submit",
            actor_user_id=maker.id,
            reason="Ready for approval",
            created_at=submit_at,
        )
    )
    session.add(
        PayrollApproval(
            organization_id=org.id,
            run_id=run.id,
            run_version_id=version_id,
            content_hash=_CONTENT_HASH,
            action="approve",
            actor_user_id=approver.id,
            reason="Approved",
            created_at=approve_at,
        )
    )
    if run_status == "posted":
        session.add(
            PayrollApproval(
                organization_id=org.id,
                run_id=run.id,
                run_version_id=version_id,
                content_hash=_CONTENT_HASH,
                action="post",
                actor_user_id=poster.id,
                reason="Posted",
                created_at=post_at,
            )
        )

    if with_signatories:
        session.add(
            ReportConfiguration(
                organization_id=org.id,
                key="signatories",
                value={
                    "maker": {"name": "Employee S-01", "role": "maker"},
                    "checker": {"name": "Employee S-02", "role": "checker"},
                    "approving_officer": {
                        "name": "Employee S-03",
                        "role": "approving_officer",
                    },
                },
            )
        )

    await session.commit()

    return {
        "org_id": org.id,
        "org_name": org.name,
        "run_id": run.id,
        "version_id": version_id,
        "maker_id": maker.id,
        "approver_id": approver.id,
        "poster_id": poster.id,
        "maker_name": maker.name,
        "approver_name": approver.name,
        "poster_name": poster.name,
        "submit_at": submit_at,
        "approve_at": approve_at,
        "post_at": post_at,
    }


def _ctx(world: dict) -> ReportContext:
    return ReportContext(
        organization_id=world["org_id"],
        posted_run_id=world["run_id"],
        template_version=_TEMPLATE_VERSION,
        generated_at=datetime.now(UTC),
        engine_version=_ENGINE_VERSION,
    )


def _section_map(dto) -> dict[str, object]:
    return {section.title: section for section in dto.sections}


def _totals_rows(dto) -> dict[str, tuple]:
    section = _section_map(dto)["Bill totals"]
    return {row[0]: row for row in section.rows}


def _identity_rows(dto) -> dict[str, str]:
    section = _section_map(dto)["Run identity"]
    return {str(row[0]): str(row[1]) for row in section.rows}


def _workflow_rows(dto) -> dict[str, tuple]:
    section = _section_map(dto)["Workflow evidence"]
    return {row[0]: row for row in section.rows}


def _signatory_rows(dto) -> dict[str, tuple]:
    section = _section_map(dto)["Signatories"]
    return {row[0]: row for row in section.rows}


@pytest.mark.asyncio
async def test_registry_registers_approval_note() -> None:
    assert REPORT_TYPE_APPROVAL_NOTE == "approval_note"
    assert REPORT_TYPE_APPROVAL_NOTE in FAMILY_REGISTRY
    entry = FAMILY_REGISTRY.get(REPORT_TYPE_APPROVAL_NOTE)
    assert entry.builder is approval_note_builder
    assert entry.formatters.to_json is approval_note_to_json
    assert entry.formatters.to_pdf is approval_note_to_pdf
    assert entry.formatters.to_excel is approval_note_to_excel
    assert entry.formatters.filename_pattern == FILENAME_PATTERN

    fresh = ReportRegistry()
    register(fresh)
    assert "approval_note" in fresh


@pytest.mark.asyncio
async def test_approval_note_totals_actors_hash_and_words(session: AsyncSession) -> None:
    world = await _seed_posted_june_world(session, with_signatories=True)
    await _bind(session, world["org_id"], world["maker_id"])

    dto = await ApprovalNoteBuilder().build(session, _ctx(world))

    assert dto.report_type == REPORT_TYPE_APPROVAL_NOTE
    assert dto.title == "Office Approval Note"
    assert dto.organization_name == world["org_name"]
    assert dto.subtitle == "June 2026"

    identity = _identity_rows(dto)
    assert identity["Period"] == "June 2026"
    assert identity["Run ID"] == str(world["run_id"])
    assert identity["Version number"] == "1"
    assert identity["Content hash"] == _CONTENT_HASH
    assert identity["Headcount"] == str(_HEADCOUNT)

    totals = _totals_rows(dto)
    assert totals["Gross"][1] == _GROSS
    assert totals["Total deductions"][1] == _DEDUCTIONS
    assert totals["Net payable"][1] == _NET
    assert totals["Gross"][2] == amount_in_words(_GROSS)
    assert totals["Total deductions"][2] == amount_in_words(_DEDUCTIONS)
    assert totals["Net payable"][2] == amount_in_words(_NET)

    workflow = _workflow_rows(dto)
    assert workflow["Submitted by"][1] == world["maker_name"]
    assert workflow["Approved by"][1] == world["approver_name"]
    assert workflow["Posted by"][1] == world["poster_name"]
    assert world["maker_name"] != world["approver_name"] != world["poster_name"]

    signatories = _signatory_rows(dto)
    assert signatories["maker"][1] == "Employee S-01"
    assert signatories["checker"][1] == "Employee S-02"
    assert signatories["approving_officer"][1] == "Employee S-03"
    assert signatories["maker"][2] == "maker"
    assert signatories["approving_officer"][2] == "approving_officer"

    # Posted version content_hash must match the note.
    version_hash = (
        await session.execute(
            sa.select(payroll_run_versions.c.content_hash).where(
                payroll_run_versions.c.id == world["version_id"]
            )
        )
    ).scalar_one()
    assert identity["Content hash"] == version_hash == _CONTENT_HASH


@pytest.mark.asyncio
async def test_signatory_placeholders_when_config_absent(session: AsyncSession) -> None:
    world = await _seed_posted_june_world(session, with_signatories=False)
    await _bind(session, world["org_id"], world["maker_id"])

    dto = await ApprovalNoteBuilder().build(session, _ctx(world))
    signatories = _signatory_rows(dto)

    assert signatories["maker"][1] == "____________________"
    assert signatories["checker"][1] == "____________________"
    assert signatories["approving_officer"][1] == "____________________"
    assert signatories["maker"][2] == "maker"
    assert signatories["checker"][2] == "checker"
    assert signatories["approving_officer"][2] == "approving_officer"


@pytest.mark.asyncio
async def test_pdf_contains_actors_and_net(session: AsyncSession) -> None:
    world = await _seed_posted_june_world(session, with_signatories=True)
    await _bind(session, world["org_id"], world["maker_id"])

    dto = await approval_note_builder.build(session, _ctx(world))
    raw = approval_note_to_pdf(dto)
    assert isinstance(raw, (bytes, bytearray))
    assert raw.startswith(b"%PDF")

    reader = PdfReader(BytesIO(raw))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Office Approval Note" in text
    assert world["maker_name"] in text
    assert world["approver_name"] in text
    assert world["poster_name"] in text
    assert format_inr(_NET) in text
    assert _CONTENT_HASH in text


@pytest.mark.asyncio
async def test_json_and_excel_formatters(session: AsyncSession) -> None:
    world = await _seed_posted_june_world(session, with_signatories=True)
    await _bind(session, world["org_id"], world["maker_id"])

    dto = await approval_note_builder.build(session, _ctx(world))
    payload = approval_note_to_json(dto)
    assert payload["report_type"] == "approval_note"
    totals_section = next(s for s in payload["sections"] if s["title"] == "Bill totals")
    net_row = next(r for r in totals_section["rows"] if r["particulars"] == "Net payable")
    assert net_row["amount"] == "3838095.00"
    assert net_row["amount_in_words"] == amount_in_words(_NET)

    xlsx = approval_note_to_excel(dto)
    assert isinstance(xlsx, (bytes, bytearray))
    assert xlsx[:2] == b"PK"


@pytest.mark.asyncio
async def test_unposted_run_raises_conflict(session: AsyncSession) -> None:
    world = await _seed_posted_june_world(session, with_signatories=False, run_status="calculated")
    await _bind(session, world["org_id"], world["maker_id"])

    with pytest.raises(ConflictError, match="must be posted") as exc_info:
        await ApprovalNoteBuilder().build(session, _ctx(world))
    assert exc_info.value.details["status"] == "calculated"


@pytest.mark.asyncio
async def test_maker_equals_approver_raises_maker_checker(session: AsyncSession) -> None:
    # payroll_approvals is append-only/immutable — seed SoD violation instead of updating.
    world = await _seed_posted_june_world(
        session,
        with_signatories=False,
        same_maker_approver=True,
    )
    await _bind(session, world["org_id"], world["maker_id"])

    with pytest.raises(ConflictError) as exc_info:
        await ApprovalNoteBuilder().build(session, _ctx(world))
    assert exc_info.value.error_code == URN_MAKER_CHECKER
