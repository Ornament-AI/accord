"""Integration tests for payroll period / run / draft-input routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import Range

from app.api.routes.payroll_runs import router as payroll_runs_router
from app.main import create_app
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.payroll_runs import PayrollRun
from app.tenancy import bind_tenant_context
from app.services.bootstrap import provision_organization
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_user,
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


async def _create_org_as_admin(client, session) -> tuple[UUID, UUID]:
    slug = f"acme-{uuid4().hex[:8]}"
    await provision_organization(
        session,
        name="Acme",
        slug=slug,
        admin_email="dev@accord.local",
    )
    await session.commit()
    await login_dev(client)
    body = (await client.get("/api/auth/me")).json()
    assert body["access_state"] == "active", body
    return UUID(body["organization"]["id"]), UUID(body["id"])


async def _seed_employee(session, *, org_id: UUID, user_id: UUID, number: str = "E001") -> UUID:
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        emp = Employee(organization_id=org_id, employee_number=number)
        session.add(emp)
        await session.flush()
        employee_id = emp.id
    await session.commit()
    return employee_id


async def _seed_employee_versions(session, *, org_id: UUID, user_id: UUID, employee_id: UUID):
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        validity = Range(date(2026, 1, 1), None, bounds="[)")
        await session.execute(
            employee_profile_versions.insert().values(
                organization_id=org_id,
                header_id=employee_id,
                validity=validity,
                name="Test Employee",
                retirement_regime="nps",
                created_by=user_id,
            )
        )
        await session.execute(
            employee_pay_versions.insert().values(
                organization_id=org_id,
                header_id=employee_id,
                validity=validity,
                basic_pay=Decimal("60000.00"),
                created_by=user_id,
            )
        )
    await session.commit()


async def _admin_context(client, session) -> dict:
    org_id, user_id = await _create_org_as_admin(client, session)
    employee_id = await _seed_employee(session, org_id=org_id, user_id=user_id)
    return {
        "org_id": org_id,
        "user_id": user_id,
        "employee_id": employee_id,
    }


async def _create_period(client, *, year: int = 2026, month: int = 6) -> dict:
    resp = await client.post(
        "/api/payroll-periods",
        json={"period_year": year, "period_month": month},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_run(client, *, period_id: str) -> dict:
    resp = await client.post(
        "/api/payroll-runs",
        json={"period_id": period_id},
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
async def test_run_create_duplicate_409_and_legacy_type_rejected(client, session):
    await _admin_context(client, session)
    period = await _create_period(client)

    run = await _create_run(client, period_id=period["id"])
    assert run["status"] == "draft"
    assert "run_type" not in run
    assert run["period_year"] == 2026
    assert run["period_month"] == 6

    second = await client.post(
        "/api/payroll-runs",
        json={"period_id": period["id"]},
    )
    assert second.status_code == 409

    legacy = await client.post(
        "/api/payroll-runs",
        json={"period_id": period["id"], "run_type": "supplemental"},
    )
    assert legacy.status_code == 422

    unknown = await client.post(
        "/api/payroll-runs",
        json={"period_id": str(uuid4())},
    )
    assert unknown.status_code == 404


# --- Inputs -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_roster_selects_employees_and_saves_inline_values(client, session):
    ctx = await _admin_context(client, session)
    await _seed_employee_versions(
        session,
        org_id=ctx["org_id"],
        user_id=ctx["user_id"],
        employee_id=ctx["employee_id"],
    )
    period = await _create_period(client, year=2026, month=6)
    run = await _create_run(client, period_id=period["id"])

    initial = await client.get(f"/api/payroll-runs/{run['id']}/roster")
    assert initial.status_code == 200, initial.text
    assert initial.json()[0]["selected"] is False
    assert initial.json()[0]["payable_days"] == "30.00"
    assert initial.json()[0]["basic_pay"] == "60000.00"
    assert initial.json()[0]["retirement_regime"] == "nps"

    saved = await client.put(
        f"/api/payroll-runs/{run['id']}/roster",
        json={
            "employees": [
                {
                    "employee_id": str(ctx["employee_id"]),
                    "payable_days": "28.00",
                    "da_percent": "55.0000",
                    "da_difference": "1250.00",
                    "hra_percent": "20.0000",
                    "transport_amount": "1800.00",
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    row = saved.json()[0]
    assert row["selected"] is True
    assert row["payable_days"] == "28.00"
    assert row["da_percent"] == "55.0000"
    assert row["transport_amount"] == "1800.00"

    detail = await client.get(f"/api/payroll-runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["roster_initialized"] is True

    history = await client.get(f"/api/payroll-runs/{run['id']}/roster-history")
    assert history.status_code == 200, history.text
    assert history.json()[0]["action"] == "Created roster"
    assert history.json()[0]["changed_employees"] == 1
    assert history.json()[0]["selected_employees"] == 1
    assert history.json()[0]["changed_fields"] == ["Employees"]

    updated = await client.put(
        f"/api/payroll-runs/{run['id']}/roster",
        json={
            "employees": [
                {
                    "employee_id": str(ctx["employee_id"]),
                    "payable_days": "29.00",
                    "da_percent": "55.0000",
                    "da_difference": "1250.00",
                    "hra_percent": "20.0000",
                    "transport_amount": "1800.00",
                }
            ]
        },
    )
    assert updated.status_code == 200, updated.text

    history = await client.get(f"/api/payroll-runs/{run['id']}/roster-history")
    assert history.status_code == 200, history.text
    assert len(history.json()) == 2
    assert history.json()[0]["action"] == "Updated roster"
    assert history.json()[0]["changed_employees"] == 1
    assert history.json()[0]["changed_fields"] == ["Paid days"]


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
        json={"period_id": period["id"]},
    )
    assert post_run.status_code == 403
    assert post_run.json()["error"] == "urn:accord:capability:create_run"


# --- Fail-closed / unknown-id isolation (single org, ADR 0011) ----------------


@pytest.mark.asyncio
async def test_unknown_run_id_404(client, session):
    await _create_org_as_admin(client, session)
    await _create_period(client, year=2026, month=3)

    detail = await client.get(f"/api/payroll-runs/{uuid4()}")
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_unprovisioned_user_fail_closed_on_runs(client, session, dev_settings):
    org_id, _admin_id = await _create_org_as_admin(client, session)
    period = await _create_period(client, year=2026, month=3)
    run = await _create_run(client, period_id=period["id"])
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

    listed = await client.get("/api/payroll-runs")
    assert listed.status_code == 409
    assert listed.json()["error"] == "OrganizationContextRequired"

    detail = await client.get(f"/api/payroll-runs/{run['id']}")
    assert detail.status_code == 409


@pytest.mark.asyncio
async def test_run_roster_rejects_ineligible_and_surfaces_saved_ineligible_rows(client, session):
    """Employees with no active profile at month-end cannot be saved; a saved
    member who later loses their profile stays visible with eligible=false."""

    from app.models.payroll_runs import PayrollRunEmployee

    ctx = await _admin_context(client, session)
    await _seed_employee_versions(
        session, org_id=ctx["org_id"], user_id=ctx["user_id"], employee_id=ctx["employee_id"]
    )
    # Second employee with NO profile version at all.
    bare_id = await _seed_employee(
        session, org_id=ctx["org_id"], user_id=ctx["user_id"], number="E002"
    )
    period = await _create_period(client, year=2026, month=6)
    run = await _create_run(client, period_id=period["id"])

    # Never-selectable employees without saved rows are omitted from the roster.
    initial = await client.get(f"/api/payroll-runs/{run['id']}/roster")
    assert initial.status_code == 200, initial.text
    assert [row["employee_id"] for row in initial.json()] == [str(ctx["employee_id"])]
    assert initial.json()[0]["eligible"] is True

    # Saving an ineligible employee is rejected with an actionable message.
    rejected = await client.put(
        f"/api/payroll-runs/{run['id']}/roster",
        json={
            "employees": [
                {"employee_id": str(ctx["employee_id"]), "payable_days": "30.00"},
                {"employee_id": str(bare_id), "payable_days": "30.00"},
            ]
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "E002" in rejected.json()["detail"]
    assert "no active profile" in rejected.json()["detail"].lower()

    # Simulate a saved member whose profile later ends: insert the roster row
    # directly, then confirm it is surfaced as ineligible instead of hidden.
    async with session.begin():
        await bind_tenant_context(session, organization_id=ctx["org_id"], user_id=ctx["user_id"])
        session.add(
            PayrollRunEmployee(
                organization_id=ctx["org_id"],
                run_id=UUID(run["id"]),
                employee_id=bare_id,
                payable_days=Decimal("30.00"),
            )
        )
    await session.commit()

    listed = await client.get(f"/api/payroll-runs/{run['id']}/roster")
    assert listed.status_code == 200, listed.text
    by_id = {row["employee_id"]: row for row in listed.json()}
    stale = by_id[str(bare_id)]
    assert stale["selected"] is True
    assert stale["eligible"] is False
    assert stale["ineligible_reason"] == "no_active_profile"
    assert by_id[str(ctx["employee_id"])]["eligible"] is True


@pytest.mark.asyncio
async def test_run_roster_noop_save_preserves_rows_lock_version_and_history(client, session):
    """A semantically identical save must not mint row UUIDs, bump
    lock_version, or append audit history."""
    from sqlalchemy import select as sa_select

    from app.models.payroll_runs import PayrollRunEmployee

    ctx = await _admin_context(client, session)
    await _seed_employee_versions(
        session, org_id=ctx["org_id"], user_id=ctx["user_id"], employee_id=ctx["employee_id"]
    )
    period = await _create_period(client, year=2026, month=6)
    run = await _create_run(client, period_id=period["id"])

    payload = {
        "employees": [
            {
                "employee_id": str(ctx["employee_id"]),
                "payable_days": "28.00",
                "da_percent": "55.0000",
                "transport_amount": "1800.00",
            }
        ]
    }
    first = await client.put(f"/api/payroll-runs/{run['id']}/roster", json=payload)
    assert first.status_code == 200, first.text

    async def snapshot():
        await bind_tenant_context(session, organization_id=ctx["org_id"], user_id=ctx["user_id"])
        rows = (
            (
                await session.execute(
                    sa_select(PayrollRunEmployee).where(
                        PayrollRunEmployee.run_id == UUID(run["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        detail = await client.get(f"/api/payroll-runs/{run['id']}")
        history = await client.get(f"/api/payroll-runs/{run['id']}/roster-history")
        return (
            sorted(str(r.id) for r in rows),
            detail.json()["lock_version"],
            len(history.json()),
        )

    ids_before, lock_before, history_before = await snapshot()

    # Cosmetically different but numerically identical values (28 == 28.00).
    noop_payload = {
        "employees": [
            {
                "employee_id": str(ctx["employee_id"]),
                "payable_days": "28",
                "da_percent": "55.00",
                "transport_amount": "1800.0",
            }
        ]
    }
    second = await client.put(f"/api/payroll-runs/{run['id']}/roster", json=noop_payload)
    assert second.status_code == 200, second.text

    ids_after, lock_after, history_after = await snapshot()
    assert ids_after == ids_before
    assert lock_after == lock_before
    assert history_after == history_before

    # A real change still bumps lock_version, preserves the retained row id,
    # and appends history.
    changed_payload = {
        "employees": [
            {
                "employee_id": str(ctx["employee_id"]),
                "payable_days": "27.00",
                "da_percent": "55.0000",
                "transport_amount": "1800.00",
            }
        ]
    }
    third = await client.put(f"/api/payroll-runs/{run['id']}/roster", json=changed_payload)
    assert third.status_code == 200, third.text
    ids_changed, lock_changed, history_changed = await snapshot()
    assert ids_changed == ids_before
    assert lock_changed == lock_before + 1
    assert history_changed == history_before + 1
