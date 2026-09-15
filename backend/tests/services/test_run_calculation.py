"""Service tests for payroll run calculate command."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import Range

from app.exceptions import ConflictError, ValidationError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import (
    Employee,
    employee_bank_account_versions,
    employee_pay_versions,
    employee_posting_versions,
    employee_profile_versions,
)
from app.models.org_structure import Office, Post
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunInput,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.platform import AuditEvent, PayrollApproval
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning
from app.services.report_readiness import v3_report_readiness_issues
from app.services.run_calculation import calculate_run_command
from app.services.run_posting import post_run
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

    org = await seed_organization(session, name="Calc Org", slug=f"calc-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"calc_{uuid4().hex[:10]}")
    await session.commit()

    await _bind(session, org.id, user.id)

    employee = Employee(organization_id=org.id, employee_number="E-CALC-1")
    office = Office(organization_id=org.id, name="Payroll Office", jurisdiction="mumbai")
    post = Post(
        organization_id=org.id,
        designation="Accounts Officer",
        class_="Class II",
    )
    pay_bill_post = Post(
        organization_id=org.id,
        designation="Combined Accounts Establishment",
        pay_bill_heading="Accounts and Audit Establishment",
        class_="Class II",
        display_order=10,
    )
    session.add_all([employee, office, post, pay_bill_post])
    await session.flush()

    await versioning.insert_version(
        session,
        employee_posting_versions,
        organization_id=org.id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={
            "office_id": office.id,
            "post_id": post.id,
            "pay_bill_post_id": pay_bill_post.id,
        },
        change_reason=None,
        created_by=user.id,
    )

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
            "payroll_export_remark": "Recovery adjusted manually",
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
        register_column="basic_pay",
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
        quarters_address="1 Government Colony, Mumbai",
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
            "house_rent": Decimal("300.00"),
            "service_charge": Decimal("100.00"),
            "parking_charge": Decimal("75.00"),
            "additional_parking_charge": Decimal("25.00"),
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
        service_period_start=date(2026, 1, 1),
        service_period_end=date(2026, 6, 30),
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(override)
    await session.commit()

    return {
        "org_id": org.id,
        "user_id": user.id,
        "employee_id": employee.id,
        "post_id": post.id,
        "pay_bill_post_id": pay_bill_post.id,
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
    basic_catalog = next(
        row for row in version["inputs_snapshot"]["component_catalog"] if row["code"] == "BASIC"
    )
    assert basic_catalog["register_column"] == "basic_pay"
    employee_input = version["inputs_snapshot"]["employees"][0]
    allowance_input = next(
        item for item in employee_input["components"] if item["component_code"] == "FIXED_ALLOWANCE"
    )
    assert allowance_input["service_period"] == "2026-01-01/2026-06-30"
    identity = version["inputs_snapshot"]["employee_identity"][str(world["employee_id"])]
    assert identity["post"] == {
        "id": str(world["post_id"]),
        "designation": "Accounts Officer",
        "class_name": "Class II",
        "sanctioned_strength": None,
        "vacant_count": None,
        "pay_scale": None,
        "display_order": None,
    }
    assert identity["pay_bill_post"] == {
        "id": str(world["pay_bill_post_id"]),
        "heading": "Accounts and Audit Establishment",
        "designation": "Combined Accounts Establishment",
        "sanctioned_strength": None,
        "vacant_count": None,
        "pay_scale": None,
        "display_order": 10,
    }
    assert "epf_number" in identity
    assert identity["payroll_export_remark"] == "Recovery adjusted manually"
    recovery_sources = version["inputs_snapshot"]["recovery_sources"]
    advance_source = next(iter(recovery_sources["advance_installments"].values()))
    assert advance_source["sanctioned_on"] == "2026-01-01"
    assert advance_source["installment_amount"] == "1000.00"
    accommodation_source = next(iter(recovery_sources["accommodation_charges"].values()))
    assert accommodation_source["quarters_address"] == "1 Government Colony, Mumbai"
    assert accommodation_source["house_rent"] == "300.00"
    assert accommodation_source["additional_parking_charge"] == "25.00"

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
    assert allowance_line["trace"]["service_period"] == "2026-01-01/2026-06-30"
    assert allowance_line["trace"]["reason"] == "June override"

    foregone = next(r for r in lines if r["component_code"] == "FOREGONE_HRA")
    assert foregone["trace"]["classification"] == "informational"
    assert foregone["amount"] == Decimal("2500.00")

    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    assert run.status == "calculated"
    assert run.current_version_id == result["version_id"]
    assert run.lock_version == 1

    audit = (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.entity_id == world["run_id"],
                AuditEvent.command == "payroll_run.calculate",
            )
        )
    ).scalar_one()
    assert audit.entity_type == "payroll_run"
    assert audit.event_kind == "mutation"
    assert audit.actor_user_id == world["user_id"]
    assert audit.before_state["status"] == "draft"
    assert audit.before_state["current_version_id"] is None
    assert audit.after_state["status"] == "calculated"
    assert audit.after_state["current_version_id"] == str(result["version_id"])
    assert audit.summary["version_number"] == 1
    assert audit.summary["content_hash"] == result["content_hash"]


@pytest.mark.asyncio
async def test_calculated_readiness_uses_selected_pay_bill_group(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    await _bind(session, world["org_id"], world["user_id"])

    issues = await v3_report_readiness_issues(
        session,
        organization_id=world["org_id"],
        posted_run_id=world["run_id"],
    )

    assert not any(issue["code"].startswith("post_") for issue in issues)


@pytest.mark.asyncio
async def test_calculate_snapshots_only_primary_salary_bank_account(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await session.execute(
        sa.insert(employee_bank_account_versions),
        [
            {
                "organization_id": world["org_id"],
                "header_id": world["employee_id"],
                "validity": Range(date(2026, 1, 1), None, bounds="[)"),
                "account_number": "PRIMARY-001",
                "ifsc": "PRIMARY0001",
                "bank_name": "Primary Bank",
                "branch": "Payroll",
                "is_primary_salary": True,
                "created_by": world["user_id"],
            },
            {
                "organization_id": world["org_id"],
                "header_id": world["employee_id"],
                "validity": Range(date(2026, 1, 1), None, bounds="[)"),
                "account_number": "SECONDARY-002",
                "ifsc": "SECOND0002",
                "bank_name": "Secondary Bank",
                "branch": "Savings",
                "is_primary_salary": False,
                "created_by": world["user_id"],
            },
        ],
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    inputs_snapshot = (
        await session.execute(
            sa.select(payroll_run_versions.c.inputs_snapshot).where(
                payroll_run_versions.c.id == result["version_id"]
            )
        )
    ).scalar_one()
    identity = inputs_snapshot["employee_identity"][str(world["employee_id"])]
    assert identity["bank_account_number"] == "PRIMARY-001"
    assert identity["bank_ifsc"] == "PRIMARY0001"
    assert identity["bank_name"] == "Primary Bank"


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
async def test_amount_override_replaces_rate_based_calculation_with_direct_amount(session):
    world = await _seed_world(session)

    await _bind(session, world["org_id"], world["user_id"])
    roster_row = (
        await session.execute(
            sa.select(PayrollRunEmployee)
            .where(PayrollRunEmployee.run_id == world["run_id"])
            .where(PayrollRunEmployee.employee_id == world["employee_id"])
        )
    ).scalar_one()
    roster_row.da_percent = Decimal("10.00")
    session.add(
        PayrollRunInput(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            employee_id=world["employee_id"],
            component_code="DA",
            input_kind="override",
            amount=Decimal("6000.00"),
            reason="Use the sanctioned fixed amount",
            created_by=world["user_id"],
            updated_by=world["user_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # BASIC 50000 + allowance override 2500 + direct DA override 6000.
    assert result["totals"]["earnings_total"] == "58500.00"
    assert result["totals"]["net_payable"] == "57000.00"


@pytest.mark.asyncio
async def test_rate_override_rejects_amount_based_component(session):
    world = await _seed_world(session)

    await _bind(session, world["org_id"], world["user_id"])
    override = await session.get(PayrollRunInput, world["override_id"])
    assert override is not None
    override.amount = None
    override.rate = Decimal("0.05")
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ValidationError, match="requires an existing rate-based component"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_rate_override_updates_existing_rate_based_component(session):
    world = await _seed_world(session)

    await _bind(session, world["org_id"], world["user_id"])
    roster_row = (
        await session.execute(
            sa.select(PayrollRunEmployee)
            .where(PayrollRunEmployee.run_id == world["run_id"])
            .where(PayrollRunEmployee.employee_id == world["employee_id"])
        )
    ).scalar_one()
    roster_row.da_percent = Decimal("10.00")
    session.add(
        PayrollRunInput(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            employee_id=world["employee_id"],
            component_code="DA",
            input_kind="override",
            rate=Decimal("0.20"),
            reason="Use the approved DA rate",
            created_by=world["user_id"],
            updated_by=world["user_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # DA remains percentage-based: 20% of BASIC 50000 = 10000.
    assert result["totals"]["earnings_total"] == "62500.00"
    assert result["totals"]["net_payable"] == "61000.00"


@pytest.mark.asyncio
async def test_draft_without_roster_rejects_calculate(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.roster_initialized = False
    await session.execute(
        sa.delete(PayrollRunEmployee).where(
            PayrollRunEmployee.run_id == world["run_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="roster must be saved"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_roster_prorates_basic_and_applies_inline_payroll_values(session):
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    roster = (
        await session.execute(
            sa.select(PayrollRunEmployee).where(
                PayrollRunEmployee.run_id == world["run_id"],
                PayrollRunEmployee.employee_id == world["employee_id"],
            )
        )
    ).scalar_one()
    roster.payable_days = Decimal("15.00")
    roster.da_percent = Decimal("50.0000")
    roster.da_difference = Decimal("100.00")
    roster.hra_percent = Decimal("20.0000")
    roster.transport_amount = Decimal("200.00")
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # June has 30 days: BASIC 25,000; DA 12,500; HRA 5,000; transport 200;
    # existing allowance override 2,500; DA difference is a gross adjustment.
    assert result["totals"]["earnings_total"] == "45200.00"
    assert result["totals"]["gross_adjustment_total"] == "100.00"
    assert result["totals"]["gross_total"] == "45300.00"
    assert result["totals"]["net_payable"] == "43800.00"


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


@pytest.mark.asyncio
async def test_calculate_rejects_empty_saved_roster(session):
    """A saved-but-empty roster fails fast instead of producing a
    zero-employee calculated version."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await session.execute(
        sa.delete(PayrollRunEmployee).where(
            PayrollRunEmployee.run_id == world["run_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="roster is empty"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_calculate_rejects_roster_member_without_active_profile(session):
    """Every saved roster member must resolve to a month-end profile; silent
    partial calculation is forbidden."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])

    ghost = Employee(organization_id=world["org_id"], employee_number="E-CALC-GHOST")
    session.add(ghost)
    await session.flush()
    session.add(
        PayrollRunEmployee(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            employee_id=ghost.id,
            payable_days=Decimal("30.00"),
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="E-CALC-GHOST"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_calculate_blocks_negative_amount_finding(session):
    """T1.4: ``validate_run_inputs`` runs before the engine — a signed
    recurring-instruction amount resolving to a non-adjustment calc kind is
    an error-severity finding and blocks calculation."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    # Remove the seeded override first: it would replace the FIXED_ALLOWANCE
    # component wholesale and mask the negative instruction amount.
    seeded_override = await session.get(PayrollRunInput, world["override_id"])
    assert seeded_override is not None
    await session.delete(seeded_override)
    instruction_id = (
        await session.execute(
            sa.select(RecurringInstruction.id).where(
                RecurringInstruction.organization_id == world["org_id"],
                RecurringInstruction.employee_id == world["employee_id"],
            )
        )
    ).scalar_one()
    # The row-level CHECK stays signed (the calc kind lives on the
    # component's rate version), so this insert succeeds; the kind rule is
    # enforced by validate_run_inputs at calculate time.
    await versioning.insert_version(
        session,
        recurring_instruction_versions,
        organization_id=world["org_id"],
        header_id=instruction_id,
        effective_from=date(2026, 3, 1),
        values={"amount": Decimal("-100.00"), "rate": None, "reason": "bad"},
        change_reason=None,
        created_by=world["user_id"],
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ValidationError, match="failed validation") as excinfo:
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )
    codes = {f["code"] for f in excinfo.value.details["findings"]}
    assert "negative_amount" in codes


@pytest.mark.asyncio
async def test_one_time_negative_input_remains_allowed(session):
    """T1.4 carve-out: a negative ``one_time`` run input is a deliberate
    prior-period recovery and must still calculate."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    session.add(
        PayComponent(
            organization_id=world["org_id"],
            code="PRIOR_RECOVERY",
            name="Prior Period Recovery",
            classification="gross_adjustment",
        )
    )
    session.add(
        PayrollRunInput(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            employee_id=world["employee_id"],
            component_code="PRIOR_RECOVERY",
            input_kind="one_time",
            amount=Decimal("-500.00"),
            reason="Recover prior overpayment",
            created_by=world["user_id"],
            updated_by=world["user_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    assert result["totals"]["gross_adjustment_total"] == "-500.00"
    assert result["totals"]["gross_total"] == "52000.00"
    assert result["totals"]["net_payable"] == "50500.00"


@pytest.mark.asyncio
async def test_override_for_unresolved_component_code_conflicts(session):
    """M-data-5: an override that resolves to no calculated component must
    fail loudly instead of silently creating a gross adjustment."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    session.add(
        PayrollRunInput(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            employee_id=world["employee_id"],
            component_code="NO_SUCH_COMPONENT",
            input_kind="override",
            amount=Decimal("10.00"),
            reason="typo",
            created_by=world["user_id"],
            updated_by=world["user_id"],
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="resolved to nothing"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


@pytest.mark.asyncio
async def test_cross_kind_input_code_collision_conflicts(session):
    """M-data-9: a ``one_time`` input may not silently coexist with an
    ``override`` input for the same component code."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    # A catalog code with no resolved component: the one_time row creates it
    # first (sorted before "override"), then the override row must conflict.
    session.add(
        PayComponent(
            organization_id=world["org_id"],
            code="COLLIDE_ADJ",
            name="Collision Probe",
            classification="gross_adjustment",
        )
    )
    session.add_all(
        [
            PayrollRunInput(
                organization_id=world["org_id"],
                run_id=world["run_id"],
                employee_id=world["employee_id"],
                component_code="COLLIDE_ADJ",
                input_kind="one_time",
                amount=Decimal("50.00"),
                reason="colliding one_time",
                created_by=world["user_id"],
                updated_by=world["user_id"],
            ),
            PayrollRunInput(
                organization_id=world["org_id"],
                run_id=world["run_id"],
                employee_id=world["employee_id"],
                component_code="COLLIDE_ADJ",
                input_kind="override",
                amount=Decimal("60.00"),
                reason="colliding override",
                created_by=world["user_id"],
                updated_by=world["user_id"],
            ),
        ]
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="already supplied"):
        await calculate_run_command(
            session,
            organization_id=world["org_id"],
            run_id=world["run_id"],
            user_id=world["user_id"],
        )


async def _version_component_codes(session: AsyncSession, version_id) -> set[str]:
    emp_result_id = (
        await session.execute(
            sa.select(payroll_employee_results.c.id).where(
                payroll_employee_results.c.run_version_id == version_id
            )
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                sa.select(payroll_result_lines.c.component_code).where(
                    payroll_result_lines.c.employee_result_id == emp_result_id
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def _advance_id(session: AsyncSession, world: dict):
    return (
        await session.execute(
            sa.select(AdvanceAccount.id).where(
                AdvanceAccount.organization_id == world["org_id"],
                AdvanceAccount.employee_id == world["employee_id"],
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_completed_recovery_emits_no_installment_line(session):
    """T1.6: once the derived recovered count reaches installments_total the
    recovery line stops being emitted."""
    world = await _seed_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    await versioning.insert_version(
        session,
        advance_installment_versions,
        organization_id=world["org_id"],
        header_id=await _advance_id(session, world),
        effective_from=date(2026, 3, 1),
        values={
            "installment_amount": Decimal("1000.00"),
            "installments_total": 12,
            "installments_recovered_opening": 12,
        },
        change_reason=None,
        created_by=world["user_id"],
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    codes = await _version_component_codes(session, result["version_id"])
    assert "HBA_INSTALLMENT" not in codes
    # Only the accommodation license fee remains as external recovery.
    assert result["totals"]["external_recovery_total"] == "500.00"
    assert result["totals"]["net_payable"] == "52000.00"


@pytest.mark.asyncio
async def test_posted_recovery_line_advances_derived_count(session):
    """T1.6: recovery progress derives from posted result lines citing the
    installment version — no mutable counter is touched. One remaining
    installment posted in June completes the series, so July emits none."""
    world = await _seed_world(session)

    # Leave exactly one installment outstanding (11 recovered of 12).
    await _bind(session, world["org_id"], world["user_id"])
    await versioning.insert_version(
        session,
        advance_installment_versions,
        organization_id=world["org_id"],
        header_id=await _advance_id(session, world),
        effective_from=date(2026, 3, 1),
        values={
            "installment_amount": Decimal("1000.00"),
            "installments_total": 12,
            "installments_recovered_opening": 11,
        },
        change_reason=None,
        created_by=world["user_id"],
    )
    await session.commit()

    # June: calculate -> approve -> post, emitting the final installment.
    await _bind(session, world["org_id"], world["user_id"])
    calc = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert "HBA_INSTALLMENT" in await _version_component_codes(session, calc["version_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.status = "approved"
    session.add(
        PayrollApproval(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            run_version_id=calc["version_id"],
            content_hash=calc["content_hash"],
            action="approve",
            actor_user_id=world["user_id"],
            reason="Looks good",
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # July: a fresh run over the same installment version derives
    # recovered = opening 11 + 1 posted = 12 -> complete, no line emitted.
    await _bind(session, world["org_id"], world["user_id"])
    july_period = PayrollPeriod(
        organization_id=world["org_id"],
        period_year=2026,
        period_month=7,
        status="open",
    )
    session.add(july_period)
    await session.flush()
    july_run = PayrollRun(
        organization_id=world["org_id"],
        period_id=july_period.id,
        status="draft",
    )
    session.add(july_run)
    await session.flush()
    session.add_all(
        initialize_run_roster(
            organization_id=world["org_id"],
            run=july_run,
            employee_ids=[world["employee_id"]],
            period_year=july_period.period_year,
            period_month=july_period.period_month,
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=july_run.id,
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    codes = await _version_component_codes(session, result["version_id"])
    assert "HBA_INSTALLMENT" not in codes


@pytest.mark.asyncio
async def test_recovery_progress_survives_installment_version_append(session):
    """Posted recoveries count across the whole version lineage (keyed by the
    advance account, not the version id). Appending a new installment version
    must not reset progress and re-recover already-posted installments."""
    world = await _seed_world(session)
    advance_id = await _advance_id(session, world)

    # One installment outstanding under the first version.
    await _bind(session, world["org_id"], world["user_id"])
    await versioning.insert_version(
        session,
        advance_installment_versions,
        organization_id=world["org_id"],
        header_id=advance_id,
        effective_from=date(2026, 3, 1),
        values={
            "installment_amount": Decimal("1000.00"),
            "installments_total": 12,
            "installments_recovered_opening": 11,
        },
        change_reason=None,
        created_by=world["user_id"],
    )
    await session.commit()

    # June: the final installment is posted under version 1.
    await _bind(session, world["org_id"], world["user_id"])
    calc = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )
    assert "HBA_INSTALLMENT" in await _version_component_codes(session, calc["version_id"])
    run = await session.get(PayrollRun, world["run_id"])
    assert run is not None
    run.status = "approved"
    session.add(
        PayrollApproval(
            organization_id=world["org_id"],
            run_id=world["run_id"],
            run_version_id=calc["version_id"],
            content_hash=calc["content_hash"],
            action="approve",
            actor_user_id=world["user_id"],
            reason="Looks good",
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    await post_run(
        session,
        organization_id=world["org_id"],
        run_id=world["run_id"],
        user_id=world["user_id"],
    )

    # July: the operator reschedules — a NEW installment version is appended
    # (the dialog prefills the same opening count). The v1 recovery must still
    # count toward the lineage total.
    await _bind(session, world["org_id"], world["user_id"])
    await versioning.insert_version(
        session,
        advance_installment_versions,
        organization_id=world["org_id"],
        header_id=advance_id,
        effective_from=date(2026, 7, 1),
        values={
            "installment_amount": Decimal("1000.00"),
            "installments_total": 12,
            "installments_recovered_opening": 11,
        },
        change_reason="Reschedule",
        created_by=world["user_id"],
    )
    july_period = PayrollPeriod(
        organization_id=world["org_id"],
        period_year=2026,
        period_month=7,
        status="open",
    )
    session.add(july_period)
    await session.flush()
    july_run = PayrollRun(
        organization_id=world["org_id"],
        period_id=july_period.id,
        status="draft",
    )
    session.add(july_run)
    await session.flush()
    session.add_all(
        initialize_run_roster(
            organization_id=world["org_id"],
            run=july_run,
            employee_ids=[world["employee_id"]],
            period_year=july_period.period_year,
            period_month=july_period.period_month,
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    result = await calculate_run_command(
        session,
        organization_id=world["org_id"],
        run_id=july_run.id,
        user_id=world["user_id"],
    )

    await _bind(session, world["org_id"], world["user_id"])
    codes = await _version_component_codes(session, result["version_id"])
    assert "HBA_INSTALLMENT" not in codes
