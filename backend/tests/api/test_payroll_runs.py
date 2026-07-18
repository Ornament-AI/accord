"""Integration tests for payroll period / run / draft-input routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.api.routes.payroll_runs import router as payroll_runs_router
from app.main import create_app
from app.models.employees import Employee
from app.models.payroll_runs import PayrollRun
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_organization,
    seed_user,
    session_cookie_from_response,
)


def _payroll_runs_app():
    application = create_app()
    application.include_router(payroll_runs_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _payroll_runs_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_as_admin(client) -> tuple[UUID, UUID]:
    await login_dev(client)
    slug = f"acme-{uuid4().hex[:8]}"
    resp = await client.post("/api/organizations", json={"name": "Acme", "slug": slug})
    assert resp.status_code == 201, resp.text
    cookie = session_cookie_from_response(resp)
    if cookie:
        client.cookies.set("accord_session", cookie)
    body = resp.json()
    org_id = UUID(body["active_organization"]["id"])
    user_id = UUID(body["id"])
    return org_id, user_id


async def _seed_employee(session, *, org_id: UUID, user_id: UUID, number: str = "E001") -> Employee:
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        emp = Employee(organization_id=org_id, employee_number=number)
        session.add(emp)
        await session.flush()
        employee_id = emp.id
    await session.commit()
    return await session.get(Employee, employee_id)


async def _admin_context(client, session) -> dict:
    org_id, user_id = await _create_org_as_admin(client)
    employee = await _seed_employee(session, org_id=org_id, user_id=user_id)
    return {
        "org_id": org_id,
        "user_id": user_id,
        "employee_id": employee.id,
    }


async def _create_period(client, *, year: int = 2026, month: int = 6) -> dict:
    resp = await client.post(
        "/api/payroll-periods",
        json={"period_year": year, "period_month": month},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_run(client, *, period_id: str, run_type: str = "regular") -> dict:
    resp = await client.post(
        "/api/payroll-runs",
        json={"period_id": period_id, "run_type": run_type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Periods ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_period_create_list_ordering_and_duplicate_409(client, session):
    await _admin_context(client, session)

    june = await _create_period(client, year=2026, month=6)
    july = await _create_period(client, year=2026, month=7)
    may = await _create_period(client, year=2025, month=5)

    listed = await client.get("/api/payroll-periods")
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()]
    assert ids == [july["id"], june["id"], may["id"]]

    dup = await client.post(
        "/api/payroll-periods",
        json={"period_year": 2026, "period_month": 6},
    )
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"].lower()


# --- Runs ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_create_second_regular_409_supplemental_allowed(client, session):
    await _admin_context(client, session)
    period = await _create_period(client)

    regular = await _create_run(client, period_id=period["id"], run_type="regular")
    assert regular["status"] == "draft"
    assert regular["run_type"] == "regular"
    assert regular["period_year"] == 2026
    assert regular["period_month"] == 6

    second = await client.post(
        "/api/payroll-runs",
        json={"period_id": period["id"], "run_type": "regular"},
    )
    assert second.status_code == 409

    supplemental = await _create_run(client, period_id=period["id"], run_type="supplemental")
    assert supplemental["run_type"] == "supplemental"
    assert supplemental["period_id"] == period["id"]

    unknown = await client.post(
        "/api/payroll-runs",
        json={"period_id": str(uuid4()), "run_type": "regular"},
    )
    assert unknown.status_code == 404


# --- Inputs -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_input_upsert_list_delete_happy_path(client, session):
    ctx = await _admin_context(client, session)
    period = await _create_period(client)
    run = await _create_run(client, period_id=period["id"])
    employee_id = str(ctx["employee_id"])

    created = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/BASIC",
        json={
            "input_kind": "exception",
            "amount": "1500.00",
            "reason": "Arrears for June",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["amount"] == "1500.00"
    assert body["version"] == 0
    assert body["component_code"] == "BASIC"
    input_id = body["id"]

    updated = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/BASIC",
        json={
            "input_kind": "exception",
            "amount": "1750.50",
            "reason": "Corrected arrears",
            "expected_version": 0,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["amount"] == "1750.50"
    assert updated.json()["version"] == 1

    listed = await client.get(f"/api/payroll-runs/{run['id']}/inputs")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == input_id

    detail = await client.get(f"/api/payroll-runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "draft"
    assert detail.json()["current_version"] is None
    assert detail.json()["lock_version"] == 0

    deleted = await client.delete(f"/api/payroll-runs/{run['id']}/inputs/{input_id}")
    assert deleted.status_code == 204

    listed_after = await client.get(f"/api/payroll-runs/{run['id']}/inputs")
    assert listed_after.json() == []


@pytest.mark.asyncio
async def test_input_mutation_on_non_draft_run_409(client, session):
    ctx = await _admin_context(client, session)
    period = await _create_period(client)
    run = await _create_run(client, period_id=period["id"])
    employee_id = str(ctx["employee_id"])

    created = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/BASIC",
        json={
            "input_kind": "override",
            "amount": "100.00",
            "reason": "Draft override",
        },
    )
    assert created.status_code == 200
    input_id = created.json()["id"]

    async with session.begin():
        await bind_tenant_context(session, organization_id=ctx["org_id"], user_id=ctx["user_id"])
        await session.execute(
            update(PayrollRun).where(PayrollRun.id == UUID(run["id"])).values(status="calculated")
        )
    await session.commit()

    mutate = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/BASIC",
        json={
            "input_kind": "override",
            "amount": "200.00",
            "reason": "Should fail",
            "expected_version": 0,
        },
    )
    assert mutate.status_code == 409

    delete_resp = await client.delete(f"/api/payroll-runs/{run['id']}/inputs/{input_id}")
    assert delete_resp.status_code == 409


@pytest.mark.asyncio
async def test_input_optimistic_version_conflict_409(client, session):
    ctx = await _admin_context(client, session)
    period = await _create_period(client)
    run = await _create_run(client, period_id=period["id"])
    employee_id = str(ctx["employee_id"])

    first = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/HRA",
        json={
            "input_kind": "one_time",
            "amount": "500.00",
            "reason": "One-time HRA",
        },
    )
    assert first.status_code == 200
    assert first.json()["version"] == 0

    second = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/HRA",
        json={
            "input_kind": "one_time",
            "amount": "600.00",
            "reason": "Updated HRA",
            "expected_version": 0,
        },
    )
    assert second.status_code == 200
    assert second.json()["version"] == 1

    stale = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{employee_id}/HRA",
        json={
            "input_kind": "one_time",
            "amount": "700.00",
            "reason": "Stale update",
            "expected_version": 0,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "stale_row"


@pytest.mark.asyncio
async def test_input_unknown_employee_404(client, session):
    await _admin_context(client, session)
    period = await _create_period(client)
    run = await _create_run(client, period_id=period["id"])

    resp = await client.put(
        f"/api/payroll-runs/{run['id']}/inputs/{uuid4()}/BASIC",
        json={
            "input_kind": "exception",
            "amount": "10.00",
            "reason": "Unknown employee",
        },
    )
    assert resp.status_code == 404


# --- Capability gate ----------------------------------------------------------


@pytest.mark.asyncio
async def test_payroll_reviewer_can_get_but_not_write(client, dev_settings, session):
    ctx = await _admin_context(client, session)
    period = await _create_period(client)
    run = await _create_run(client, period_id=period["id"])

    reviewer = await seed_user(session, email="reviewer@example.com", name="Reviewer")
    await seed_membership(
        session,
        organization_id=ctx["org_id"],
        user_id=reviewer.id,
        role="payroll_reviewer",
    )
    await session.commit()

    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=reviewer.id,
        active_organization_id=ctx["org_id"],
    )
    apply_session_cookie(client, cookie)

    get_periods = await client.get("/api/payroll-periods")
    assert get_periods.status_code == 200

    get_runs = await client.get("/api/payroll-runs")
    assert get_runs.status_code == 200
    assert any(r["id"] == run["id"] for r in get_runs.json())

    post_period = await client.post(
        "/api/payroll-periods",
        json={"period_year": 2027, "period_month": 1},
    )
    assert post_period.status_code == 403
    assert post_period.json()["error"] == "urn:accord:capability:create_run"

    post_run = await client.post(
        "/api/payroll-runs",
        json={"period_id": period["id"], "run_type": "supplemental"},
    )
    assert post_run.status_code == 403
    assert post_run.json()["error"] == "urn:accord:capability:create_run"


# --- Tenant isolation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_runs_not_visible_across_orgs(client, session, dev_settings):
    org_a_id, admin_a = await _create_org_as_admin(client)
    period_a = await _create_period(client, year=2026, month=3)
    run_a = await _create_run(client, period_id=period_a["id"])

    org_b = await seed_organization(session, name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    admin_b = await seed_user(session, email="admin-b@example.com", name="Admin B")
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

    listed = await client.get("/api/payroll-runs")
    assert listed.status_code == 200
    assert listed.json() == []

    detail = await client.get(f"/api/payroll-runs/{run_a['id']}")
    assert detail.status_code == 404

    # Silence unused binding for clarity in dual-org setup.
    assert org_a_id is not None
    assert admin_a is not None
