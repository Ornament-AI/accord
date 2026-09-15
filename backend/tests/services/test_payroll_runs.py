"""Service tests for payroll period/run/draft-input mutations (T1.13)."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employees import Employee
from app.models.pay_components import PayComponent
from app.models.platform import AuditEvent
from app.schemas.payroll_runs import (
    InputKind,
    PayrollPeriodCreate,
    PayrollRunCreate,
    PayrollRunInputUpsert,
)
from app.services import payroll_runs as payroll_runs_service
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


async def _world(session: AsyncSession):
    org = await seed_organization(session, name="Runs Org", slug=f"runs-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"runs_{uuid4().hex[:10]}")
    employee = Employee(organization_id=org.id, employee_number=f"E-{uuid4().hex[:6]}")
    component = PayComponent(
        organization_id=org.id,
        code="SVC_ADJ",
        name="Adjustment",
        classification="gross_adjustment",
    )
    session.add_all([employee, component])
    await session.commit()
    await session.begin()
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    return org, user, employee


async def _audit(session: AsyncSession, *, organization_id, command: str, entity_id) -> AuditEvent:
    return (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.command == command,
                AuditEvent.entity_id == entity_id,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_create_period_and_run_audit(session):
    org, user, _employee = await _world(session)

    period = await payroll_runs_service.create_period(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        body=PayrollPeriodCreate(period_year=2026, period_month=6),
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="payroll_period.create",
        entity_id=period["id"],
    )
    assert event.entity_type == "payroll_period"
    assert event.actor_user_id == user.id
    assert event.before_state == {}
    assert event.after_state["status"] == "open"
    assert event.after_state["period_month"] == 6

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    run = await payroll_runs_service.create_run(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        body=PayrollRunCreate(period_id=period["id"]),
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="payroll_run.create",
        entity_id=run["id"],
    )
    assert event.entity_type == "payroll_run"
    assert event.before_state == {}
    assert event.after_state["status"] == "draft"


@pytest.mark.asyncio
async def test_run_input_upsert_and_delete_audit(session):
    org, user, employee = await _world(session)

    period = await payroll_runs_service.create_period(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        body=PayrollPeriodCreate(period_year=2026, period_month=6),
    )
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    run = await payroll_runs_service.create_run(
        session,
        organization_id=org.id,
        actor_user_id=user.id,
        body=PayrollRunCreate(period_id=period["id"]),
    )

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    created = await payroll_runs_service.upsert_run_input(
        session,
        organization_id=org.id,
        run_id=run["id"],
        employee_id=employee.id,
        component_code="SVC_ADJ",
        actor_user_id=user.id,
        body=PayrollRunInputUpsert(
            input_kind=InputKind.ONE_TIME,
            amount="500.00",
            reason="Arrears",
        ),
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="payroll_run_input.upsert",
        entity_id=created["id"],
    )
    assert event.entity_type == "payroll_run_input"
    assert event.before_state == {}
    assert event.after_state["amount"] == "500.00"
    assert event.after_state["version"] == 0
    assert event.summary["run_id"] == str(run["id"])
    assert event.summary["component_code"] == "SVC_ADJ"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await payroll_runs_service.upsert_run_input(
        session,
        organization_id=org.id,
        run_id=run["id"],
        employee_id=employee.id,
        component_code="SVC_ADJ",
        actor_user_id=user.id,
        body=PayrollRunInputUpsert(
            input_kind=InputKind.ONE_TIME,
            amount="750.00",
            reason="Arrears revised",
            expected_version=0,
        ),
    )
    events = list(
        (
            await session.execute(
                sa.select(AuditEvent)
                .where(
                    AuditEvent.organization_id == org.id,
                    AuditEvent.command == "payroll_run_input.upsert",
                    AuditEvent.entity_id == created["id"],
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2
    assert events[1].before_state["amount"] == "500.00"
    assert events[1].after_state["amount"] == "750.00"
    assert events[1].after_state["version"] == 1

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await payroll_runs_service.delete_run_input(
        session,
        organization_id=org.id,
        run_id=run["id"],
        input_id=created["id"],
        actor_user_id=user.id,
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="payroll_run_input.delete",
        entity_id=created["id"],
    )
    assert event.before_state["amount"] == "750.00"
    assert event.after_state == {}
    assert event.summary["component_code"] == "SVC_ADJ"
