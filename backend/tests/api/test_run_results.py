"""API tests for calculated payroll run result read endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.payroll_runs import router as payroll_runs_router
from app.api.routes.run_commands import router as run_commands_router
from app.api.routes.run_results import router as run_results_router
from app.main import create_app
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import PayrollPeriod, PayrollRun, PayrollRunInput
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.schemas.run_results import CalculateResponse
from app.services import run_calculation as run_calculation_service
from app.services import versioning
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_organization,
    seed_user,
    session_cookie_from_response,
)


def _run_results_app():
    application = create_app()
    application.include_router(payroll_runs_router, prefix="/api")
    application.include_router(run_commands_router, prefix="/api")
    application.include_router(run_results_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _run_results_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_as_admin(client) -> tuple[UUID, UUID]:
    resp, cookie = await login_dev(client)
    assert resp.status_code in {200, 302}, resp.text
    assert cookie, "expected accord_session cookie from login"
    client.cookies.set("accord_session", cookie)

    slug = f"results-api-{uuid4().hex[:8]}"
    resp = await client.post("/api/organizations", json={"name": "Results API", "slug": slug})
    assert resp.status_code == 201, resp.text
    cookie = session_cookie_from_response(resp) or cookie
    client.cookies.set("accord_session", cookie)
    body = resp.json()
    return UUID(body["active_organization"]["id"]), UUID(body["id"])


async def _bind(session, org_id: UUID, user_id: UUID) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_calculated_world(session, *, org_id: UUID, user_id: UUID) -> dict:
    """Seed master data + draft run, then calculate via service. Returns ids."""
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
                "name": "Results Employee",
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

        period = PayrollPeriod(
            organization_id=org_id,
            period_year=2026,
            period_month=6,
            status="open",
        )
        session.add(period)
        await session.flush()
        run = PayrollRun(
            organization_id=org_id,
            period_id=period.id,
            run_type="regular",
            status="draft",
        )
        session.add(run)
        await session.flush()

        session.add(
            PayrollRunInput(
                organization_id=org_id,
                run_id=run.id,
                employee_id=employee.id,
                component_code="FIXED_ALLOWANCE",
                input_kind="override",
                amount=Decimal("2500.00"),
                reason="June override",
                created_by=user_id,
                updated_by=user_id,
            )
        )
        employee_id = employee.id
        run_id = run.id

    await _bind(session, org_id, user_id)
    calc = await run_calculation_service.calculate_run_command(
        session,
        organization_id=org_id,
        run_id=run_id,
        user_id=user_id,
    )

    return {
        "org_id": org_id,
        "user_id": user_id,
        "employee_id": employee_id,
        "run_id": run_id,
        "calc": calc,
    }


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


@pytest.mark.asyncio
async def test_results_list_happy_path(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=user_id)
    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)

    resp = await client.get(f"/api/payroll-runs/{world['run_id']}/results")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["version"]["version_number"] == 1
    assert body["version"]["id"] == str(world["calc"]["version_id"])
    assert body["version"]["content_hash"] == world["calc"]["content_hash"]
    assert body["version"]["engine_version"] == world["calc"]["engine_version"]
    assert body["version"]["calculated_at"]
    assert body["totals"]["net_payable"] == "51000.00"
    assert body["totals"]["earnings_total"] == "52500.00"
    assert body["version"]["totals"] == body["totals"]

    assert len(body["employees"]) == 1
    emp = body["employees"][0]
    assert emp["employee_id"] == str(world["employee_id"])
    assert emp["net_payable"] == "51000.00"
    assert emp["earnings_total"] == "52500.00"
    assert emp["deductions_total"] == "1500.00"


@pytest.mark.asyncio
async def test_results_version_number_selection(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=user_id)

    await _bind(session, org_id, user_id)
    second = await run_calculation_service.calculate_run_command(
        session,
        organization_id=org_id,
        run_id=world["run_id"],
        user_id=user_id,
    )
    assert second["version_number"] == 2

    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)

    current = await client.get(f"/api/payroll-runs/{world['run_id']}/results")
    assert current.status_code == 200
    assert current.json()["version"]["version_number"] == 2
    assert current.json()["version"]["id"] == str(second["version_id"])

    v1 = await client.get(
        f"/api/payroll-runs/{world['run_id']}/results",
        params={"version_number": 1},
    )
    assert v1.status_code == 200
    assert v1.json()["version"]["version_number"] == 1
    assert v1.json()["version"]["id"] == str(world["calc"]["version_id"])

    missing = await client.get(
        f"/api/payroll-runs/{world['run_id']}/results",
        params={"version_number": 99},
    )
    assert missing.status_code == 409


@pytest.mark.asyncio
async def test_results_409_when_run_has_no_calculated_version(client, session):
    org_id, _user_id = await _create_org_as_admin(client)

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

    resp = await client.get(f"/api/payroll-runs/{run.json()['id']}/results")
    assert resp.status_code == 409
    assert "no calculated version" in resp.json()["detail"].lower()
    assert org_id is not None


@pytest.mark.asyncio
async def test_results_404_unknown_run(client, session):
    await _create_org_as_admin(client)
    resp = await client.get(f"/api/payroll-runs/{uuid4()}/results")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_employee_lines_trace_passthrough_and_sequence(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=user_id)
    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)

    resp = await client.get(f"/api/payroll-runs/{world['run_id']}/results/{world['employee_id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["employee_id"] == str(world["employee_id"])
    assert body["net_payable"] == "51000.00"
    assert len(body["lines"]) >= 4

    codes = [line["component_code"] for line in body["lines"]]
    assert "BASIC" in codes
    assert "FIXED_ALLOWANCE" in codes
    # Sequence ordering: BASIC is resolved before allowance / recoveries.
    assert codes.index("BASIC") < codes.index("FIXED_ALLOWANCE")

    for line in body["lines"]:
        assert isinstance(line["trace"], dict)
        assert "rounded_value" in line["trace"]
        assert "engine_version" in line["trace"]
        assert line["trace"]["engine_version"] == world["calc"]["engine_version"]
        assert line["amount"]
        assert line["component_code"]
        assert line["classification"]
        assert line["calc_kind"]

    allowance = next(line for line in body["lines"] if line["component_code"] == "FIXED_ALLOWANCE")
    assert allowance["amount"] == "2500.00"
    assert allowance["trace"]["rounded_value"] == "2500.00"

    foregone = next(line for line in body["lines"] if line["component_code"] == "FOREGONE_HRA")
    assert foregone["trace"]["classification"] == "informational"


@pytest.mark.asyncio
async def test_run_detail_populated_current_version_after_calculation(
    client, session, dev_settings
):
    org_id, user_id = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=user_id)
    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)

    detail = await client.get(f"/api/payroll-runs/{world['run_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "calculated"
    assert body["current_version"] is not None
    assert body["current_version"]["id"] == str(world["calc"]["version_id"])
    assert body["current_version"]["version_number"] == 1
    assert body["current_version"]["content_hash"] == world["calc"]["content_hash"]
    assert body["current_version"]["engine_version"] == world["calc"]["engine_version"]
    assert body["current_version"]["totals"]["net_payable"] == "51000.00"
    assert body["current_version"]["calculated_at"]


@pytest.mark.asyncio
async def test_calculate_response_matches_calculate_response_schema(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=user_id)

    # Fresh draft run against the same seeded master data for the API path.
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        period_row = PayrollPeriod(
            organization_id=org_id,
            period_year=2026,
            period_month=8,
            status="open",
        )
        session.add(period_row)
        await session.flush()
        draft = PayrollRun(
            organization_id=org_id,
            period_id=period_row.id,
            run_type="regular",
            status="draft",
        )
        session.add(draft)
        await session.flush()
        draft_id = draft.id

    await _restore_admin_cookie(client, session, dev_settings, org_id=org_id, user_id=user_id)
    resp = await client.post(f"/api/payroll-runs/{draft_id}/calculate")
    assert resp.status_code == 200, resp.text
    parsed = CalculateResponse.model_validate(resp.json())
    assert parsed.run_id == draft_id
    assert parsed.version_number == 1
    assert parsed.version_id
    assert parsed.content_hash
    assert parsed.engine_version
    assert parsed.totals["net_payable"]
    assert world["employee_id"] is not None


@pytest.mark.asyncio
async def test_results_tenant_isolation_org_b_404(client, session, dev_settings):
    org_a_id, admin_a = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_a_id, user_id=admin_a)

    org_b = await seed_organization(session, name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    admin_b = await seed_user(session, email="admin-b-results@example.com", name="Admin B")
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=admin_b.id,
        role="organization_administrator",
    )
    await session.commit()

    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=admin_b.id,
        active_organization_id=org_b.id,
    )
    apply_session_cookie(client, cookie)

    list_resp = await client.get(f"/api/payroll-runs/{world['run_id']}/results")
    assert list_resp.status_code == 404

    emp_resp = await client.get(
        f"/api/payroll-runs/{world['run_id']}/results/{world['employee_id']}"
    )
    assert emp_resp.status_code == 404


@pytest.mark.asyncio
async def test_results_capability_gate_auditor_403(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=user_id)

    auditor = await seed_user(session, email="auditor-results@example.com", name="Auditor")
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=auditor.id,
        role="auditor",
    )
    await session.commit()

    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=auditor.id,
        active_organization_id=org_id,
    )
    apply_session_cookie(client, cookie)

    resp = await client.get(f"/api/payroll-runs/{world['run_id']}/results")
    assert resp.status_code == 403
    assert resp.json()["error"] == "urn:accord:capability:view_master_data"

    emp_resp = await client.get(
        f"/api/payroll-runs/{world['run_id']}/results/{world['employee_id']}"
    )
    assert emp_resp.status_code == 403
    assert emp_resp.json()["error"] == "urn:accord:capability:view_master_data"
