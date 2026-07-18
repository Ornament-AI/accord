"""API tests for payroll run workflow commands."""

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
from app.api.routes.run_workflow import router as run_workflow_router
from app.main import create_app
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.platform import PayrollApproval
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


def _workflow_app():
    application = create_app()
    application.include_router(payroll_runs_router, prefix="/api")
    application.include_router(run_commands_router, prefix="/api")
    application.include_router(run_workflow_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _workflow_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_as_admin(client) -> tuple[UUID, UUID]:
    resp, cookie = await login_dev(client)
    assert resp.status_code in {200, 302}, resp.text
    assert cookie, "expected accord_session cookie from login"
    client.cookies.set("accord_session", cookie)

    slug = f"wf-api-{uuid4().hex[:8]}"
    resp = await client.post("/api/organizations", json={"name": "WF API", "slug": slug})
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


async def _restore_cookie(client, session, dev_settings, *, org_id: UUID, user_id: UUID) -> None:
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=user_id,
        active_organization_id=org_id,
    )
    apply_session_cookie(client, cookie)


async def _create_calculated_run(client, session, dev_settings, *, org_id, user_id) -> str:
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
    run_id = run.json()["id"]

    employee_id = await _seed_calculate_world(session, org_id=org_id, user_id=user_id)
    await _restore_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)

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
    return run_id


@pytest.mark.asyncio
async def test_api_happy_path_validate_submit_approve(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    run_id = await _create_calculated_run(
        client, session, dev_settings, org_id=org_id, user_id=user_id
    )

    validated = await client.post(f"/api/payroll-runs/{run_id}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "calculated"
    assert validated.json()["blocking"] is False

    submitted = await client.post(
        f"/api/payroll-runs/{run_id}/submit",
        json={"reason": "ready"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    if session.in_transaction():
        await session.rollback()
    approver = await seed_user(session, email="approver-wf@example.com", name="Approver")
    approver_id = approver.id
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=approver_id,
        role="payroll_approver",
    )
    await session.commit()
    await _restore_cookie(client, session, dev_settings, org_id=org_id, user_id=approver_id)

    approved = await client.post(
        f"/api/payroll-runs/{run_id}/approve",
        json={"reason": "lgtm"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_api_self_approval_409(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    run_id = await _create_calculated_run(
        client, session, dev_settings, org_id=org_id, user_id=user_id
    )
    submitted = await client.post(f"/api/payroll-runs/{run_id}/submit")
    assert submitted.status_code == 200, submitted.text

    approved = await client.post(f"/api/payroll-runs/{run_id}/approve")
    assert approved.status_code == 409
    assert approved.json()["error"] == "urn:accord:workflow:maker_checker"


@pytest.mark.asyncio
async def test_api_idempotent_submit_no_duplicate_approvals(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    run_id = await _create_calculated_run(
        client, session, dev_settings, org_id=org_id, user_id=user_id
    )
    headers = {"Idempotency-Key": f"submit-{uuid4().hex}"}
    first = await client.post(
        f"/api/payroll-runs/{run_id}/submit",
        json={"reason": "once"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/payroll-runs/{run_id}/submit",
        json={"reason": "once"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        count = int(
            (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(PayrollApproval)
                    .where(
                        PayrollApproval.run_id == UUID(run_id),
                        PayrollApproval.action == "submit",
                    )
                )
            ).scalar_one()
        )
    assert count == 1


@pytest.mark.asyncio
async def test_api_capability_gates(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    run_id = await _create_calculated_run(
        client, session, dev_settings, org_id=org_id, user_id=user_id
    )

    if session.in_transaction():
        await session.rollback()
    reviewer = await seed_user(session, email="reviewer-wf@example.com", name="Reviewer")
    reviewer_id = reviewer.id
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=reviewer_id,
        role="payroll_reviewer",
    )
    await session.commit()
    await _restore_cookie(client, session, dev_settings, org_id=org_id, user_id=reviewer_id)

    validate = await client.post(f"/api/payroll-runs/{run_id}/validate")
    assert validate.status_code == 403
    assert validate.json()["error"] == "urn:accord:capability:create_run"

    submit = await client.post(f"/api/payroll-runs/{run_id}/submit")
    assert submit.status_code == 403
    assert submit.json()["error"] == "urn:accord:capability:submit_run"

    approve = await client.post(f"/api/payroll-runs/{run_id}/approve")
    assert approve.status_code == 403
    assert approve.json()["error"] == "urn:accord:capability:approve_run"

    reject = await client.post(f"/api/payroll-runs/{run_id}/reject")
    assert reject.status_code == 403
    assert reject.json()["error"] == "urn:accord:capability:approve_run"


@pytest.mark.asyncio
async def test_api_wrong_status_409(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    period = await client.post(
        "/api/payroll-periods",
        json={"period_year": 2026, "period_month": 7},
    )
    assert period.status_code == 201, period.text
    run = await client.post(
        "/api/payroll-runs",
        json={"period_id": period.json()["id"], "run_type": "regular"},
    )
    assert run.status_code == 201, run.text
    draft_run_id = run.json()["id"]

    approve = await client.post(f"/api/payroll-runs/{draft_run_id}/approve")
    assert approve.status_code == 409
    assert approve.json()["error"] == "urn:accord:workflow:illegal_transition"

    # submit-on-submitted
    run_id = await _create_calculated_run(
        client, session, dev_settings, org_id=org_id, user_id=user_id
    )
    first = await client.post(f"/api/payroll-runs/{run_id}/submit")
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/payroll-runs/{run_id}/submit")
    assert second.status_code == 409
    assert second.json()["error"] == "urn:accord:workflow:illegal_transition"


@pytest.mark.asyncio
async def test_api_withdraw_forbidden_for_other_preparer(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    run_id = await _create_calculated_run(
        client, session, dev_settings, org_id=org_id, user_id=user_id
    )
    submitted = await client.post(f"/api/payroll-runs/{run_id}/submit")
    assert submitted.status_code == 200, submitted.text

    if session.in_transaction():
        await session.rollback()
    other = await seed_user(session, email="other-prep@example.com", name="Other Prep")
    other_id = other.id
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=other_id,
        role="payroll_preparer",
    )
    await session.commit()
    await _restore_cookie(client, session, dev_settings, org_id=org_id, user_id=other_id)

    withdrawn = await client.post(f"/api/payroll-runs/{run_id}/withdraw")
    assert withdrawn.status_code == 403
    assert withdrawn.json()["error"] == "urn:accord:workflow:withdraw_forbidden"
