"""API tests for calculated payroll run result read endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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
from app.services.bootstrap import provision_organization
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_user,
)
from tests.roster_helpers import initialize_run_roster


def _run_results_app():
    application = create_app()
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _run_results_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_as_admin(client, session) -> tuple[UUID, UUID]:
    slug = f"results-api-{uuid4().hex[:8]}"
    await provision_organization(
        session,
        name="Results API",
        slug=slug,
        admin_email="dev@accord.local",
    )
    await session.commit()
    resp, cookie = await login_dev(client)
    assert resp.status_code in {200, 302}, resp.text
    assert cookie, "expected accord_session cookie from login"
    body = (await client.get("/api/auth/me")).json()
    assert body["access_state"] == "active", body
    return UUID(body["organization"]["id"]), UUID(body["id"])


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

        standard_components = {
            row.code: row
            for row in (
                await session.execute(
                    select(PayComponent).where(PayComponent.organization_id == org_id)
                )
            ).scalars()
        }
        basic = standard_components["BASIC"]
        allowance = PayComponent(
            organization_id=org_id,
            code="FIXED_ALLOWANCE",
            name="Fixed Allowance",
            classification="earning",
        )
        session.add(allowance)
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
            status="draft",
        )
        session.add(run)
        await session.flush()
        session.add_all(
            initialize_run_roster(
                organization_id=org_id,
                run=run,
                employee_ids=[employee.id],
                period_year=period.period_year,
                period_month=period.period_month,
            )
        )

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
    org_id, user_id = await _create_org_as_admin(client, session)
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
    org_id, user_id = await _create_org_as_admin(client, session)
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
    org_id, _user_id = await _create_org_as_admin(client, session)

    period = await client.post(
        "/api/payroll-periods",
        json={"period_year": 2026, "period_month": 6},
    )
    assert period.status_code == 201, period.text
    run = await client.post(
        "/api/payroll-runs",
        json={"period_id": period.json()["id"]},
    )
    assert run.status_code == 201, run.text

    resp = await client.get(f"/api/payroll-runs/{run.json()['id']}/results")
    assert resp.status_code == 409
    assert "no calculated version" in resp.json()["detail"].lower()
    assert org_id is not None


@pytest.mark.asyncio
async def test_results_404_unknown_run(client, session):
    await _create_org_as_admin(client, session)
    resp = await client.get(f"/api/payroll-runs/{uuid4()}/results")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_employee_lines_trace_passthrough_and_sequence(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client, session)
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
    org_id, user_id = await _create_org_as_admin(client, session)
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
    org_id, user_id = await _create_org_as_admin(client, session)
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
            status="draft",
        )
        session.add(draft)
        await session.flush()
        session.add_all(
            initialize_run_roster(
                organization_id=org_id,
                run=draft,
                employee_ids=[world["employee_id"]],
                period_year=period_row.period_year,
                period_month=period_row.period_month,
            )
        )
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
async def test_results_unknown_run_404(client, session):
    await _create_org_as_admin(client, session)

    list_resp = await client.get(f"/api/payroll-runs/{uuid4()}/results")
    assert list_resp.status_code == 404


@pytest.mark.asyncio
async def test_results_unprovisioned_user_fail_closed(client, session, dev_settings):
    org_id, admin_id = await _create_org_as_admin(client, session)
    world = await _seed_calculated_world(session, org_id=org_id, user_id=admin_id)
    outsider = await seed_user(session, email=f"out-{uuid4().hex[:8]}@example.com")
    await session.commit()

    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=outsider.id,
            active_organization_id=org_id,
        ),
    )

    list_resp = await client.get(f"/api/payroll-runs/{world['run_id']}/results")
    assert list_resp.status_code == 409
    assert list_resp.json()["error"] == "OrganizationContextRequired"

    emp_resp = await client.get(
        f"/api/payroll-runs/{world['run_id']}/results/{world['employee_id']}"
    )
    assert emp_resp.status_code == 409


@pytest.mark.asyncio
async def test_results_capability_gate_auditor_403(client, session, dev_settings):
    org_id, user_id = await _create_org_as_admin(client, session)
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
