"""Service tests for payroll run calculate command."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunInput,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning
from app.services.run_calculation import calculate_run_command
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


async def _bind(session: AsyncSession, org_id, user_id) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_world(session: AsyncSession) -> dict:
    """Seed a small calculate world in one committed transaction."""
    if session.in_transaction():
        await session.rollback()

    org = await seed_organization(session, name="Calc Org", slug=f"calc-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"calc_{uuid4().hex[:10]}")
    await session.commit()

    await _bind(session, org.id, user.id)

    employee = Employee(organization_id=org.id, employee_number="E-CALC-1")
    session.add(employee)
    await session.flush()

    await versioning.insert_version(
        session,
        employee_profile_versions,
        organization_id=org.id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={
            "name": "Calc Employee",
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
        run_type="regular",
        status="draft",
    )
    session.add(run)
    await session.flush()

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
        "override_id": override.id,
    }


@pytest.mark.asyncio
async def test_calculate_persists_version_results_and_totals(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])

    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    assert result["version_number"] == 1
    assert result["engine_version"]
    assert result["content_hash"]
    # BASIC 50000 + overridden allowance 2500 = 52500 earnings
    # HBA 1000 + license 500 = 1500 deductions; foregone HRA excluded
    assert result["totals"]["earnings_total"] == "52500.00"
    assert result["totals"]["employer_contribution_total"] == "0.00"
    assert result["totals"]["gross_total"] == "52500.00"
    assert result["totals"]["external_recovery_total"] == "1500.00"
    assert result["totals"]["deductions_total"] == "1500.00"
    assert result["totals"]["net_payable"] == "51000.00"

    await _bind(session, world["org_id"], world["user_id"])
    version = (
        (
            await session.execute(
                sa.select(payroll_run_versions).where(
                    payroll_run_versions.c.id == result["version_id"]
                )
            )
        )
        .mappings()
        .one()
    )
    assert version["version_number"] == 1
    assert version["content_hash"] == result["content_hash"]
    assert version["inputs_snapshot"]["period"] == "2026-06"

    emp_results = (
        (
            await session.execute(
                sa.select(payroll_employee_results).where(
                    payroll_employee_results.c.run_version_id == result["version_id"]
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(emp_results) == 1
    assert emp_results[0]["employee_number"] == "E-CALC-1"
    assert emp_results[0]["net_payable"] == Decimal("51000.00")

    lines = (
        (
            await session.execute(
                sa.select(payroll_result_lines)
                .where(payroll_result_lines.c.employee_result_id == emp_results[0]["id"])
                .order_by(payroll_result_lines.c.sequence)
            )
        )
        .mappings()
        .all()
    )
    codes = {row["component_code"] for row in lines}
    assert {
        "BASIC",
        "FIXED_ALLOWANCE",
        "HBA_INSTALLMENT",
        "ACCOMMODATION_LICENSE_FEE",
        "FOREGONE_HRA",
    } <= codes
    for row in lines:
        assert "rounded_value" in row["trace"]
        assert row["trace"]["engine_version"] == result["engine_version"]
        assert row["trace"]["calculator_kind"]

    allowance_line = next(r for r in lines if r["component_code"] == "FIXED_ALLOWANCE")
    assert allowance_line["amount"] == Decimal("2500.00")

    foregone = next(r for r in lines if r["component_code"] == "FOREGONE_HRA")
    assert foregone["trace"]["classification"] == "informational"
    assert foregone["amount"] == Decimal("2500.00")

    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    assert run.status == "calculated"
    assert run.current_version_id == result["version_id"]
    assert run.lock_version == 1


@pytest.mark.asyncio
async def test_recalculate_same_hash_new_version(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    first = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    second = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    assert first["content_hash"] == second["content_hash"]
    assert first["version_number"] == 1
    assert second["version_number"] == 2
    assert first["version_id"] != second["version_id"]

    await _bind(session, world["org_id"], world["user_id"])
    versions = (
        (
            await session.execute(
                sa.select(payroll_run_versions.c.version_number)
                .where(payroll_run_versions.c.run_id == world["run_id"])
                .order_by(payroll_run_versions.c.version_number)
            )
        )
        .scalars()
        .all()
    )
    assert list(versions) == [1, 2]


@pytest.mark.asyncio
async def test_override_changes_line_amount(session):
    world = await _seed_world(session)

    await _bind(session, world["org_id"], world["user_id"])
    override = await session.get(PayrollRunInput, world["override_id"])
    assert override is not None
    await session.delete(override)
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    baseline = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert baseline["totals"]["earnings_total"] == "52000.00"
    assert baseline["totals"]["net_payable"] == "50500.00"

    await _bind(session, world["org_id"], world["user_id"])
    session.add(
        PayrollRunInput(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            employee_id=world["employee_id"],
            component_code="FIXED_ALLOWANCE",
            input_kind="override",
            amount=Decimal("3000.00"),
            reason="Raised override",
            created_by=world["user_id"],
            updated_by=world["user_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    overridden = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert overridden["totals"]["earnings_total"] == "53000.00"
    assert overridden["totals"]["net_payable"] == "51500.00"
    assert overridden["content_hash"] != baseline["content_hash"]


@pytest.mark.asyncio
async def test_wrong_status_raises_conflict(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.status = "submitted"
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="cannot be calculated"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_immutable_version_row_rejects_update(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(DBAPIError, match="(?i)accord: UPDATE/DELETE forbidden"):
        await session.execute(
            sa.update(payroll_run_versions)
            .where(payroll_run_versions.c.id == result["version_id"])
            .values(engine_version="tampered")
        )
        await session.flush()
