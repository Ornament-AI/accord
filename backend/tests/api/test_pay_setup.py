"""Integration tests for pay-setup master data routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.pay_setup import router as pay_setup_router
from app.main import create_app
from app.models.employees import Employee
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_organization,
    seed_user,
    session_cookie_from_response,
)


def _pay_setup_app():
    application = create_app()
    application.include_router(pay_setup_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _pay_setup_app()
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


async def _create_component(client, *, code: str = "BASIC", name: str = "Basic Pay") -> dict:
    resp = await client.post(
        "/api/pay-components",
        json={
            "code": code,
            "name": name,
            "classification": "earning",
            "display_order": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Happy path CRUD + versioning (5 families) --------------------------------


@pytest.mark.asyncio
async def test_pay_component_crud_and_rate_versioning(client, session):
    await _admin_context(client, session)
    created = await _create_component(client, code="BASIC")
    component_id = created["id"]
    assert created["code"] == "BASIC"
    assert created["classification"] == "earning"

    listed = (await client.get("/api/pay-components")).json()
    assert any(c["id"] == component_id for c in listed)

    patched = await client.patch(
        f"/api/pay-components/{component_id}",
        json={"name": "Basic Salary", "is_active": True},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Basic Salary"

    rate = await client.post(
        f"/api/pay-components/{component_id}/rate-versions",
        json={
            "effective_from": "2026-01-01",
            "calc_kind": "fixed_recurring_amount",
            "amount": "50000.00",
            "rounding_rule": "ROUND_HALF_UP_RUPEE",
        },
    )
    assert rate.status_code == 201, rate.text
    rate_body = rate.json()
    assert rate_body["amount"] == "50000.00"
    assert rate_body["effective_from"] == "2026-01-01"
    assert rate_body["effective_to"] is None

    rates = (await client.get(f"/api/pay-components/{component_id}/rate-versions")).json()
    assert len(rates) == 1
    assert rates[0]["id"] == rate_body["id"]


@pytest.mark.asyncio
async def test_pay_component_employer_transfer_metadata_is_validated_and_editable(client, session):
    await _admin_context(client, session)
    contribution = await client.post(
        "/api/pay-components",
        json={
            "code": "EPF_EMPLOYER",
            "name": "EPF Employer",
            "classification": "employer_contribution",
        },
    )
    assert contribution.status_code == 201, contribution.text

    transfer = await client.post(
        "/api/pay-components",
        json={
            "code": "EPF_EMPLOYER_TRANSFER",
            "name": "EPF Employer Transfer",
            "classification": "ag_deduction",
            "employer_transfer": True,
            "transfer_of": "EPF_EMPLOYER",
        },
    )
    assert transfer.status_code == 201, transfer.text
    body = transfer.json()
    assert body["employer_transfer"] is True
    assert body["transfer_of"] == "EPF_EMPLOYER"

    patched = await client.patch(
        f"/api/pay-components/{body['id']}",
        json={"transfer_of": None},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["employer_transfer"] is True
    assert patched.json()["transfer_of"] is None

    invalid_class = await client.post(
        "/api/pay-components",
        json={
            "code": "BAD_TRANSFER",
            "name": "Bad Transfer",
            "classification": "earning",
            "employer_transfer": True,
        },
    )
    assert invalid_class.status_code == 422, invalid_class.text

    unknown_target = await client.post(
        "/api/pay-components",
        json={
            "code": "UNKNOWN_TRANSFER",
            "name": "Unknown Transfer",
            "classification": "ag_deduction",
            "employer_transfer": True,
            "transfer_of": "DOES_NOT_EXIST",
        },
    )
    assert unknown_target.status_code == 400, unknown_target.text


@pytest.mark.asyncio
async def test_recurring_instruction_crud_and_versioning(client, session):
    ctx = await _admin_context(client, session)
    component = await _create_component(client, code="SPECIAL")
    employee_id = ctx["employee_id"]
    component_id = component["id"]

    created = await client.post(
        f"/api/employees/{employee_id}/recurring-instructions",
        json={
            "component_id": component_id,
            "effective_from": "2026-01-01",
            "amount": "2500.00",
            "reason": "Special allowance",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    instruction_id = body["id"]
    assert body["amount"] == "2500.00"
    assert body["version_id"] is not None

    listed = (await client.get(f"/api/employees/{employee_id}/recurring-instructions")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == instruction_id

    version = await client.post(
        f"/api/recurring-instructions/{instruction_id}/versions",
        json={
            "effective_from": "2026-04-01",
            "amount": "3000.00",
            "change_reason": "Annual revision",
        },
    )
    assert version.status_code == 201, version.text
    assert version.json()["amount"] == "3000.00"

    versions = (await client.get(f"/api/recurring-instructions/{instruction_id}/versions")).json()
    assert len(versions) == 2


@pytest.mark.asyncio
async def test_advance_crud_and_installment_versioning(client, session):
    ctx = await _admin_context(client, session)
    employee_id = ctx["employee_id"]

    created = await client.post(
        f"/api/employees/{employee_id}/advances",
        json={
            "advance_type": "festival",
            "principal": "10000.00",
            "sanctioned_on": "2026-01-15",
            "reference": "FEST-2026-001",
            "installment": {
                "installment_amount": "1000.00",
                "installments_total": 10,
                "installments_recovered_opening": 0,
                "effective_from": "2026-02-01",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    advance_id = body["id"]
    assert body["principal"] == "10000.00"
    assert body["installment_amount"] == "1000.00"

    listed = (await client.get(f"/api/employees/{employee_id}/advances")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == advance_id

    version = await client.post(
        f"/api/advances/{advance_id}/installment-versions",
        json={
            "effective_from": "2026-06-01",
            "installment_amount": "800.00",
            "installments_total": 12,
            "installments_recovered_opening": 2,
            "change_reason": "Restructured",
        },
    )
    assert version.status_code == 201, version.text
    assert version.json()["installment_amount"] == "800.00"


@pytest.mark.asyncio
async def test_accommodation_crud_and_charge_versioning(client, session):
    ctx = await _admin_context(client, session)
    employee_id = ctx["employee_id"]

    created = await client.post(
        f"/api/employees/{employee_id}/accommodation",
        json={
            "quarters_location": "mumbai",
            "quarters_identifier": "Block-A-12",
            "charge": {
                "license_fee": "1000.00",
                "informational_hra_foregone": "2500.00",
                "effective_from": "2026-01-01",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assignment_id = body["id"]
    assert body["license_fee"] == "1000.00"
    assert body["informational_hra_foregone"] == "2500.00"

    listed = (await client.get(f"/api/employees/{employee_id}/accommodation")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == assignment_id

    version = await client.post(
        f"/api/accommodation/{assignment_id}/charge-versions",
        json={
            "effective_from": "2026-04-01",
            "license_fee": "1200.00",
            "informational_hra_foregone": "2700.00",
        },
    )
    assert version.status_code == 201, version.text
    assert version.json()["license_fee"] == "1200.00"
    assert version.json()["informational_hra_foregone"] == "2700.00"


@pytest.mark.asyncio
async def test_report_configuration_upsert_and_list(client, session):
    await _admin_context(client, session)

    signatories = await client.put(
        "/api/report-configurations/signatories",
        json={"value": {"chair": "Director", "members": ["A", "B"]}},
    )
    assert signatories.status_code == 200, signatories.text
    assert signatories.json()["key"] == "signatories"

    account_heads = await client.put(
        "/api/report-configurations/account_heads",
        json={"value": {"salary": "4100", "pf": "4200"}},
    )
    assert account_heads.status_code == 200, account_heads.text
    assert account_heads.json()["key"] == "account_heads"

    listed = (await client.get("/api/report-configurations")).json()
    keys = {row["key"]: row["value"] for row in listed}
    assert keys["signatories"]["chair"] == "Director"
    assert keys["account_heads"]["salary"] == "4100"


# --- calc_kind matrix ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("calc_kind", "payload_extra", "expect_status"),
    [
        ("fixed_recurring_amount", {"amount": "1000.00"}, 201),
        ("direct_monthly_amount", {"amount": "2000.00"}, 201),
        (
            "percentage_of_component_bases",
            {"rate": "0.1200", "basis": ["BASIS_A"]},
            201,
        ),
        ("employer_employee_contribution", {"rate": "0.1200"}, 201),
        ("loan_installment_recovery", {}, 201),
        ("accommodation_charge", {}, 201),
        ("one_time_adjustment", {}, 201),
        ("fixed_recurring_amount", {}, 422),
        ("fixed_recurring_amount", {"amount": "1000.00", "rate": "0.0100"}, 422),
        ("direct_monthly_amount", {"rate": "0.0100"}, 422),
        ("percentage_of_component_bases", {"basis": ["BASIS_A"]}, 422),
        ("percentage_of_component_bases", {"rate": "0.1200", "basis": ["UNKNOWN"]}, 400),
        ("employer_employee_contribution", {"amount": "100.00", "rate": "0.1200"}, 422),
        ("employer_employee_contribution", {}, 422),
    ],
)
async def test_component_rate_calc_kind_matrix(
    client,
    session,
    calc_kind,
    payload_extra,
    expect_status,
):
    await _admin_context(client, session)
    await _create_component(client, code="BASIS_A", name="Basis A")
    component = await _create_component(client, code="TARGET", name="Target")

    body = {
        "effective_from": "2026-01-01",
        "calc_kind": calc_kind,
        "rounding_rule": "ROUND_HALF_UP_RUPEE",
        **payload_extra,
    }
    resp = await client.post(
        f"/api/pay-components/{component['id']}/rate-versions",
        json=body,
    )
    assert resp.status_code == expect_status, resp.text


@pytest.mark.asyncio
async def test_component_rate_invalid_rounding_rule_422(client, session):
    await _admin_context(client, session)
    component = await _create_component(client, code="ROUND", name="Rounding")

    resp = await client.post(
        f"/api/pay-components/{component['id']}/rate-versions",
        json={
            "effective_from": "2026-01-01",
            "calc_kind": "fixed_recurring_amount",
            "amount": "1000.00",
            "rounding_rule": "ROUND_NONE",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_component_rate_invalid_calc_kind_string_422(client, session):
    await _admin_context(client, session)
    component = await _create_component(client, code="KIND", name="Kind")

    resp = await client.post(
        f"/api/pay-components/{component['id']}/rate-versions",
        json={
            "effective_from": "2026-01-01",
            "calc_kind": "not_a_real_kind",
            "amount": "1000.00",
            "rounding_rule": "ROUND_HALF_UP_RUPEE",
        },
    )
    assert resp.status_code == 422


# --- Immutable code/classification --------------------------------------------


@pytest.mark.asyncio
async def test_patch_pay_component_code_returns_409_and_leaves_unchanged(client, session):
    await _admin_context(client, session)
    created = await _create_component(client, code="IMMUTABLE")
    component_id = created["id"]

    resp = await client.patch(
        f"/api/pay-components/{component_id}",
        json={"code": "CHANGED"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "ConflictError"

    fetched = (await client.get("/api/pay-components")).json()
    match = next(c for c in fetched if c["id"] == component_id)
    assert match["code"] == "IMMUTABLE"


@pytest.mark.asyncio
async def test_patch_pay_component_classification_returns_409(client, session):
    await _admin_context(client, session)
    created = await _create_component(client, code="CLASS")
    component_id = created["id"]

    resp = await client.patch(
        f"/api/pay-components/{component_id}",
        json={"classification": "ag_deduction"},
    )
    assert resp.status_code == 409


# --- Termination via end_on ---------------------------------------------------


@pytest.mark.asyncio
async def test_recurring_instruction_termination_via_end_on(client, session):
    ctx = await _admin_context(client, session)
    component = await _create_component(client, code="TERM")
    employee_id = ctx["employee_id"]

    created = await client.post(
        f"/api/employees/{employee_id}/recurring-instructions",
        json={
            "component_id": component["id"],
            "effective_from": "2026-01-01",
            "amount": "1500.00",
        },
    )
    assert created.status_code == 201
    instruction_id = created.json()["id"]

    terminated = await client.post(
        f"/api/recurring-instructions/{instruction_id}/versions",
        json={"end_on": "2026-06-01"},
    )
    assert terminated.status_code == 201
    assert terminated.json()["effective_to"] == "2026-06-01"

    before = await client.get(
        f"/api/employees/{employee_id}/recurring-instructions",
        params={"as_of": "2026-05-31"},
    )
    assert len(before.json()) == 1

    on_end = await client.get(
        f"/api/employees/{employee_id}/recurring-instructions",
        params={"as_of": "2026-06-01"},
    )
    assert on_end.json() == []

    after = await client.get(
        f"/api/employees/{employee_id}/recurring-instructions",
        params={"as_of": "2026-07-01"},
    )
    assert after.json() == []


# --- Advance validation -------------------------------------------------------


@pytest.mark.asyncio
async def test_advance_installment_amount_exceeds_principal_422(client, session):
    ctx = await _admin_context(client, session)
    employee_id = ctx["employee_id"]

    resp = await client.post(
        f"/api/employees/{employee_id}/advances",
        json={
            "advance_type": "other",
            "principal": "5000.00",
            "sanctioned_on": "2026-01-01",
            "installment": {
                "installment_amount": "6000.00",
                "installments_total": 10,
                "installments_recovered_opening": 0,
                "effective_from": "2026-02-01",
            },
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_advance_recovered_opening_exceeds_total_422(client, session):
    ctx = await _admin_context(client, session)
    employee_id = ctx["employee_id"]

    resp = await client.post(
        f"/api/employees/{employee_id}/advances",
        json={
            "advance_type": "other",
            "principal": "5000.00",
            "sanctioned_on": "2026-01-01",
            "installment": {
                "installment_amount": "500.00",
                "installments_total": 10,
                "installments_recovered_opening": 11,
                "effective_from": "2026-02-01",
            },
        },
    )
    assert resp.status_code == 422


# --- Accommodation independent money fields -----------------------------------


@pytest.mark.asyncio
async def test_accommodation_license_fee_and_hra_foregone_independent(client, session):
    ctx = await _admin_context(client, session)
    employee_id = ctx["employee_id"]

    resp = await client.post(
        f"/api/employees/{employee_id}/accommodation",
        json={
            "quarters_location": "worli",
            "quarters_identifier": "W-9",
            "charge": {
                "license_fee": "1000.00",
                "informational_hra_foregone": "2500.00",
                "effective_from": "2026-01-01",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["license_fee"] == "1000.00"
    assert body["informational_hra_foregone"] == "2500.00"

    listed = (await client.get(f"/api/employees/{employee_id}/accommodation")).json()
    assert listed[0]["license_fee"] == "1000.00"
    assert listed[0]["informational_hra_foregone"] == "2500.00"


# --- Capability gates ---------------------------------------------------------


@pytest.mark.asyncio
async def test_auditor_cannot_view_pay_components(client, dev_settings, session):
    org_id, admin_id = await _create_org_as_admin(client)
    auditor = await seed_user(session, email="auditor@example.com", name="Auditor")
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

    resp = await client.get("/api/pay-components")
    assert resp.status_code == 403
    assert resp.json()["error"] == "urn:accord:capability:view_master_data"


@pytest.mark.asyncio
async def test_payroll_reviewer_can_get_but_not_post_pay_components(client, dev_settings, session):
    org_id, _admin_id = await _create_org_as_admin(client)
    reviewer = await seed_user(session, email="reviewer@example.com", name="Reviewer")
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=reviewer.id,
        role="payroll_reviewer",
    )
    await session.commit()

    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=reviewer.id,
        active_organization_id=org_id,
    )
    apply_session_cookie(client, cookie)

    get_resp = await client.get("/api/pay-components")
    assert get_resp.status_code == 200

    post_resp = await client.post(
        "/api/pay-components",
        json={
            "code": "REV",
            "name": "Reviewer Blocked",
            "classification": "earning",
        },
    )
    assert post_resp.status_code == 403
    assert post_resp.json()["error"] == "urn:accord:capability:manage_master_data"


# --- Tenant isolation ---------------------------------------------------------


async def _dual_org_admin(client, session, dev_settings) -> dict:
    org_a_id, admin_id = await _create_org_as_admin(client)

    org_b = await seed_organization(session, name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=admin_id,
        role="organization_administrator",
    )
    await session.commit()
    return {"org_a_id": org_a_id, "org_b_id": org_b.id, "admin_id": admin_id}


@pytest.mark.asyncio
async def test_tenant_isolation_pay_component_patch_404_after_switch(client, session, dev_settings):
    worlds = await _dual_org_admin(client, session, dev_settings)
    component = await _create_component(client, code="ORG_A_ONLY")
    component_id = component["id"]

    switch = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(worlds["org_b_id"])},
    )
    assert switch.status_code == 200
    cookie = session_cookie_from_response(switch)
    if cookie:
        client.cookies.set("accord_session", cookie)

    listed = (await client.get("/api/pay-components")).json()
    assert all(c["id"] != component_id for c in listed)

    patch = await client.patch(
        f"/api/pay-components/{component_id}",
        json={"name": "Should Not Apply"},
    )
    assert patch.status_code == 404


@pytest.mark.asyncio
async def test_tenant_isolation_recurring_instruction_versions_404_after_switch(
    client, session, dev_settings
):
    worlds = await _dual_org_admin(client, session, dev_settings)
    employee = await _seed_employee(
        session,
        org_id=worlds["org_a_id"],
        user_id=worlds["admin_id"],
    )
    component = await _create_component(client, code="RI_ORG_A")

    created = await client.post(
        f"/api/employees/{employee.id}/recurring-instructions",
        json={
            "component_id": component["id"],
            "effective_from": "2026-01-01",
            "amount": "500.00",
        },
    )
    assert created.status_code == 201
    instruction_id = created.json()["id"]

    switch = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(worlds["org_b_id"])},
    )
    assert switch.status_code == 200
    cookie = session_cookie_from_response(switch)
    if cookie:
        client.cookies.set("accord_session", cookie)

    versions = await client.get(f"/api/recurring-instructions/{instruction_id}/versions")
    assert versions.status_code == 404


# --- as_of boundary for recurring versions ------------------------------------


@pytest.mark.asyncio
async def test_recurring_instruction_as_of_version_boundary(client, session):
    ctx = await _admin_context(client, session)
    component = await _create_component(client, code="ASOF")
    employee_id = ctx["employee_id"]

    created = await client.post(
        f"/api/employees/{employee_id}/recurring-instructions",
        json={
            "component_id": component["id"],
            "effective_from": "2026-01-01",
            "amount": "1000.00",
        },
    )
    assert created.status_code == 201
    instruction_id = created.json()["id"]

    terminated = await client.post(
        f"/api/recurring-instructions/{instruction_id}/versions",
        json={"end_on": "2026-04-01"},
    )
    assert terminated.status_code == 201
    assert terminated.json()["effective_to"] == "2026-04-01"

    cases = [
        ("2025-12-31", 0),
        ("2026-01-01", 1),
        ("2026-03-31", 1),
        ("2026-04-01", 0),
    ]
    for as_of, expected_count in cases:
        resp = await client.get(
            f"/api/employees/{employee_id}/recurring-instructions",
            params={"as_of": as_of},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == expected_count, (
            f"as_of={as_of}: expected {expected_count}, got {len(items)}"
        )
        if expected_count:
            assert items[0]["amount"] == "1000.00"
