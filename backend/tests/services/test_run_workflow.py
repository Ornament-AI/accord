"""Service tests for payroll run workflow commands."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ForbiddenError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunInput,
    payroll_run_versions,
)
from app.models.platform import AuditEvent, PayrollApproval
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning
from app.services.run_calculation import calculate_run_command
from app.services.run_workflow import (
    URN_BLOCKING_VALIDATION,
    URN_ILLEGAL_TRANSITION,
    URN_MAKER_CHECKER,
    URN_STALE_VERSION,
    URN_WITHDRAW_FORBIDDEN,
    approve_run,
    reject_run,
    submit_run,
    validate_run,
    withdraw_run,
)
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_membership, seed_organization, seed_user
from tests.roster_helpers import initialize_run_roster


async def _bind(session: AsyncSession, org_id, user_id) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_world(session: AsyncSession) -> dict:
    """Seed a small calculate world in one committed transaction."""
    if session.in_transaction():
        await session.rollback()

    org = await seed_organization(session, name="Workflow Org", slug=f"wf-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"wf_{uuid4().hex[:10]}")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=user.id,
        role="organization_administrator",
    )
    await session.commit()

    await _bind(session, org.id, user.id)

    employee = Employee(organization_id=org.id, employee_number="E-WF-1")
    session.add(employee)
    await session.flush()

    await versioning.insert_version(
        session,
        employee_profile_versions,
        organization_id=org.id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={
            "name": "Workflow Employee",
            "sevarth_id": f"SEV-{uuid4().hex[:8]}",
            "pan": "ABCDE1234F",
            "date_of_birth": date(1990, 1, 15),
            "date_of_joining": date(2015, 6, 1),
            "retirement_regime": "gpf",
            "gpf_jurisdiction": "mumbai",
            "pran": None,
            "gpf_account_number": "GPF123",
            "epf_number": None,
            "pension_account": None,
        },
        change_reason=None,
        created_by=user.id,
    )
    await versioning.insert_version(
        session,
        employee_pay_versions,
        organization_id=org.id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={"pay_matrix_level": "L10", "basic_pay": Decimal("50000.00")},
        change_reason=None,
        created_by=user.id,
    )

    basic = PayComponent(
        organization_id=org.id,
        code="BASIC",
        name="Basic Pay",
        classification="earning",
    )
    allowance = PayComponent(
        organization_id=org.id,
        code="FIXED_ALLOWANCE",
        name="Fixed Allowance",
        classification="earning",
    )
    hba = PayComponent(
        organization_id=org.id,
        code="HBA_INSTALLMENT",
        name="HBA Installment",
        classification="external_recovery",
    )
    license_fee = PayComponent(
        organization_id=org.id,
        code="ACCOMMODATION_LICENSE_FEE",
        name="Accommodation License Fee",
        classification="external_recovery",
    )
    session.add_all([basic, allowance, hba, license_fee])
    await session.flush()

    for component, amount in (
        (basic, Decimal("50000.00")),
        (allowance, Decimal("2000.00")),
    ):
        await versioning.insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            values={
                "calc_kind": "fixed_recurring_amount",
                "amount": amount,
                "rate": None,
                "basis": None,
                "rounding_rule": "ROUND_NONE",
            },
            change_reason=None,
            created_by=user.id,
        )

    instruction = RecurringInstruction(
        organization_id=org.id,
        employee_id=employee.id,
        component_id=allowance.id,
    )
    session.add(instruction)
    await session.flush()
    await versioning.insert_version(
        session,
        recurring_instruction_versions,
        organization_id=org.id,
        header_id=instruction.id,
        effective_from=date(2026, 1, 1),
        values={"amount": Decimal("2000.00"), "rate": None, "reason": "Standing allowance"},
        change_reason=None,
        created_by=user.id,
    )

    advance = AdvanceAccount(
        organization_id=org.id,
        employee_id=employee.id,
        advance_type="hba",
        principal=Decimal("12000.00"),
        sanctioned_on=date(2026, 1, 1),
        reference="HBA-1",
    )
    session.add(advance)
    await session.flush()
    await versioning.insert_version(
        session,
        advance_installment_versions,
        organization_id=org.id,
        header_id=advance.id,
        effective_from=date(2026, 1, 1),
        values={
            "installment_amount": Decimal("1000.00"),
            "installments_total": 12,
            "installments_recovered_opening": 0,
        },
        change_reason=None,
        created_by=user.id,
    )

    assignment = AccommodationAssignment(
        organization_id=org.id,
        employee_id=employee.id,
        quarters_location="mumbai",
        quarters_identifier="A-1",
    )
    session.add(assignment)
    await session.flush()
    await versioning.insert_version(
        session,
        accommodation_charge_versions,
        organization_id=org.id,
        header_id=assignment.id,
        effective_from=date(2026, 1, 1),
        values={
            "license_fee": Decimal("500.00"),
            "informational_hra_foregone": Decimal("2500.00"),
        },
        change_reason=None,
        created_by=user.id,
    )

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
        status="draft",
    )
    session.add(run)
    await session.flush()
    session.add_all(
        initialize_run_roster(
            organization_id=org.id,
            run=run,
            employee_ids=[employee.id],
            period_year=period.period_year,
            period_month=period.period_month,
        )
    )

    override = PayrollRunInput(
        organization_id=org.id,
        run_id=run.id,
        employee_id=employee.id,
        component_code="FIXED_ALLOWANCE",
        input_kind="override",
        amount=Decimal("2500.00"),
        reason="June override",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(override)
    await session.commit()

    return {
        "org_id": org.id,
        "user_id": user.id,
        "employee_id": employee.id,
        "run_id": run.id,
        "period_id": period.id,
    }


async def _count_approvals(session: AsyncSession, *, run_id, action: str | None = None) -> int:
    stmt = (
        sa.select(sa.func.count())
        .select_from(PayrollApproval)
        .where(PayrollApproval.run_id == run_id)
    )
    if action is not None:
        stmt = stmt.where(PayrollApproval.action == action)
    return int((await session.execute(stmt)).scalar_one())


async def _count_audits(session: AsyncSession, *, run_id, command: str | None = None) -> int:
    stmt = (
        sa.select(sa.func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.entity_type == "payroll_run",
            AuditEvent.entity_id == run_id,
        )
    )
    if command is not None:
        stmt = stmt.where(AuditEvent.command == command)
    return int((await session.execute(stmt)).scalar_one())


@pytest.mark.asyncio
async def test_happy_path_validate_submit_approve(session):
    world = await _seed_world(session)
    approver = await seed_user(session, workos_user_id=f"wf_ap_{uuid4().hex[:10]}")
    approver_id = approver.id
    await seed_membership(
        session,
        organization_id=world["org_id"],
        user_id=approver_id,
        role="payroll_approver",
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    calc = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    validated = await validate_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
    )
    assert validated["status"] == "calculated"
    assert validated["blocking"] is False
    assert validated["current_version_number"] == 1
    assert validated["content_hash"] == calc["content_hash"]
    assert await _count_approvals(session, run_id=world["run_id"]) == 0
    assert await _count_audits(session, run_id=world["run_id"]) == 0

    await _bind(session, world["org_id"], world["user_id"])
    submitted = await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
        reason="ready for review",
    )
    assert submitted["status"] == "submitted"
    assert await _count_approvals(session, run_id=world["run_id"], action="submit") == 1
    assert await _count_audits(session, run_id=world["run_id"], command="submit") == 1
    submit_audit = (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.entity_id == world["run_id"], AuditEvent.command == "submit"
            )
        )
    ).scalar_one()
    assert submit_audit.event_kind == "mutation"
    assert submit_audit.before_state is not None
    assert submit_audit.before_state["status"] == "calculated"
    assert submit_audit.after_state is not None
    assert submit_audit.after_state["status"] == "submitted"
    assert submit_audit.changed_count == 1

    await _bind(session, world["org_id"], approver_id)
    approved = await approve_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=approver_id,
        reason="ok",
    )
    assert approved["status"] == "approved"
    assert approved["content_hash"] == calc["content_hash"]
    assert await _count_approvals(session, run_id=world["run_id"], action="approve") == 1
    assert await _count_audits(session, run_id=world["run_id"], command="approve") == 1


@pytest.mark.asyncio
async def test_self_approval_blocked(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError) as exc:
        await approve_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )
    assert exc.value.error_code == URN_MAKER_CHECKER


@pytest.mark.asyncio
async def test_withdraw_by_submitter_and_admin(session):
    world = await _seed_world(session)
    other = await seed_user(session, workos_user_id=f"wf_ot_{uuid4().hex[:10]}")
    other_id = other.id
    await seed_membership(
        session,
        organization_id=world["org_id"],
        user_id=other_id,
        role="payroll_preparer",
    )
    admin = await seed_user(session, workos_user_id=f"wf_ad_{uuid4().hex[:10]}")
    admin_id = admin.id
    await seed_membership(
        session,
        organization_id=world["org_id"],
        user_id=admin_id,
        role="organization_administrator",
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], other_id)
    with pytest.raises(ForbiddenError) as exc:
        await withdraw_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=other_id,
        )
    assert exc.value.error_code == URN_WITHDRAW_FORBIDDEN

    await _bind(session, world["org_id"], world["user_id"])
    withdrawn = await withdraw_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert withdrawn["status"] == "calculated"
    assert await _count_approvals(session, run_id=world["run_id"], action="withdraw") == 1

    await _bind(session, world["org_id"], world["user_id"])
    await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], admin_id)
    withdrawn_by_admin = await withdraw_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=admin_id,
        reason="admin pullback",
    )
    assert withdrawn_by_admin["status"] == "calculated"
    assert await _count_approvals(session, run_id=world["run_id"], action="withdraw") == 2


@pytest.mark.asyncio
async def test_approve_stale_hash_after_recalculate(session):
    world = await _seed_world(session)
    approver = await seed_user(session, workos_user_id=f"wf_st_{uuid4().hex[:10]}")
    approver_id = approver.id
    await seed_membership(
        session,
        organization_id=world["org_id"],
        user_id=approver_id,
        role="payroll_approver",
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    first = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # Calculate rejects submitted; force a recalculation while keeping status submitted
    # so current_version drifts from the submit binding.
    await _bind(session, world["org_id"], world["user_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.status = "calculated"
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    override = (
        await session.execute(
            sa.select(PayrollRunInput).where(PayrollRunInput.run_id == world["run_id"])
        )
    ).scalar_one()
    override.amount = Decimal("3000.00")
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    second = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert second["content_hash"] != first["content_hash"]

    await _bind(session, world["org_id"], world["user_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.status = "submitted"
    await session.commit()

    await _bind(session, world["org_id"], approver_id)
    with pytest.raises(ConflictError) as exc:
        await approve_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=approver_id,
        )
    assert exc.value.error_code == URN_STALE_VERSION


@pytest.mark.asyncio
async def test_wrong_status_transitions(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])

    with pytest.raises(ConflictError) as approve_draft:
        await approve_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )
    assert approve_draft.value.error_code == URN_ILLEGAL_TRANSITION

    with pytest.raises(ConflictError) as validate_draft:
        await validate_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
        )
    assert validate_draft.value.error_code == URN_ILLEGAL_TRANSITION

    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError) as submit_again:
        await submit_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )
    assert submit_again.value.error_code == URN_ILLEGAL_TRANSITION


@pytest.mark.asyncio
async def test_blocking_validation_prevents_submit(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # Point the run at an empty calculated version (blocking empty_run finding).
    empty_version_id = uuid4()
    await _bind(session, world["org_id"], world["user_id"])
    await session.execute(
        sa.insert(payroll_run_versions).values(
            id=empty_version_id,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            version_number=99,
            engine_version="test",
            content_hash="a" * 64,
            calculated_at=datetime.now(timezone.utc),
            calculated_by=world["user_id"],
            inputs_snapshot={"period": "2026-06", "org_ref": str(world["org_id"]), "employees": []},
            totals={
                "earnings_total": "0.00",
                "employer_contribution_total": "0.00",
                "gross_adjustment_total": "0.00",
                "gross_total": "0.00",
                "ag_deduction_total": "0.00",
                "treasury_deduction_total": "0.00",
                "external_recovery_total": "0.00",
                "deductions_total": "0.00",
                "net_payable": "0.00",
            },
        )
    )
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.current_version_id = empty_version_id
    run.status = "calculated"
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    validated = await validate_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
    )
    assert validated["blocking"] is True

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError) as exc:
        await submit_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )
    assert exc.value.error_code == URN_BLOCKING_VALIDATION


@pytest.mark.asyncio
async def test_reject_writes_approval_and_audit(session):
    world = await _seed_world(session)
    approver = await seed_user(session, workos_user_id=f"wf_rj_{uuid4().hex[:10]}")
    approver_id = approver.id
    await seed_membership(
        session,
        organization_id=world["org_id"],
        user_id=approver_id,
        role="payroll_approver",
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])
    await submit_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], approver_id)
    rejected = await reject_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=approver_id,
        reason="fix inputs",
    )
    assert rejected["status"] == "rejected"
    assert await _count_approvals(session, run_id=world["run_id"], action="reject") == 1
    assert await _count_audits(session, run_id=world["run_id"], command="reject") == 1
