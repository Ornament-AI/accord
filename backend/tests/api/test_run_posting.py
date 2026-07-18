"""API tests for payroll run post / reverse commands.

Seam: submit/approve workflow is owned by a parallel lane. Tests insert
``PayrollApproval`` rows directly (and set run.status) to simulate
submit/approve without importing ``run_workflow``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.api.routes.payroll_runs import router as payroll_runs_router
from app.api.routes.run_commands import router as run_commands_router
from app.api.routes.run_posting import router as run_posting_router
from app.main import create_app
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import PayrollRun
from app.models.platform import AuditEvent, OutboxEvent, PayrollApproval
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_user,
    session_cookie_from_response,
)


def _posting_app():
    application = create_app()
    application.include_router(payroll_runs_router, prefix="/api")
    application.include_router(run_commands_router, prefix="/api")
    application.include_router(run_posting_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _posting_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_as_admin(client) -> tuple[UUID, UUID]:
    resp, cookie = await login_dev(client)
    assert resp.status_code in {200, 302}, resp.text
    assert cookie, "expected accord_session cookie from login"
    client.cookies.set("accord_session", cookie)

    slug = f"post-api-{uuid4().hex[:8]}"
    resp = await client.post("/api/organizations", json={"name": "Post API", "slug": slug})
    assert resp.status_code == 201, resp.text
    cookie = session_cookie_from_response(resp) or cookie
    client.cookies.set("accord_session", cookie)
    body = resp.json()
    return UUID(body["active_organization"]["id"]), UUID(body["id"])


async def _seed_calculate_world(session, *, org_id: UUID, user_id: UUID) -> UUID:
    if session.in_transaction():
        await session.rollback()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)

        employee = Employee(organization_id=org_id, employee_number=f"E-{uuid4().hex[:6]}")
        session.add(employee)
        await session.flush()

        await versioning.insert_version(
            session,
            employee_profile_versions,
            organization_id=org_id,
            header_id=employee.id,
            effective_from=date(2026, 1, 1),
            values={
                "name": "API Employee",
                "sevarth_id": f"SEV-{uuid4().hex[:8]}",
                "pan": "ABCDE1234F",
                "date_of_birth": date(1990, 1, 15),
                "date_of_joining": date(2015, 6, 1),
                "retirement_regime": "gpf",
                "gpf_jurisdiction": "mumbai",
                "pran": None,
                "gpf_account_number": "GPF1",
                "epf_number": None,
                "pension_account": None,
            },
            change_reason=None,
            created_by=user_id,
        )
        await versioning.insert_version(
            session,
            employee_pay_versions,
            organization_id=org_id,
            header_id=employee.id,
            effective_from=date(2026, 1, 1),
            values={
                "pay_matrix_level": "L10",
                "basic_pay": Decimal("50000.00"),
            },
            change_reason=None,
            created_by=user_id,
        )

        basic = PayComponent(
            organization_id=org_id,
            code="BASIC",
            name="Basic Pay",
            classification="earning",
        )
        allowance = PayComponent(
            organization_id=org_id,
            code="FIXED_ALLOWANCE",
            name="Fixed Allowance",
            classification="earning",
        )
        hba = PayComponent(
            organization_id=org_id,
            code="HBA_INSTALLMENT",
            name="HBA",
            classification="external_recovery",
        )
        license_fee = PayComponent(
            organization_id=org_id,
            code="ACCOMMODATION_LICENSE_FEE",
            name="License Fee",
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
                organization_id=org_id,
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
                created_by=user_id,
            )

        instruction = RecurringInstruction(
            organization_id=org_id,
            employee_id=employee.id,
            component_id=allowance.id,
        )
        session.add(instruction)
        await session.flush()
        await versioning.insert_version(
            session,
            recurring_instruction_versions,
            organization_id=org_id,
            header_id=instruction.id,
            effective_from=date(2026, 1, 1),
            values={"amount": Decimal("2000.00"), "rate": None, "reason": "Allowance"},
            change_reason=None,
            created_by=user_id,
        )

        advance = AdvanceAccount(
            organization_id=org_id,
            employee_id=employee.id,
            advance_type="hba",
            principal=Decimal("12000.00"),
            sanctioned_on=date(2026, 1, 1),
        )
        session.add(advance)
        await session.flush()
        await versioning.insert_version(
            session,
            advance_installment_versions,
            organization_id=org_id,
            header_id=advance.id,
            effective_from=date(2026, 1, 1),
            values={
                "installment_amount": Decimal("1000.00"),
                "installments_total": 12,
                "installments_recovered_opening": 0,
            },
            change_reason=None,
            created_by=user_id,
        )

        assignment = AccommodationAssignment(
            organization_id=org_id,
            employee_id=employee.id,
            quarters_location="mumbai",
            quarters_identifier="B-2",
        )
        session.add(assignment)
        await session.flush()
        await versioning.insert_version(
            session,
            accommodation_charge_versions,
            organization_id=org_id,
            header_id=assignment.id,
            effective_from=date(2026, 1, 1),
            values={
                "license_fee": Decimal("500.00"),
                "informational_hra_foregone": Decimal("2500.00"),
            },
            change_reason=None,
            created_by=user_id,
        )
        employee_id = employee.id

    return employee_id


async def _restore_admin_cookie(
    client, session, dev_settings, *, org_id: UUID, user_id: UUID
) -> None:
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=user_id,
        active_organization_id=org_id,
    )
    apply_session_cookie(client, cookie)


async def _prepare_approved_run(client, session, dev_settings) -> dict:
    org_id, user_id = await _create_org_as_admin(client)

    period = await client.post(
        "/api/payroll-periods",
        json={"period_year": 2026, "period_month": 6},
    )
    assert period.status_code == 201, period.text
    run = await client.post(
        "/api/payroll-runs",
        json={"period_id": period.json()["id"], "run_type": "regular"},
    )
    assert run.status_code == 201, run.text
    run_id = UUID(run.json()["id"])

    employee_id = await _seed_calculate_world(session, org_id=org_id, user_id=user_id)
    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)

    override = await client.put(
        f"/api/payroll-runs/{run_id}/inputs/{employee_id}/FIXED_ALLOWANCE",
        json={
            "input_kind": "override",
            "amount": "2500.00",
            "reason": "June override",
        },
    )
    assert override.status_code == 200, override.text

    calc = await client.post(f"/api/payroll-runs/{run_id}/calculate")
    assert calc.status_code == 200, calc.text
    calc_body = calc.json()

    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        await session.execute(
            sa.update(PayrollRun).where(PayrollRun.id == run_id).values(status="approved")
        )
        session.add(
            PayrollApproval(
                organization_id=org_id,
                run_id=run_id,
                run_version_id=UUID(calc_body["version_id"]),
                content_hash=calc_body["content_hash"],
                action="approve",
                actor_user_id=user_id,
                reason="OK",
            )
        )

    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)
    return {
        "org_id": org_id,
        "user_id": user_id,
        "run_id": run_id,
        "calc": calc_body,
    }


@pytest.mark.asyncio
async def test_post_happy_path(client, session, dev_settings):
    world = await _prepare_approved_run(client, session, dev_settings)
    run_id = world["run_id"]

    resp = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": f"post-{uuid4().hex}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(run_id)
    assert body["status"] == "posted"

    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(
            session, organization_id=world["org_id"], user_id=world["user_id"]
        )
        post_rows = (
            (
                await session.execute(
                    sa.select(PayrollApproval).where(
                        PayrollApproval.run_id == run_id,
                        PayrollApproval.action == "post",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(post_rows) == 1
        audits = (
            (
                await session.execute(
                    sa.select(AuditEvent).where(
                        AuditEvent.entity_id == run_id,
                        AuditEvent.command == "payroll_run.post",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        outbox = (
            (
                await session.execute(
                    sa.select(OutboxEvent).where(
                        OutboxEvent.organization_id == world["org_id"],
                        OutboxEvent.event_type == "payroll_run.posted",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(outbox) == 1


@pytest.mark.asyncio
async def test_post_idempotent_replay(client, session, dev_settings):
    world = await _prepare_approved_run(client, session, dev_settings)
    run_id = world["run_id"]
    key = f"post-idem-{uuid4().hex}"

    first = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(
            session, organization_id=world["org_id"], user_id=world["user_id"]
        )
        post_count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(PayrollApproval)
                .where(
                    PayrollApproval.run_id == run_id,
                    PayrollApproval.action == "post",
                )
            )
        ).scalar_one()
        assert post_count == 1
        audit_count = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == run_id,
                    AuditEvent.command == "payroll_run.post",
                )
            )
        ).scalar_one()
        assert audit_count == 1


@pytest.mark.asyncio
async def test_reverse_happy_path(client, session, dev_settings):
    world = await _prepare_approved_run(client, session, dev_settings)
    run_id = world["run_id"]

    posted = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": f"post-{uuid4().hex}"},
    )
    assert posted.status_code == 200, posted.text

    reversed_resp = await client.post(
        f"/api/payroll-runs/{run_id}/reverse",
        headers={"Idempotency-Key": f"rev-{uuid4().hex}"},
        json={"reason": "Correcting bank file"},
    )
    assert reversed_resp.status_code == 200, reversed_resp.text
    body = reversed_resp.json()
    assert body["status"] == "reversed"
    assert body["reversal_run_id"]


@pytest.mark.asyncio
async def test_reverse_without_reason_422(client, session, dev_settings):
    world = await _prepare_approved_run(client, session, dev_settings)
    run_id = world["run_id"]

    posted = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": f"post-{uuid4().hex}"},
    )
    assert posted.status_code == 200, posted.text

    missing = await client.post(
        f"/api/payroll-runs/{run_id}/reverse",
        headers={"Idempotency-Key": f"rev-{uuid4().hex}"},
        json={},
    )
    assert missing.status_code == 422

    empty = await client.post(
        f"/api/payroll-runs/{run_id}/reverse",
        headers={"Idempotency-Key": f"rev-{uuid4().hex}"},
        json={"reason": ""},
    )
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_post_capability_gate_approver_403(client, session, dev_settings):
    world = await _prepare_approved_run(client, session, dev_settings)
    run_id = world["run_id"]

    if session.in_transaction():
        await session.rollback()
    approver = await seed_user(session, email="approver-post@example.com", name="Approver")
    await seed_membership(
        session,
        organization_id=world["org_id"],
        user_id=approver.id,
        role="payroll_approver",
    )
    await session.commit()

    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=approver.id,
        active_organization_id=world["org_id"],
    )
    apply_session_cookie(client, cookie)

    resp = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": f"post-{uuid4().hex}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "urn:accord:capability:post_run"
