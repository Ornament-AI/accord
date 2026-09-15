"""Unit/integration tests for pay-setup versioning helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.employees import Employee
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.platform import AuditEvent
from app.schemas.pay_setup import (
    AccommodationChargeInput,
    AccommodationChargeVersionCreate,
    AccommodationCreate,
    AccommodationUpdate,
    AdvanceCreate,
    AdvanceInstallmentInput,
    AdvanceInstallmentVersionCreate,
    AdvanceType,
    ComponentRateVersionCreate,
    CalcKind,
    Classification,
    PayComponentCreate,
    PayComponentUpdate,
    QuartersLocation,
    RecurringInstructionCreate,
    RecurringInstructionVersionCreate,
    RoundingRule,
)
from app.services import pay_setup as pay_setup_service
from app.services.versioning import insert_version, terminate_open_version
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


def _rate_payload(*, calc_kind: str = "fixed_recurring_amount", amount: str = "1000.00") -> dict:
    return {
        "calc_kind": calc_kind,
        "rounding_rule": "ROUND_HALF_UP_RUPEE",
        "amount": Decimal(amount),
        "rate": None,
        "basis": None,
    }


@pytest.mark.asyncio
async def test_insert_version_clip_and_insert_happy_path(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="BASIC",
            name="Basic Pay",
            classification="earning",
        )
        session.add(component)
        await session.flush()
        header_id = component.id

        first = await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=header_id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )
        second = await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=header_id,
            effective_from=date(2026, 4, 1),
            created_by=user.id,
            values=_rate_payload(amount="1200.00"),
            change_reason=None,
        )

    stmt = (
        sa.select(component_rate_versions)
        .where(component_rate_versions.c.header_id == header_id)
        .order_by(sa.func.lower(component_rate_versions.c.validity))
    )
    rows = (await session.execute(stmt)).mappings().all()
    assert len(rows) == 2

    first_from = rows[0]["validity"].lower
    first_to = rows[0]["validity"].upper
    assert first_from == date(2026, 1, 1)
    assert first_to == date(2026, 4, 1)
    assert rows[0]["id"] == first["id"]

    second_from = rows[1]["validity"].lower
    second_to = rows[1]["validity"].upper
    assert second_from == date(2026, 4, 1)
    assert second_to is None or not hasattr(second_to, "year")
    assert rows[1]["id"] == second["id"]


@pytest.mark.asyncio
async def test_insert_version_conflict_when_effective_from_not_after_open_lower(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="DA",
            name="Dearness Allowance",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )

        with pytest.raises(ConflictError, match="effective_from must be after"):
            await insert_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                effective_from=date(2026, 1, 1),
                created_by=user.id,
                values=_rate_payload(amount="1100.00"),
                change_reason=None,
            )


@pytest.mark.asyncio
async def test_terminate_open_version_clips_without_insert(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="HRA",
            name="House Rent Allowance",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )
        terminated = await terminate_open_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            end_on=date(2026, 6, 1),
        )

    upper = terminated["validity"].upper
    assert upper == date(2026, 6, 1)

    header_id = terminated["header_id"]
    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(component_rate_versions)
        .where(component_rate_versions.c.header_id == header_id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_terminate_open_version_conflict_when_no_open_version(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="TA",
            name="Transport Allowance",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        with pytest.raises(ConflictError, match="No open version exists"):
            await terminate_open_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                end_on=date(2026, 6, 1),
            )


@pytest.mark.asyncio
async def test_terminate_open_version_validation_when_end_on_not_after_start(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="MED",
            name="Medical",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )

        with pytest.raises(ValidationError, match="end_on must be after"):
            await terminate_open_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                end_on=date(2026, 1, 1),
            )


def test_component_rate_version_create_rejects_non_string_money():
    with pytest.raises(PydanticValidationError):
        ComponentRateVersionCreate.model_validate(
            {
                "effective_from": "2026-01-01",
                "calc_kind": "fixed_recurring_amount",
                "rounding_rule": "ROUND_HALF_UP_RUPEE",
                "amount": 1000.00,
            }
        )


# --- T1.13: mutation audit events -------------------------------------------


async def _audit_events(
    session: AsyncSession, *, organization_id, command: str, entity_id=None
) -> list[AuditEvent]:
    stmt = (
        sa.select(AuditEvent)
        .where(
            AuditEvent.organization_id == organization_id,
            AuditEvent.command == command,
        )
        .order_by(AuditEvent.created_at, AuditEvent.id)
    )
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    return list((await session.execute(stmt)).scalars().all())


async def _service_world(session: AsyncSession):
    org = await seed_organization(session, name="PS Org", slug=f"ps-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"ps_{uuid4().hex[:10]}")
    employee = Employee(organization_id=org.id, employee_number=f"E-{uuid4().hex[:6]}")
    session.add(employee)
    await session.commit()
    await session.begin()
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    return org, user, employee


@pytest.mark.asyncio
async def test_pay_component_create_update_and_rate_version_audit(session):
    org, user, _employee = await _service_world(session)

    component = await pay_setup_service.create_pay_component(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        body=PayComponentCreate(
            code="SVC_BONUS",
            name="Service Bonus",
            classification=Classification.EARNING,
        ),
    )

    create_events = await _audit_events(
        session,
        organization_id=org.id,
        command="pay_component.create",
        entity_id=component["id"],
    )
    assert len(create_events) == 1
    event = create_events[0]
    assert event.entity_type == "pay_component"
    assert event.event_kind == "mutation"
    assert event.actor_user_id == user.id
    assert event.before_state == {}
    assert event.after_state["code"] == "SVC_BONUS"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await pay_setup_service.update_pay_component(
        session,
        organization_id=org.id,
        component_id=component["id"],
        actor_user_id=user.id,
        body=PayComponentUpdate(name="Service Bonus (Revised)"),
    )
    update_events = await _audit_events(
        session,
        organization_id=org.id,
        command="pay_component.update",
        entity_id=component["id"],
    )
    assert len(update_events) == 1
    assert update_events[0].before_state["name"] == "Service Bonus"
    assert update_events[0].after_state["name"] == "Service Bonus (Revised)"
    assert update_events[0].summary["updated_fields"] == ["name"]

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    version = await pay_setup_service.create_component_rate_version(
        session,
        organization_id=org.id,
        component_id=component["id"],
        created_by=user.id,
        body=ComponentRateVersionCreate(
            effective_from=date(2026, 1, 1),
            calc_kind=CalcKind.FIXED_RECURRING_AMOUNT,
            amount="1500.00",
            rounding_rule=RoundingRule.ROUND_HALF_UP_RUPEE,
            change_reason="Initial rate",
        ),
    )
    rate_events = await _audit_events(
        session,
        organization_id=org.id,
        command="pay_component.rate_version.append",
        entity_id=component["id"],
    )
    assert len(rate_events) == 1
    event = rate_events[0]
    assert event.entity_type == "pay_component"
    assert event.before_state == {}
    assert event.after_state["amount"] == "1500.00"
    assert event.after_state["effective_from"] == "2026-01-01"
    assert event.summary["version_id"] == str(version["id"])
    assert event.summary["change_reason"] == "Initial rate"


@pytest.mark.asyncio
async def test_recurring_instruction_create_and_terminate_audit(session):
    org, user, employee = await _service_world(session)
    component = PayComponent(
        organization_id=org.id,
        code="SVC_REC",
        name="Recurring",
        classification="earning",
    )
    session.add(component)
    await session.commit()
    await session.begin()
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)

    instruction = await pay_setup_service.create_recurring_instruction(
        session,
        organization_id=org.id,
        employee_id=employee.id,
        created_by=user.id,
        body=RecurringInstructionCreate(
            component_id=component.id,
            effective_from=date(2026, 1, 1),
            amount="2000.00",
        ),
    )
    create_events = await _audit_events(
        session,
        organization_id=org.id,
        command="recurring_instruction.create",
        entity_id=instruction["id"],
    )
    assert len(create_events) == 1
    event = create_events[0]
    assert event.entity_type == "recurring_instruction"
    assert event.before_state == {}
    assert event.after_state["instruction"]["employee_id"] == str(employee.id)
    assert event.after_state["version"]["amount"] == "2000.00"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await pay_setup_service.create_recurring_instruction_version(
        session,
        organization_id=org.id,
        instruction_id=instruction["id"],
        created_by=user.id,
        body=RecurringInstructionVersionCreate(
            end_on=date(2026, 6, 1),
            change_reason="Stop allowance",
        ),
    )
    term_events = await _audit_events(
        session,
        organization_id=org.id,
        command="recurring_instruction.version.terminate",
        entity_id=instruction["id"],
    )
    assert len(term_events) == 1
    event = term_events[0]
    assert event.before_state["effective_to"] is None
    assert event.before_state["amount"] == "2000.00"
    assert event.after_state["effective_to"] == "2026-06-01"
    assert event.summary["end_on"] == "2026-06-01"


@pytest.mark.asyncio
async def test_advance_create_and_installment_version_audit(session):
    org, user, employee = await _service_world(session)

    advance = await pay_setup_service.create_advance(
        session,
        organization_id=org.id,
        employee_id=employee.id,
        created_by=user.id,
        body=AdvanceCreate(
            advance_type=AdvanceType.HBA,
            principal="12000.00",
            sanctioned_on=date(2026, 1, 1),
            installment=AdvanceInstallmentInput(
                installment_amount="1000.00",
                installments_total=12,
                installments_recovered_opening=0,
                effective_from=date(2026, 1, 1),
            ),
        ),
    )
    create_events = await _audit_events(
        session,
        organization_id=org.id,
        command="advance_account.create",
        entity_id=advance["id"],
    )
    assert len(create_events) == 1
    event = create_events[0]
    assert event.entity_type == "advance_account"
    assert event.before_state == {}
    assert event.after_state["account"]["principal"] == "12000.00"
    assert event.after_state["installment_version"]["installment_amount"] == "1000.00"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await pay_setup_service.create_advance_installment_version(
        session,
        organization_id=org.id,
        advance_id=advance["id"],
        created_by=user.id,
        body=AdvanceInstallmentVersionCreate(
            effective_from=date(2026, 4, 1),
            installment_amount="1500.00",
            installments_total=8,
            installments_recovered_opening=0,
            change_reason="Reschedule",
        ),
    )
    append_events = await _audit_events(
        session,
        organization_id=org.id,
        command="advance_account.installment_version.append",
        entity_id=advance["id"],
    )
    assert len(append_events) == 1
    event = append_events[0]
    assert event.before_state["installment_amount"] == "1000.00"
    assert event.before_state["effective_to"] is None
    assert event.after_state["installment_amount"] == "1500.00"
    assert event.after_state["effective_from"] == "2026-04-01"


@pytest.mark.asyncio
async def test_accommodation_create_update_and_charge_terminate_audit(session):
    org, user, employee = await _service_world(session)

    assignment = await pay_setup_service.create_accommodation(
        session,
        organization_id=org.id,
        employee_id=employee.id,
        created_by=user.id,
        body=AccommodationCreate(
            quarters_location=QuartersLocation.WORLI,
            quarters_identifier="W-1",
            charge=AccommodationChargeInput(
                license_fee="400.00",
                house_rent="300.00",
                service_charge="100.00",
                effective_from=date(2026, 1, 1),
            ),
        ),
    )
    create_events = await _audit_events(
        session,
        organization_id=org.id,
        command="accommodation_assignment.create",
        entity_id=assignment["id"],
    )
    assert len(create_events) == 1
    event = create_events[0]
    assert event.entity_type == "accommodation_assignment"
    assert event.before_state == {}
    assert event.after_state["assignment"]["quarters_identifier"] == "W-1"
    assert event.after_state["charge_version"]["license_fee"] == "400.00"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await pay_setup_service.update_accommodation(
        session,
        organization_id=org.id,
        assignment_id=assignment["id"],
        actor_user_id=user.id,
        body=AccommodationUpdate(quarters_identifier="W-2"),
    )
    update_events = await _audit_events(
        session,
        organization_id=org.id,
        command="accommodation_assignment.update",
        entity_id=assignment["id"],
    )
    assert len(update_events) == 1
    assert update_events[0].before_state["quarters_identifier"] == "W-1"
    assert update_events[0].after_state["quarters_identifier"] == "W-2"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await pay_setup_service.create_accommodation_charge_version(
        session,
        organization_id=org.id,
        assignment_id=assignment["id"],
        created_by=user.id,
        body=AccommodationChargeVersionCreate(end_on=date(2026, 6, 1)),
    )
    term_events = await _audit_events(
        session,
        organization_id=org.id,
        command="accommodation_assignment.charge_version.terminate",
        entity_id=assignment["id"],
    )
    assert len(term_events) == 1
    event = term_events[0]
    assert event.before_state["effective_to"] is None
    assert event.after_state["effective_to"] == "2026-06-01"


@pytest.mark.asyncio
async def test_report_configuration_upsert_audit(session):
    org, user, _employee = await _service_world(session)

    await pay_setup_service.upsert_report_configuration(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        key="bill_format",
        value={"layout": "a4"},
    )
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await pay_setup_service.upsert_report_configuration(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        key="bill_format",
        value={"layout": "a3"},
    )

    events = await _audit_events(
        session, organization_id=org.id, command="report_configuration.upsert"
    )
    assert len(events) == 2
    created, updated = events
    assert created.entity_type == "report_configuration"
    assert created.before_state == {}
    assert created.after_state["value"] == {"layout": "a4"}
    assert updated.before_state["value"] == {"layout": "a4"}
    assert updated.after_state["value"] == {"layout": "a3"}
    assert updated.entity_id == created.entity_id
