"""June 2026 golden E2E: full HTTP payroll workflow reproduces fixture totals.

Seeding mapping (fixture line type → API / resolution source)
-----------------------------------------------------------
| Fixture component              | Seed API / source                                      |
| ------------------------------ | ------------------------------------------------------ |
| BASIC                          | POST /api/employees pay.basic_pay (employee pay version)|
| DA, HRA, TRANSPORT,            | POST /api/pay-components/{id}/rate-versions            |
| OTHER_ALLOWANCE,               |   (calc_kind=fixed_recurring_amount) +                 |
| GPF_SUBSCRIPTION, NPS_*, EPF_*,| POST /api/employees/{id}/recurring-instructions       |
| INCOME_TAX, PROFESSIONAL_TAX,  |                                                       |
| GIS                            |                                                       |
| HBA_INSTALLMENT                | POST /api/employees/{id}/advances (advance_type=hba)  |
|                                |   with nested installment version                      |
| ACCOMMODATION_LICENSE_FEE      | POST /api/employees/{id}/accommodation + charge        |
| FOREGONE_HRA                   | Same accommodation charge                              |
|                                |   ``informational_hra_foregone`` (resolver emits       |
|                                |   informational / excluded_from_totals line)           |
| Catalog FOREGONE_HRA row       | **Not creatable** via POST /api/pay-components —       |
|                                |   classification ``informational`` is absent from the  |
|                                |   PayComponentCreate enum (product gap; documented)    |

Org-wide component_rate_versions alone are out of scope for resolution; every
non-BASIC amount is seeded per-employee as above.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll_runs import payroll_employee_results, payroll_result_lines
from app.models.platform import AuditEvent, OutboxEvent, PayrollApproval
from app.tenancy import bind_tenant_context
from tests.e2e.fixture_loader import (
    ACCOMMODATION_COMPONENT_CODES,
    ADVANCE_COMPONENT_CODES,
    BASIC_CODE,
    RECURRING_COMPONENT_CODES,
    EmployeeSeed,
    JuneFixture,
    line_amount,
    load_june_fixture,
    map_quarters_location,
    map_regime,
    money_str,
)
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_user,
    session_cookie_from_response,
)

EFFECTIVE_FROM = "2026-01-01"
AS_OF_PERIOD_YEAR = 2026
AS_OF_PERIOD_MONTH = 6


def _dec(value: str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def _auth_as(
    client: AsyncClient,
    session: AsyncSession,
    settings_obj,
    *,
    org_id: UUID,
    user_id: UUID,
) -> None:
    cookie = await mint_session_cookie(
        session,
        settings_obj,
        user_id=user_id,
        active_organization_id=org_id,
    )
    apply_session_cookie(client, cookie)


async def _create_org_as_admin(client: AsyncClient, fixture: JuneFixture) -> tuple[UUID, UUID]:
    resp, cookie = await login_dev(client)
    assert resp.status_code in {200, 302}, resp.text
    assert cookie, "expected accord_session cookie from login"
    client.cookies.set("accord_session", cookie)

    slug = f"june-e2e-{uuid4().hex[:10]}"
    resp = await client.post(
        "/api/organizations",
        json={"name": fixture.organization.name, "slug": slug},
    )
    assert resp.status_code == 201, resp.text
    cookie = session_cookie_from_response(resp) or cookie
    client.cookies.set("accord_session", cookie)
    body = resp.json()
    return UUID(body["active_organization"]["id"]), UUID(body["id"])


async def _seed_role_users(
    session: AsyncSession,
    *,
    org_id: UUID,
) -> dict[str, UUID]:
    if session.in_transaction():
        await session.rollback()

    preparer = await seed_user(
        session,
        email=f"preparer-{uuid4().hex[:8]}@june-e2e.test",
        name="June Preparer",
    )
    approver = await seed_user(
        session,
        email=f"approver-{uuid4().hex[:8]}@june-e2e.test",
        name="June Approver",
    )
    releaser = await seed_user(
        session,
        email=f"releaser-{uuid4().hex[:8]}@june-e2e.test",
        name="June Releaser",
    )
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=preparer.id,
        role="payroll_preparer",
    )
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=approver.id,
        role="payroll_approver",
    )
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=releaser.id,
        role="report_releaser",
    )
    await session.commit()
    return {
        "preparer": preparer.id,
        "approver": approver.id,
        "releaser": releaser.id,
    }


async def _create_org_structure(
    client: AsyncClient,
    fixture: JuneFixture,
) -> tuple[dict[str, UUID], UUID, UUID]:
    office_ids: dict[str, UUID] = {}
    for office in fixture.organization.offices:
        resp = await client.post(
            "/api/offices",
            json={
                "name": office.name,
                "code": office.code,
                "jurisdiction": office.jurisdiction,
            },
        )
        assert resp.status_code == 201, resp.text
        office_ids[office.fixture_id] = UUID(resp.json()["id"])

    unit = await client.post(
        "/api/payroll-units",
        json={
            "name": fixture.organization.pay_unit_name,
            "code": fixture.organization.pay_unit_code,
        },
    )
    assert unit.status_code == 201, unit.text
    post = await client.post(
        "/api/posts",
        json={"designation": "Synthetic Clerk", "class_name": "III"},
    )
    assert post.status_code == 201, post.text
    return office_ids, UUID(unit.json()["id"]), UUID(post.json()["id"])


async def _create_components(client: AsyncClient, fixture: JuneFixture) -> dict[str, UUID]:
    """Create catalog rows the API accepts; skip informational FOREGONE_HRA."""
    component_ids: dict[str, UUID] = {}
    display_order = 0
    for comp in fixture.components:
        display_order += 1
        if comp.api_classification is None:
            # Product gap: informational FOREGONE_HRA cannot be catalogued via API.
            # Resolver still emits FOREGONE_HRA from accommodation charge versions.
            assert comp.code == "FOREGONE_HRA"
            continue
        resp = await client.post(
            "/api/pay-components",
            json={
                "code": comp.code,
                "name": comp.name,
                "classification": comp.api_classification,
                "display_order": display_order,
            },
        )
        assert resp.status_code == 201, (
            f"create component {comp.code}: {resp.status_code} {resp.text}"
        )
        component_id = UUID(resp.json()["id"])
        component_ids[comp.code] = component_id

        # Rate versions required for recurring-instruction resolution.
        if comp.code in RECURRING_COMPONENT_CODES or comp.code == BASIC_CODE:
            rate = await client.post(
                f"/api/pay-components/{component_id}/rate-versions",
                json={
                    "effective_from": EFFECTIVE_FROM,
                    "calc_kind": "fixed_recurring_amount",
                    "amount": "0.00",
                    "rounding_rule": "ROUND_HALF_UP_RUPEE",
                },
            )
            assert rate.status_code == 201, (
                f"rate version {comp.code}: {rate.status_code} {rate.text}"
            )

    assert len(component_ids) == 16, (
        f"expected 16 API-creatable components, got {len(component_ids)}: {sorted(component_ids)}"
    )
    return component_ids


def _profile_payload(employee: EmployeeSeed) -> dict[str, Any]:
    regime, gpf_jurisdiction = map_regime(employee.regime)
    profile: dict[str, Any] = {
        "name": employee.name,
        "sevarth_id": employee.sevarth_id,
        "pan": employee.pan,
        "date_of_birth": "1985-01-15",
        "date_of_joining": "2010-06-01",
        "retirement_regime": regime,
    }
    if regime == "gpf":
        profile["gpf_jurisdiction"] = gpf_jurisdiction
        profile["gpf_account_number"] = employee.gpf_account
        # Optional PRAN is allowed on GPF profiles in API tests.
        if employee.pran:
            profile["pran"] = employee.pran
    elif regime == "nps":
        profile["pran"] = employee.pran or f"9000{employee.fixture_id[-4:].zfill(8)}"
    elif regime == "epf":
        profile["epf_number"] = employee.epf_number or f"SYNTEPF/{employee.fixture_id}/UAN"
    return profile


async def _create_employee(
    client: AsyncClient,
    employee: EmployeeSeed,
    *,
    office_ids: dict[str, UUID],
    unit_id: UUID,
    post_id: UUID,
) -> UUID:
    basic = line_amount(employee, BASIC_CODE)
    assert basic is not None, f"{employee.fixture_id} missing BASIC"
    payload = {
        "employee_number": employee.fixture_id,
        "effective_from": EFFECTIVE_FROM,
        "profile": _profile_payload(employee),
        "posting": {
            "office_id": str(office_ids[employee.office_id]),
            "payroll_unit_id": str(unit_id),
            "post_id": str(post_id),
        },
        "pay": {"pay_matrix_level": "L10", "basic_pay": money_str(basic)},
        "bank": {
            "account_number": employee.bank_account,
            "ifsc": employee.ifsc,
            "bank_name": "Synthetic Bank",
            "branch": "Synthetic Branch",
            "is_primary_salary": True,
        },
    }
    resp = await client.post("/api/employees", json=payload)
    assert resp.status_code == 201, (
        f"create employee {employee.fixture_id}: {resp.status_code} {resp.text}"
    )
    return UUID(resp.json()["id"])


async def _seed_employee_amounts(
    client: AsyncClient,
    employee: EmployeeSeed,
    *,
    employee_id: UUID,
    component_ids: dict[str, UUID],
) -> None:
    for line in employee.lines:
        code = line.component_code
        if code == BASIC_CODE:
            continue
        if code in RECURRING_COMPONENT_CODES:
            resp = await client.post(
                f"/api/employees/{employee_id}/recurring-instructions",
                json={
                    "component_id": str(component_ids[code]),
                    "effective_from": EFFECTIVE_FROM,
                    "amount": money_str(line.amount),
                    "reason": f"June fixture {code}",
                },
            )
            assert resp.status_code == 201, (
                f"{employee.fixture_id} recurring {code}: {resp.status_code} {resp.text}"
            )
            continue
        if code in ADVANCE_COMPONENT_CODES:
            principal = max(line.amount * Decimal("24"), line.amount)
            resp = await client.post(
                f"/api/employees/{employee_id}/advances",
                json={
                    "advance_type": "hba",
                    "principal": money_str(principal),
                    "sanctioned_on": EFFECTIVE_FROM,
                    "reference": f"HBA-{employee.fixture_id}",
                    "installment": {
                        "installment_amount": money_str(line.amount),
                        "installments_total": 24,
                        "installments_recovered_opening": 0,
                        "effective_from": EFFECTIVE_FROM,
                    },
                },
            )
            assert resp.status_code == 201, (
                f"{employee.fixture_id} advance {code}: {resp.status_code} {resp.text}"
            )
            continue
        if code == "ACCOMMODATION_LICENSE_FEE":
            assert employee.accommodation is not None
            foregone = line_amount(employee, "FOREGONE_HRA")
            charge: dict[str, Any] = {
                "license_fee": money_str(line.amount),
                "effective_from": EFFECTIVE_FROM,
            }
            if foregone is not None:
                charge["informational_hra_foregone"] = money_str(foregone)
            resp = await client.post(
                f"/api/employees/{employee_id}/accommodation",
                json={
                    "quarters_location": map_quarters_location(employee.accommodation.location),
                    "quarters_identifier": f"Q-{employee.fixture_id}",
                    "charge": charge,
                },
            )
            assert resp.status_code == 201, (
                f"{employee.fixture_id} accommodation: {resp.status_code} {resp.text}"
            )
            continue
        if code in ACCOMMODATION_COMPONENT_CODES:
            # FOREGONE_HRA is seeded with the accommodation charge above.
            continue
        raise AssertionError(f"No seeding strategy for {employee.fixture_id} line {code}")


async def _sum_component_amounts(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    version_id: UUID,
) -> dict[str, Decimal]:
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        rows = (
            await session.execute(
                sa.select(
                    payroll_result_lines.c.component_code,
                    sa.func.sum(payroll_result_lines.c.amount),
                )
                .select_from(
                    payroll_result_lines.join(
                        payroll_employee_results,
                        payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                    )
                )
                .where(
                    payroll_employee_results.c.organization_id == org_id,
                    payroll_employee_results.c.run_version_id == version_id,
                )
                .group_by(payroll_result_lines.c.component_code)
            )
        ).all()
    return {code: _dec(total) for code, total in rows}


async def _sum_gpf_by_jurisdiction(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    version_id: UUID,
    employee_meta: dict[str, EmployeeSeed],
) -> dict[str, Decimal]:
    """GPF jurisdiction is on the employee profile, not result-line trace."""
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        rows = (
            await session.execute(
                sa.select(
                    payroll_employee_results.c.employee_number,
                    payroll_result_lines.c.amount,
                )
                .select_from(
                    payroll_result_lines.join(
                        payroll_employee_results,
                        payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                    )
                )
                .where(
                    payroll_employee_results.c.organization_id == org_id,
                    payroll_employee_results.c.run_version_id == version_id,
                    payroll_result_lines.c.component_code == "GPF_SUBSCRIPTION",
                )
            )
        ).all()
    totals = {"mumbai": Decimal("0.00"), "nagpur": Decimal("0.00")}
    for employee_number, amount in rows:
        meta = employee_meta[employee_number]
        _, jurisdiction = map_regime(meta.regime)
        assert jurisdiction in totals
        totals[jurisdiction] = _dec(totals[jurisdiction] + _dec(amount))
    return totals


async def _sum_accommodation_by_location(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    version_id: UUID,
    employee_meta: dict[str, EmployeeSeed],
) -> dict[str, Decimal]:
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=user_id)
        rows = (
            await session.execute(
                sa.select(
                    payroll_employee_results.c.employee_number,
                    payroll_result_lines.c.amount,
                )
                .select_from(
                    payroll_result_lines.join(
                        payroll_employee_results,
                        payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                    )
                )
                .where(
                    payroll_employee_results.c.organization_id == org_id,
                    payroll_employee_results.c.run_version_id == version_id,
                    payroll_result_lines.c.component_code == "ACCOMMODATION_LICENSE_FEE",
                )
            )
        ).all()
    totals = {"mumbai": Decimal("0.00"), "worli": Decimal("0.00")}
    for employee_number, amount in rows:
        meta = employee_meta[employee_number]
        assert meta.accommodation is not None
        location = map_quarters_location(meta.accommodation.location)
        assert location in totals
        totals[location] = _dec(totals[location] + _dec(amount))
    return totals


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_june_2026_golden_e2e_full_workflow(client, session, dev_settings):
    fixture = load_june_fixture()
    assert len(fixture.employees) == 32
    expected = fixture.expected.aggregates

    org_id, admin_id = await _create_org_as_admin(client, fixture)
    roles = await _seed_role_users(session, org_id=org_id)
    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=admin_id)

    office_ids, unit_id, post_id = await _create_org_structure(client, fixture)
    component_ids = await _create_components(client, fixture)

    employee_ids: dict[str, UUID] = {}
    employee_meta: dict[str, EmployeeSeed] = {}
    for emp in fixture.employees:
        emp_id = await _create_employee(
            client,
            emp,
            office_ids=office_ids,
            unit_id=unit_id,
            post_id=post_id,
        )
        employee_ids[emp.fixture_id] = emp_id
        employee_meta[emp.fixture_id] = emp
        await _seed_employee_amounts(
            client,
            emp,
            employee_id=emp_id,
            component_ids=component_ids,
        )

    period = await client.post(
        "/api/payroll-periods",
        json={
            "period_year": AS_OF_PERIOD_YEAR,
            "period_month": AS_OF_PERIOD_MONTH,
        },
    )
    assert period.status_code == 201, period.text
    run = await client.post(
        "/api/payroll-runs",
        json={"period_id": period.json()["id"], "run_type": "regular"},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]

    # Preparer owns calculate → validate → submit (maker side of maker-checker).
    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=roles["preparer"])

    calc1 = await client.post(f"/api/payroll-runs/{run_id}/calculate")
    assert calc1.status_code == 200, calc1.text
    calc1_body = calc1.json()
    content_hash = calc1_body["content_hash"]
    version_id = UUID(calc1_body["version_id"])
    totals = calc1_body["totals"]

    assert _dec(totals["earnings_total"]) == _dec(expected["salary_earnings"])
    assert _dec(totals["employer_contribution_total"]) == _dec(expected["employer_share"])
    assert _dec(totals["gross_total"]) == _dec(expected["gross_bill"])
    assert _dec(totals["deductions_total"]) == _dec(expected["total_deductions"])
    assert _dec(totals["net_payable"]) == _dec(expected["net_payable"])

    results = await client.get(f"/api/payroll-runs/{run_id}/results")
    assert results.status_code == 200, results.text
    results_body = results.json()
    assert results_body["version"]["content_hash"] == content_hash
    assert _dec(results_body["totals"]["earnings_total"]) == _dec(expected["salary_earnings"])
    assert _dec(results_body["totals"]["employer_contribution_total"]) == _dec(
        expected["employer_share"]
    )
    assert _dec(results_body["totals"]["gross_total"]) == _dec(expected["gross_bill"])
    assert _dec(results_body["totals"]["deductions_total"]) == _dec(expected["total_deductions"])
    assert _dec(results_body["totals"]["net_payable"]) == _dec(expected["net_payable"])
    assert len(results_body["employees"]) == 32

    component_sums = await _sum_component_amounts(
        session, org_id=org_id, user_id=admin_id, version_id=version_id
    )
    assert component_sums["GPF_SUBSCRIPTION"] == _dec(expected["gpf_total"])
    assert component_sums["NPS_EMPLOYEE"] == _dec(expected["nps_employee"])
    assert component_sums["NPS_EMPLOYER_TRANSFER"] == _dec(expected["nps_employer"])
    assert component_sums["EPF_EMPLOYEE"] == _dec(expected["epf_employee"])
    assert component_sums["EPF_EMPLOYER"] == _dec(expected["epf_employer"])
    assert component_sums["EPF_EMPLOYER_TRANSFER"] == _dec(expected["epf_employer"])
    assert component_sums["INCOME_TAX"] == _dec(expected["income_tax"])
    assert component_sums["GIS"] == _dec(expected["gis"])
    assert component_sums["HBA_INSTALLMENT"] == _dec(expected["hba"])
    assert component_sums["PROFESSIONAL_TAX"] == _dec(expected["professional_tax"])
    assert component_sums["ACCOMMODATION_LICENSE_FEE"] == _dec(expected["accommodation_total"])
    # FOREGONE_HRA must exist but is excluded from engine totals.
    assert "FOREGONE_HRA" in component_sums
    assert component_sums["FOREGONE_HRA"] > Decimal("0.00")

    gpf_by_jurisdiction = await _sum_gpf_by_jurisdiction(
        session,
        org_id=org_id,
        user_id=admin_id,
        version_id=version_id,
        employee_meta=employee_meta,
    )
    assert gpf_by_jurisdiction["mumbai"] == _dec(expected["gpf_mumbai"])
    assert gpf_by_jurisdiction["nagpur"] == _dec(expected["gpf_nagpur"])

    acc_by_location = await _sum_accommodation_by_location(
        session,
        org_id=org_id,
        user_id=admin_id,
        version_id=version_id,
        employee_meta=employee_meta,
    )
    assert acc_by_location["mumbai"] == _dec(expected["accommodation_mumbai"])
    assert acc_by_location["worli"] == _dec(expected["accommodation_worli"])

    # Determinism: recalculate through the full stack → same content_hash.
    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=roles["preparer"])
    calc2 = await client.post(f"/api/payroll-runs/{run_id}/calculate")
    assert calc2.status_code == 200, calc2.text
    assert calc2.json()["content_hash"] == content_hash
    version_id = UUID(calc2.json()["version_id"])

    validated = await client.post(f"/api/payroll-runs/{run_id}/validate")
    assert validated.status_code == 200, validated.text
    validated_body = validated.json()
    assert validated_body["blocking"] is False
    assert validated_body["status"] == "calculated"

    submitted = await client.post(
        f"/api/payroll-runs/{run_id}/submit",
        json={"reason": "June golden ready"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"

    # payroll_preparer lacks approve_run → capability gate 403 (not maker_checker).
    # Product gap vs a literal "preparer self-approve → 409": the capability check
    # runs first. Prove maker_checker below with org admin (submit_run+approve_run).
    preparer_approve = await client.post(
        f"/api/payroll-runs/{run_id}/approve",
        json={"reason": "should fail capability"},
    )
    assert preparer_approve.status_code == 403, preparer_approve.text
    assert preparer_approve.json()["error"] == "urn:accord:capability:approve_run"

    withdrawn = await client.post(f"/api/payroll-runs/{run_id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "calculated"

    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=admin_id)
    admin_submitted = await client.post(
        f"/api/payroll-runs/{run_id}/submit",
        json={"reason": "June golden ready (admin maker)"},
    )
    assert admin_submitted.status_code == 200, admin_submitted.text

    self_approve = await client.post(
        f"/api/payroll-runs/{run_id}/approve",
        json={"reason": "should fail maker_checker"},
    )
    assert self_approve.status_code == 409, self_approve.text
    assert self_approve.json()["error"] == "urn:accord:workflow:maker_checker"

    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=roles["approver"])
    approved = await client.post(
        f"/api/payroll-runs/{run_id}/approve",
        json={"reason": "June golden approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=roles["releaser"])
    posted = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": f"june-post-{uuid4().hex}"},
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"

    # Audit chain + outbox + approval content_hash binding.
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await bind_tenant_context(session, organization_id=org_id, user_id=admin_id)
        run_uuid = UUID(run_id)
        audit_commands = set(
            (
                await session.execute(
                    sa.select(AuditEvent.command).where(
                        AuditEvent.organization_id == org_id,
                        AuditEvent.entity_id == run_uuid,
                        AuditEvent.entity_type == "payroll_run",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "submit" in audit_commands
        assert "approve" in audit_commands
        assert "payroll_run.post" in audit_commands

        outbox = (
            (
                await session.execute(
                    sa.select(OutboxEvent).where(
                        OutboxEvent.organization_id == org_id,
                        OutboxEvent.event_type == "payroll_run.posted",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(outbox) == 1

        approvals = (
            (
                await session.execute(
                    sa.select(PayrollApproval).where(
                        PayrollApproval.organization_id == org_id,
                        PayrollApproval.run_id == run_uuid,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_action = {row.action: row for row in approvals}
        assert by_action["submit"].content_hash == content_hash
        assert by_action["approve"].content_hash == content_hash
        assert by_action["post"].content_hash == content_hash
        assert by_action["submit"].run_version_id == version_id
        assert by_action["approve"].run_version_id == version_id
        assert by_action["post"].run_version_id == version_id

        # Immutability: runtime UPDATE on posted result lines must be blocked.
        line_id = (
            await session.execute(
                sa.select(payroll_result_lines.c.id)
                .select_from(
                    payroll_result_lines.join(
                        payroll_employee_results,
                        payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                    )
                )
                .where(payroll_employee_results.c.run_version_id == version_id)
                .limit(1)
            )
        ).scalar_one()

    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=admin_id)
    with pytest.raises(DBAPIError, match="(?i)accord: UPDATE/DELETE forbidden"):
        await session.execute(
            sa.update(payroll_result_lines)
            .where(payroll_result_lines.c.id == line_id)
            .values(amount=Decimal("1.00"))
        )
        await session.flush()
    await session.rollback()

    # Second post without matching idempotency key → 409.
    await _auth_as(client, session, dev_settings, org_id=org_id, user_id=roles["releaser"])
    second_post = await client.post(
        f"/api/payroll-runs/{run_id}/post",
        headers={"Idempotency-Key": f"june-post-again-{uuid4().hex}"},
    )
    assert second_post.status_code == 409, second_post.text
