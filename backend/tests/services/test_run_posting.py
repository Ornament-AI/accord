"""Service tests for payroll run post / reverse commands.

Seam: submit/approve workflow is owned by a parallel lane. Tests insert
``PayrollApproval`` rows directly (and set run.status) to simulate
submit/approve without importing ``run_workflow``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunInput,
    payroll_employee_results,
    payroll_run_versions,
)
from app.models.platform import AuditEvent, OutboxEvent, PayrollApproval
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning
from app.services.run_calculation import calculate_run_command
from app.services.run_posting import post_run, reverse_run
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user
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

    org = await seed_organization(session, name="Post Org", slug=f"post-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"post_{uuid4().hex[:10]}")
    await session.commit()

    await _bind(session, org.id, user.id)

    employee = Employee(organization_id=org.id, employee_number="E-POST-1")
    session.add(employee)
    await session.flush()

    await versioning.insert_version(
        session,
        employee_profile_versions,
        organization_id=org.id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={
            "name": "Post Employee",
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


async def _calculate_and_approve(
    session: AsyncSession,
    world: dict,
    *,
    content_hash: str | None = None,
) -> dict:
    """Calculate then simulate approve via direct status + PayrollApproval insert."""
    await _bind(session, world["org_id"], world["user_id"])
    calc = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.status = "approved"
    hash_to_bind = content_hash if content_hash is not None else calc["content_hash"]
    session.add(
        PayrollApproval(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            run_version_id=calc["version_id"],
            content_hash=hash_to_bind,
            action="approve",
            actor_user_id=world["user_id"],
            reason="Looks good",
        )
    )
    await session.commit()
    return calc


async def _count_evidence(
    session: AsyncSession, *, org_id, run_id, action: str | None = None
) -> dict:
    approvals_stmt = (
        sa.select(sa.func.count())
        .select_from(PayrollApproval)
        .where(
            PayrollApproval.organization_id == org_id,
            PayrollApproval.run_id == run_id,
        )
    )
    if action is not None:
        approvals_stmt = approvals_stmt.where(PayrollApproval.action == action)
    approvals = int((await session.execute(approvals_stmt)).scalar_one())

    audits = int(
        (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.organization_id == org_id,
                    AuditEvent.entity_id == run_id,
                    AuditEvent.command.in_(("payroll_run.post", "payroll_run.reverse")),
                )
            )
        ).scalar_one()
    )
    outbox = int(
        (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.organization_id == org_id,
                    OutboxEvent.event_type.in_(("payroll_run.posted", "payroll_run.reversed")),
                )
            )
        ).scalar_one()
    )
    return {"approvals": approvals, "audits": audits, "outbox": outbox}


@pytest.mark.asyncio
async def test_post_happy_path_writes_approval_audit_outbox(session):
    world = await _seed_world(session)
    calc = await _calculate_and_approve(session, world)

    await _bind(session, world["org_id"], world["user_id"])
    result = await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert result["status"] == "posted"
    assert result["id"] == str(world["run_id"])

    await _bind(session, world["org_id"], world["user_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    assert run.status == "posted"

    post_approval = (
        await session.execute(
            sa.select(PayrollApproval).where(
                PayrollApproval.run_id == world["run_id"],
                PayrollApproval.action == "post",
            )
        )
    ).scalar_one()
    assert post_approval.run_version_id == calc["version_id"]
    assert post_approval.content_hash == calc["content_hash"]
    assert post_approval.actor_user_id == world["user_id"]

    audit = (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.entity_id == world["run_id"],
                AuditEvent.command == "payroll_run.post",
            )
        )
    ).scalar_one()
    assert audit.event_kind == "mutation"
    assert audit.before_state is not None and audit.before_state["status"] == "approved"
    assert audit.after_state is not None and audit.after_state["status"] == "posted"
    assert audit.changed_count == 1
    assert audit.actor_snapshot is not None
    assert audit.actor_snapshot["id"] == str(world["user_id"])
    assert audit.entity_label.startswith("2026-")
    assert audit.summary["content_hash"] == calc["content_hash"]
    assert audit.summary["totals"]["net_payable"] == "51000.00"

    outbox = (
        await session.execute(
            sa.select(OutboxEvent).where(
                OutboxEvent.organization_id == world["org_id"],
                OutboxEvent.event_type == "payroll_run.posted",
            )
        )
    ).scalar_one()
    assert outbox.payload["run_id"] == str(world["run_id"])
    assert outbox.payload["run_version_id"] == str(calc["version_id"])
    assert outbox.payload["content_hash"] == calc["content_hash"]


@pytest.mark.asyncio
async def test_stale_approval_hash_409_writes_nothing(session):
    world = await _seed_world(session)
    await _calculate_and_approve(session, world, content_hash="stale-hash-not-matching")

    await _bind(session, world["org_id"], world["user_id"])
    before = await _count_evidence(session, org_id=world["org_id"], run_id=world["run_id"])

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="stale"):
        await post_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )

    await _bind(session, world["org_id"], world["user_id"])
    after = await _count_evidence(session, org_id=world["org_id"], run_id=world["run_id"])
    assert after == before
    assert (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(PayrollApproval)
            .where(
                PayrollApproval.run_id == world["run_id"],
                PayrollApproval.action == "post",
            )
        )
    ).scalar_one() == 0
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    assert run.status == "approved"


@pytest.mark.asyncio
async def test_blocking_validation_409(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # Replace the calculated snapshot with an empty-employees version so
    # validate_run_result reports blocking ``empty_run``.
    await _bind(session, world["org_id"], world["user_id"])
    empty_version_id = uuid4()
    await session.execute(
        sa.insert(payroll_run_versions).values(
            id=empty_version_id,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            version_number=99,
            engine_version="test-empty",
            content_hash="empty-run-hash",
            calculated_at=datetime.now(timezone.utc),
            calculated_by=world["user_id"],
            inputs_snapshot={"employees": []},
            totals={"net_payable": "0.00"},
        )
    )
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.current_version_id = empty_version_id
    run.status = "approved"
    session.add(
        PayrollApproval(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            run_version_id=empty_version_id,
            content_hash="empty-run-hash",
            action="approve",
            actor_user_id=world["user_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="blocking validation"):
        await post_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_wrong_status_409(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="cannot be posted"):
        await post_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_posted_immutable_rows_reject_update(session):
    world = await _seed_world(session)
    calc = await _calculate_and_approve(session, world)

    await _bind(session, world["org_id"], world["user_id"])
    await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(DBAPIError, match="(?i)accord: UPDATE/DELETE forbidden"):
        await session.execute(
            sa.update(payroll_run_versions)
            .where(payroll_run_versions.c.id == calc["version_id"])
            .values(engine_version="tampered")
        )
        await session.flush()

    await _bind(session, world["org_id"], world["user_id"])
    emp = (
        (
            await session.execute(
                sa.select(payroll_employee_results).where(
                    payroll_employee_results.c.run_version_id == calc["version_id"]
                )
            )
        )
        .mappings()
        .one()
    )
    with pytest.raises(DBAPIError, match="(?i)accord: UPDATE/DELETE forbidden"):
        await session.execute(
            sa.update(payroll_employee_results)
            .where(payroll_employee_results.c.id == emp["id"])
            .values(net_payable=Decimal("1.00"))
        )
        await session.flush()


@pytest.mark.asyncio
async def test_double_post_second_call_409(session):
    world = await _seed_world(session)
    await _calculate_and_approve(session, world)

    await _bind(session, world["org_id"], world["user_id"])
    await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="cannot be posted"):
        await post_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )

    await _bind(session, world["org_id"], world["user_id"])
    post_count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(PayrollApproval)
            .where(
                PayrollApproval.run_id == world["run_id"],
                PayrollApproval.action == "post",
            )
        )
    ).scalar_one()
    assert post_count == 1


@pytest.mark.asyncio
async def test_reverse_happy_path(session):
    world = await _seed_world(session)
    calc = await _calculate_and_approve(session, world)

    await _bind(session, world["org_id"], world["user_id"])
    await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    result = await reverse_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
        reason="Bank file rejected",
    )
    assert result["status"] == "reversed"
    assert result["reversal_run_id"]

    await _bind(session, world["org_id"], world["user_id"])
    original = await session.get(PayrollRun, world["run_id"])
    assert original is not None
    assert original.status == "reversed"
    assert original.current_version_id == calc["version_id"]

    reversal = await session.get(PayrollRun, UUID(result["reversal_run_id"]))
    assert reversal is not None
    assert reversal.status == "draft"
    assert reversal.original_run_id == world["run_id"]
    assert reversal.period_id == world["period_id"]

    reverse_approval = (
        await session.execute(
            sa.select(PayrollApproval).where(
                PayrollApproval.run_id == world["run_id"],
                PayrollApproval.action == "reverse",
            )
        )
    ).scalar_one()
    assert reverse_approval.reason == "Bank file rejected"

    audit = (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.entity_id == world["run_id"],
                AuditEvent.command == "payroll_run.reverse",
            )
        )
    ).scalar_one()
    assert audit.event_kind == "mutation"
    assert audit.before_state is not None and audit.before_state["status"] == "posted"
    assert audit.after_state is not None and audit.after_state["status"] == "reversed"
    assert audit.changed_count == 1
    assert audit.summary["reversal_run_id"] == result["reversal_run_id"]

    outbox = (
        await session.execute(
            sa.select(OutboxEvent).where(
                OutboxEvent.organization_id == world["org_id"],
                OutboxEvent.event_type == "payroll_run.reversed",
            )
        )
    ).scalar_one()
    assert outbox.payload["reversal_run_id"] == result["reversal_run_id"]


@pytest.mark.asyncio
async def test_reverse_without_reason_raises(session):
    world = await _seed_world(session)
    await _calculate_and_approve(session, world)
    await _bind(session, world["org_id"], world["user_id"])
    await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ValidationError, match="reason is required"):
        await reverse_run(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
            reason="   ",
        )
