"""Integration tests for pay-setup master data routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.pay_setup import router as pay_setup_router
from app.main import create_app
from app.models.employees import Employee
from app.models.reports import ReportConfiguration
from app.tenancy import bind_tenant_context
from app.services.bootstrap import provision_organization
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_user,
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
    org_id, user_id = await _create_org_as_admin(client, session)
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
    created = await _create_component(client, code="CUSTOM_BASIC")
    component_id = created["id"]
    assert created["code"] == "CUSTOM_BASIC"
    assert created["classification"] == "earning"
    assert created["register_column"] is None

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
async def test_pay_component_register_column_is_typed_and_classification_safe(client, session):
    await _admin_context(client, session)
    created = await client.post(
        "/api/pay-components",
        json={
            "code": "CUSTOM_TRAVEL",
            "name": "Travel Allowance",
            "classification": "earning",
            "register_column": "additional_conveyance_transport_allowance",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["register_column"] == "additional_conveyance_transport_allowance"

    invalid_create = await client.post(
        "/api/pay-components",
        json={
            "code": "BAD_COLUMN",
            "name": "Bad Column",
            "classification": "earning",
            "register_column": "income_tax",
        },
    )
    assert invalid_create.status_code == 422

    invalid_update = await client.patch(
        f"/api/pay-components/{created.json()['id']}",
        json={"register_column": "income_tax"},
    )
    assert invalid_update.status_code == 400
    assert invalid_update.json()["error"] == "ValidationError"


@pytest.mark.asyncio
async def test_pay_component_employer_transfer_metadata_is_validated_and_editable(client, session):
    await _admin_context(client, session)
    contribution = await client.post(
        "/api/pay-components",
        json={
            "code": "CUSTOM_EPF_EMPLOYER",
            "name": "EPF Employer",
            "classification": "employer_contribution",
        },
    )
    assert contribution.status_code == 201, contribution.text

    transfer = await client.post(
        "/api/pay-components",
        json={
            "code": "CUSTOM_EPF_EMPLOYER_TRANSFER",
            "name": "EPF Employer Transfer",
            "classification": "ag_deduction",
            "employer_transfer": True,
            "transfer_of": "CUSTOM_EPF_EMPLOYER",
        },
    )
    assert transfer.status_code == 201, transfer.text
    body = transfer.json()
    assert body["employer_transfer"] is True
    assert body["transfer_of"] == "CUSTOM_EPF_EMPLOYER"

    patched = await client.patch(
        f"/api/pay-components/{body['id']}",
        json={"transfer_of": None},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["employer_transfer"] is True
    assert patched.json()["transfer_of"] is None

    for field in ("name", "display_order", "is_active", "employer_transfer"):
        null_update = await client.patch(
            f"/api/pay-components/{body['id']}",
            json={field: None},
        )
        assert null_update.status_code == 422, (field, null_update.text)

    unchanged = await client.get("/api/pay-components")
    assert unchanged.status_code == 200, unchanged.text
    saved = next(component for component in unchanged.json() if component["id"] == body["id"])
    assert saved["employer_transfer"] is True

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
            "quarters_address": "12 Example Road, Mumbai",
            "charge": {
                "license_fee": "1000.00",
                "house_rent": "700.00",
                "service_charge": "200.00",
                "parking_charge": "75.00",
                "additional_parking_charge": "25.00",
                "informational_hra_foregone": "2500.00",
                "effective_from": "2026-01-01",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assignment_id = body["id"]
    assert body["license_fee"] == "1000.00"
    assert body["quarters_address"] == "12 Example Road, Mumbai"
    assert body["service_charge"] == "200.00"
    assert body["informational_hra_foregone"] == "2500.00"

    listed = (await client.get(f"/api/employees/{employee_id}/accommodation")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == assignment_id

    updated = await client.patch(
        f"/api/accommodation/{assignment_id}",
        json={
            "quarters_identifier": "Block-A-14",
            "quarters_address": "14 Example Road, Mumbai",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["quarters_identifier"] == "Block-A-14"
    assert updated.json()["quarters_address"] == "14 Example Road, Mumbai"

    listed = (await client.get(f"/api/employees/{employee_id}/accommodation")).json()
    assert listed[0]["quarters_identifier"] == "Block-A-14"
    assert listed[0]["quarters_address"] == "14 Example Road, Mumbai"

    version = await client.post(
        f"/api/accommodation/{assignment_id}/charge-versions",
        json={
            "effective_from": "2026-04-01",
            "license_fee": "1200.00",
            "house_rent": "900.00",
            "service_charge": "200.00",
            "parking_charge": "100.00",
            "additional_parking_charge": "0.00",
            "informational_hra_foregone": "2700.00",
        },
    )
    assert version.status_code == 201, version.text
    assert version.json()["license_fee"] == "1200.00"
    assert version.json()["informational_hra_foregone"] == "2700.00"

    invalid_breakdown = await client.post(
        f"/api/accommodation/{assignment_id}/charge-versions",
        json={
            "effective_from": "2026-07-01",
            "license_fee": "1000.00",
            "house_rent": "900.00",
        },
    )
    assert invalid_breakdown.status_code == 400

    partial_breakdown = await client.post(
        f"/api/accommodation/{assignment_id}/charge-versions",
        json={
            "effective_from": "2026-08-01",
            "license_fee": "100.00",
            "house_rent": "100.00",
        },
    )
    assert partial_breakdown.status_code == 400

    worli_with_parking = await client.post(
        f"/api/employees/{employee_id}/accommodation",
        json={
            "quarters_location": "worli",
            "quarters_identifier": "Worli-12",
            "charge": {
                "license_fee": "100.00",
                "house_rent": "80.00",
                "service_charge": "10.00",
                "parking_charge": "10.00",
                "effective_from": "2026-09-01",
            },
        },
    )
    assert worli_with_parking.status_code == 422


@pytest.mark.asyncio
async def test_accommodation_rejects_partial_breakdown_even_when_it_sums(client, session):
    # A breakdown that leaves buckets NULL is rejected at input, even when the
    # provided buckets already sum to license_fee: the v3 export path treats NULL
    # buckets as incomplete, so explicit zeros must be entered here.
    ctx = await _admin_context(client, session)
    employee_id = ctx["employee_id"]

    resp = await client.post(
        f"/api/employees/{employee_id}/accommodation",
        json={
            "quarters_location": "mumbai",
            "quarters_identifier": "Block-B-1",
            "quarters_address": "1 Example Road, Mumbai",
            "charge": {
                "license_fee": "100.00",
                "house_rent": "100.00",
                "effective_from": "2026-01-01",
            },
        },
    )
    assert resp.status_code == 422, resp.text


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


@pytest.mark.asyncio
async def test_payroll_export_profile_round_trip(client, session):
    await _admin_context(client, session)

    initial = await client.get("/api/report-profile")
    assert initial.status_code == 200, initial.text
    assert initial.json()["value"]["ddo_code"] is None

    saved = await client.put(
        "/api/report-profile",
        json={
            "legal_name": "Acme Corporation",
            "office_name": "Payroll Office",
            "address_lines": ["Mumbai"],
            "ddo_code": "DDO-42",
            "administrative_department": "Finance Department",
            "fund_source": "Consolidated Fund",
            "plan_status": "Non-Plan",
            "nps_employee_account_head": "8342-00-117-01 Employee contribution",
            "nps_employer_account_head": "2071-01-117-01 Employer contribution",
            "head_of_account": {
                "demand_number": "17",
                "major_head": "2052",
                "sub_head": "090",
                "detailed_head": "01",
            },
            "bank_advice_recipient": {
                "bank_name": "State Bank",
                "branch": "Fort",
                "address_lines": ["Mumbai"],
            },
            "gpf_remittance_profiles": {
                "mumbai": {
                    "office_name": "Accountant General, Mumbai",
                    "address_lines": ["Mumbai"],
                    "account_code": "GPF-MUM",
                    "authority_text": "Maharashtra Treasury Rule 478",
                },
                "nagpur": {
                    "office_name": "Accountant General, Nagpur",
                    "address_lines": ["Nagpur"],
                    "account_code": "GPF-NGP",
                    "authority_text": "Maharashtra Treasury Rule 478",
                },
            },
            "signatories": [
                {"role": "maker", "name": "A. Maker", "designation": "Accountant"},
                {
                    "role": "final_approver",
                    "name": "F. Approver",
                    "designation": "Managing Director",
                },
            ],
            "pay_bill_footer_text": "Certified for treasury payment.",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["value"]["ddo_code"] == "DDO-42"
    assert saved.json()["value"]["fund_source"] == "Consolidated Fund"
    assert saved.json()["value"]["nps_employee_account_head"].startswith("8342")
    assert saved.json()["value"]["signatories"][1]["role"] == "final_approver"
    assert saved.json()["value"]["gpf_remittance_profiles"]["mumbai"]["account_code"] == "GPF-MUM"

    fetched = await client.get("/api/report-profile")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["value"] == saved.json()["value"]


@pytest.mark.asyncio
async def test_payroll_export_profile_read_ignores_legacy_signatory_roles(client, session):
    context = await _admin_context(client, session)
    stored_value = {
        "legal_name": "Acme Corporation",
        "signatories": [
            {
                "role": "legacy_certifying_officer",
                "name": "L. Officer",
                "designation": "Legacy Officer",
            },
            {
                "role": "maker",
                "name": "A. Maker",
                "designation": "Accountant",
            },
        ],
    }
    async with session.begin():
        await bind_tenant_context(
            session,
            organization_id=context["org_id"],
            user_id=context["user_id"],
        )
        configuration = ReportConfiguration(
            organization_id=context["org_id"],
            key="payroll_export_profile",
            value=stored_value,
        )
        session.add(configuration)

    fetched = await client.get("/api/report-profile")

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["value"]["legal_name"] == "Acme Corporation"
    assert fetched.json()["value"]["signatories"] == [
        {
            "role": "maker",
            "name": "A. Maker",
            "designation": "Accountant",
        }
    ]

    async with session.begin():
        await bind_tenant_context(
            session,
            organization_id=context["org_id"],
            user_id=context["user_id"],
        )
        await session.refresh(configuration)
        assert configuration.value == stored_value

    updated = await client.put(
        "/api/report-profile",
        json={
            **fetched.json()["value"],
            "office_name": "Updated without erasing legacy signatories",
        },
    )
    assert updated.status_code == 200, updated.text
    stored = (
        await session.execute(
            select(ReportConfiguration).where(ReportConfiguration.key == "payroll_export_profile")
        )
    ).scalar_one()
    assert stored.value["signatories"][0]["role"] == "legacy_certifying_officer"
    assert updated.json()["value"]["signatories"] == fetched.json()["value"]["signatories"]


@pytest.mark.asyncio
async def test_payroll_export_profile_write_rejects_unknown_signatory_role(client, session):
    await _admin_context(client, session)

    response = await client.put(
        "/api/report-profile",
        json={
            "signatories": [
                {
                    "role": "legacy_certifying_officer",
                    "name": "L. Officer",
                    "designation": "Legacy Officer",
                }
            ]
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_payroll_export_profile_reserved_from_generic_configuration(client, session):
    await _admin_context(client, session)

    response = await client.put(
        "/api/report-configurations/payroll_export_profile",
        json={"value": {"head_of_account": "invalid"}},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"


@pytest.mark.asyncio
async def test_standard_component_transfer_rules_are_immutable(client, session):
    await _admin_context(client, session)
    components = (await client.get("/api/pay-components")).json()
    transfer = next(item for item in components if item["code"] == "NPS_EMPLOYER_TRANSFER")

    response = await client.patch(
        f"/api/pay-components/{transfer['id']}",
        json={"employer_transfer": False, "transfer_of": None},
    )

    assert response.status_code == 409
    assert response.json()["error"] == "ConflictError"


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
                "house_rent": "800.00",
                "service_charge": "200.00",
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
    org_id, admin_id = await _create_org_as_admin(client, session)
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
    org_id, _admin_id = await _create_org_as_admin(client, session)
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


# --- Fail-closed / unknown-id isolation (single org, ADR 0011) ----------------


@pytest.mark.asyncio
async def test_pay_component_unknown_id_patch_404(client, session):
    await _create_org_as_admin(client, session)
    await _create_component(client, code="KNOWN")

    patch = await client.patch(
        f"/api/pay-components/{uuid4()}",
        json={"name": "Should Not Apply"},
    )
    assert patch.status_code == 404


@pytest.mark.asyncio
async def test_unprovisioned_user_fail_closed(client, session, dev_settings):
    """Authenticated user without membership cannot access tenant resources."""
    org_id, _admin_id = await _create_org_as_admin(client, session)
    component = await _create_component(client, code="BOUND")
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

    listed = await client.get("/api/pay-components")
    assert listed.status_code == 409
    assert listed.json()["error"] == "OrganizationContextRequired"

    patch = await client.patch(
        f"/api/pay-components/{component['id']}",
        json={"name": "Should Not Apply"},
    )
    assert patch.status_code == 409


@pytest.mark.asyncio
async def test_recurring_instruction_versions_unknown_id_404(client, session):
    ctx = await _admin_context(client, session)
    component = await _create_component(client, code="RI_KNOWN")
    created = await client.post(
        f"/api/employees/{ctx['employee_id']}/recurring-instructions",
        json={
            "component_id": component["id"],
            "effective_from": "2026-01-01",
            "amount": "500.00",
        },
    )
    assert created.status_code == 201

    versions = await client.get(f"/api/recurring-instructions/{uuid4()}/versions")
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
