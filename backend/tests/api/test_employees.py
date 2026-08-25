"""Integration tests for Phase 3 employee master-data HTTP API."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.main import app as fastapi_app
from app.api.routes.employees import router as employees_router
from app.models.org_structure import Office, Post
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import seed_membership, seed_organization, seed_user

if not any(getattr(r, "path", "").startswith("/api/employees") for r in fastapi_app.routes):
    fastapi_app.include_router(employees_router, prefix="/api")


async def _seed_posting_refs(session, org_id: UUID) -> tuple[Office, Post]:
    office = Office(
        organization_id=org_id,
        name="HQ",
        jurisdiction="mumbai",
    )
    post = Post(organization_id=org_id, designation=f"Clerk-{uuid4().hex[:6]}", class_="III")
    session.add_all([office, post])
    await session.flush()
    return office, post


async def _admin_world(session, dev_settings, client, *, slug: str | None = None):
    org = await seed_organization(
        session,
        name="Emp API Org",
        slug=slug or f"emp-api-{uuid4().hex[:10]}",
    )
    admin = await seed_user(session, name="Org Admin")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=admin.id,
        role="organization_administrator",
    )
    office, post = await _seed_posting_refs(session, org.id)
    await session.commit()
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=admin.id,
        active_organization_id=org.id,
    )
    apply_session_cookie(client, cookie)
    return org, admin, office, post


def _profile_payload(regime: str) -> dict:
    base = {
        "name": "Alice",
        "sevarth_id": f"SEV-{uuid4().hex[:6]}",
        "pan": "ABCDE1234F",
        "date_of_birth": "1990-01-15",
        "date_of_joining": "2015-06-01",
        "retirement_regime": regime,
        "payroll_export_remark": "Recovery adjusted manually",
    }
    if regime == "gpf":
        base["gpf_jurisdiction"] = "mumbai"
        base["pran"] = "123456789012"
        base["gpf_account_number"] = "GPF998877"
    elif regime == "nps":
        base["pran"] = "123456789012"
    elif regime == "epf":
        base["epf_number"] = "EPF998877"
    return base


def _create_payload(
    *,
    office_id: UUID,
    post_id: UUID,
    regime: str = "gpf",
    employee_number: str | None = None,
    effective_from: str = "2026-01-01",
    basic_pay: object = "50732.00",
) -> dict:
    return {
        "employee_number": employee_number or f"E-{uuid4().hex[:6]}",
        "effective_from": effective_from,
        "profile": _profile_payload(regime),
        "posting": {
            "office_id": str(office_id),
            "post_id": str(post_id),
        },
        "pay": {"pay_matrix_level": "L10", "basic_pay": basic_pay},
        "bank": {
            "account_number": "123456789012",
            "ifsc": "SBIN0001234",
            "bank_name": "SBI",
            "branch": "Main",
            "is_primary_salary": True,
        },
    }


async def _create_employee(client, payload: dict) -> dict:
    resp = await client.post("/api/employees", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _auth_as(session, dev_settings, client, org_id: UUID, user, role: str) -> None:
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=user.id,
        role=role,
    )
    await session.commit()
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=user.id,
        active_organization_id=org_id,
    )
    apply_session_cookie(client, cookie)


# --- Composite create (all regimes) ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("regime", ["gpf", "nps", "epf"])
async def test_create_employee_all_regimes_masks_sensitive_and_money_string(
    client, session, dev_settings, regime
):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    body = await _create_employee(
        client,
        _create_payload(
            office_id=office.id,
            post_id=post.id,
            regime=regime,
        ),
    )
    assert body["profile"]["retirement_regime"] == regime
    assert body["profile"]["payroll_export_remark"] == "Recovery adjusted manually"
    assert body["profile"]["pan"] == "••••234F"
    assert body["bank"]["account_number"] == "••••9012"
    assert body["pay"]["basic_pay"] == "50732.00"
    assert body["posting"]["pay_bill_post_id"] == str(post.id)
    assert isinstance(body["pay"]["basic_pay"], str)


# --- Validation -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_rejects_numeric_basic_pay(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    payload = _create_payload(
        office_id=office.id,
        post_id=post.id,
        basic_pay=50732.00,
    )
    resp = await client.post("/api/employees", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_allows_gpf_with_unknown_jurisdiction(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    payload = _create_payload(office_id=office.id, post_id=post.id)
    del payload["profile"]["gpf_jurisdiction"]
    resp = await client.post("/api/employees", json=payload)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_create_rejects_nps_with_jurisdiction(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    payload = _create_payload(
        office_id=office.id,
        post_id=post.id,
        regime="nps",
    )
    payload["profile"]["gpf_jurisdiction"] = "mumbai"
    resp = await client.post("/api/employees", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_allows_unknown_legacy_profile_fields(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    payload = _create_payload(
        office_id=office.id,
        post_id=post.id,
        regime="nps",
    )
    payload["profile"]["sevarth_id"] = None
    payload["profile"]["date_of_birth"] = None
    payload["profile"]["date_of_joining"] = None
    payload["pay"]["pay_matrix_level"] = None
    payload["bank"]["branch"] = None

    created = await _create_employee(client, payload)

    assert created["profile"]["sevarth_id"] is None
    assert created["profile"]["date_of_birth"] is None
    assert created["profile"]["date_of_joining"] is None
    assert created["pay"]["pay_matrix_level"] is None
    assert created["pay"]["basic_pay"] == "50732.00"
    assert created["bank"]["branch"] is None


@pytest.mark.asyncio
async def test_posting_pay_bill_group_create_change_and_read(client, session, dev_settings):
    org, _, office, post = await _admin_world(session, dev_settings, client)
    pay_bill_post = Post(
        organization_id=org.id,
        designation=f"Combined Establishment-{uuid4().hex[:6]}",
        pay_bill_heading="Accounts and Audit Establishment",
        class_="Class II",
        sanctioned_strength=10,
        vacant_count=2,
        pay_scale="S-18: 49100-155800",
        display_order=5,
    )
    session.add(pay_bill_post)
    await session.commit()

    payload = _create_payload(office_id=office.id, post_id=post.id)
    payload["posting"]["pay_bill_post_id"] = str(pay_bill_post.id)
    created = await _create_employee(client, payload)
    employee_id = created["id"]
    assert created["posting"]["post_id"] == str(post.id)
    assert created["posting"]["pay_bill_post_id"] == str(pay_bill_post.id)

    changed = await client.post(
        f"/api/employees/{employee_id}/versions/posting",
        json={
            "effective_from": "2026-07-01",
            "office_id": str(office.id),
            "post_id": str(post.id),
            "change_reason": "Return to designation group",
        },
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["pay_bill_post_id"] == str(post.id)

    june = await client.get(f"/api/employees/{employee_id}", params={"as_of": "2026-06-30"})
    july = await client.get(f"/api/employees/{employee_id}", params={"as_of": "2026-07-01"})
    assert june.status_code == 200, june.text
    assert july.status_code == 200, july.text
    assert june.json()["posting"]["pay_bill_post_id"] == str(pay_bill_post.id)
    assert july.json()["posting"]["pay_bill_post_id"] == str(post.id)


# --- Pay as_of boundary -----------------------------------------------------------


@pytest.mark.asyncio
async def test_pay_version_as_of_before_on_after_boundary(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    employee_id = created["id"]

    future = await client.post(
        f"/api/employees/{employee_id}/versions/pay",
        json={
            "effective_from": "2026-07-01",
            "pay_matrix_level": "L11",
            "basic_pay": "55000.00",
            "change_reason": "annual increment",
        },
    )
    assert future.status_code == 201, future.text

    cases = [
        ("2026-06-30", "L10", "50732.00"),
        ("2026-07-01", "L11", "55000.00"),
        ("2026-08-01", "L11", "55000.00"),
    ]
    for as_of, level, pay in cases:
        resp = await client.get(f"/api/employees/{employee_id}", params={"as_of": as_of})
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        assert detail["pay"]["pay_matrix_level"] == level
        assert detail["pay"]["basic_pay"] == pay


@pytest.mark.asyncio
async def test_list_employee_versions_returns_newest_first_and_honors_reveal(
    client, session, dev_settings
):
    org, _, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    employee_id = created["id"]

    future = await client.post(
        f"/api/employees/{employee_id}/versions/pay",
        json={
            "effective_from": "2026-07-01",
            "pay_matrix_level": "L11",
            "basic_pay": "55000.00",
            "change_reason": "annual increment",
        },
    )
    assert future.status_code == 201, future.text

    pay_response = await client.get(f"/api/employees/{employee_id}/versions/pay")
    assert pay_response.status_code == 200, pay_response.text
    assert [
        (version["effective_from"], version["effective_to"], version["basic_pay"])
        for version in pay_response.json()
    ] == [
        ("2026-07-01", None, "55000.00"),
        ("2026-01-01", "2026-07-01", "50732.00"),
    ]

    masked = await client.get(f"/api/employees/{employee_id}/versions/profile")
    assert masked.status_code == 200, masked.text
    assert masked.json()[0]["pan"] == "••••234F"

    revealed = await client.get(
        f"/api/employees/{employee_id}/versions/profile",
        params={"reveal": "true"},
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()[0]["pan"] == "ABCDE1234F"

    preparer = await seed_user(session, name="Version History Preparer")
    await _auth_as(session, dev_settings, client, org.id, preparer, "payroll_preparer")
    blocked = await client.get(
        f"/api/employees/{employee_id}/versions/profile",
        params={"reveal": "true"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "urn:accord:capability:reveal_sensitive_fields"


# --- Version / employee conflicts -------------------------------------------------


@pytest.mark.asyncio
async def test_overlapping_effective_from_returns_409(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    employee_id = created["id"]

    overlap = await client.post(
        f"/api/employees/{employee_id}/versions/pay",
        json={
            "effective_from": "2026-01-01",
            "pay_matrix_level": "L12",
            "basic_pay": "60000.00",
        },
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"] == "ConflictError"


@pytest.mark.asyncio
async def test_duplicate_employee_number_returns_409(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    payload = _create_payload(
        office_id=office.id,
        post_id=post.id,
        employee_number="E-DUP-001",
    )
    assert (await client.post("/api/employees", json=payload)).status_code == 201

    dup = await client.post("/api/employees", json=payload)
    assert dup.status_code == 409
    assert dup.json()["error"] == "ConflictError"


# --- Bank primary conflict --------------------------------------------------------


@pytest.mark.asyncio
async def test_bank_primary_same_effective_from_returns_409(client, session, dev_settings):
    _, _, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    employee_id = created["id"]

    conflict = await client.post(
        f"/api/employees/{employee_id}/versions/bank",
        json={
            "effective_from": "2026-01-01",
            "account_number": "999988887777",
            "ifsc": "SBIN0002222",
            "bank_name": "SBI",
            "branch": "Alt",
            "is_primary_salary": True,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "ConflictError"


# --- Masking + reveal -------------------------------------------------------------


@pytest.mark.asyncio
async def test_masking_default_and_reveal_admin_vs_preparer(client, session, dev_settings):
    org, admin, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    employee_id = created["id"]

    masked = await client.get(f"/api/employees/{employee_id}")
    assert masked.status_code == 200
    assert masked.json()["profile"]["pan"] == "••••234F"
    assert masked.json()["bank"]["account_number"] == "••••9012"

    revealed = await client.get(f"/api/employees/{employee_id}", params={"reveal": "true"})
    assert revealed.status_code == 200
    assert revealed.json()["profile"]["pan"] == "ABCDE1234F"
    assert revealed.json()["bank"]["account_number"] == "123456789012"

    preparer = await seed_user(session, name="Preparer")
    await _auth_as(session, dev_settings, client, org.id, preparer, "payroll_preparer")
    blocked = await client.get(f"/api/employees/{employee_id}", params={"reveal": "true"})
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "urn:accord:capability:reveal_sensitive_fields"


# --- Fail-closed / unknown-id isolation (single org, ADR 0011) --------------------


@pytest.mark.asyncio
async def test_unknown_employee_id_404(client, session, dev_settings):
    org, _, office, post = await _admin_world(session, dev_settings, client)
    await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    _ = org

    by_id = await client.get(f"/api/employees/{uuid4()}")
    assert by_id.status_code == 404


@pytest.mark.asyncio
async def test_unprovisioned_user_fail_closed_on_employees(client, session, dev_settings):
    org, _admin, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )
    outsider = await seed_user(session, name="Outsider")
    await session.commit()

    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=outsider.id,
            active_organization_id=org.id,
        ),
    )

    by_id = await client.get(f"/api/employees/{created['id']}")
    assert by_id.status_code == 409
    assert by_id.json()["error"] == "OrganizationContextRequired"

    listed = await client.get("/api/employees")
    assert listed.status_code == 409


# --- Capability gates -------------------------------------------------------------


@pytest.mark.asyncio
async def test_payroll_reviewer_can_get_but_not_post(client, session, dev_settings):
    org, _, office, post = await _admin_world(session, dev_settings, client)
    created = await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )

    reviewer = await seed_user(session, name="Reviewer")
    await _auth_as(session, dev_settings, client, org.id, reviewer, "payroll_reviewer")

    get_resp = await client.get(f"/api/employees/{created['id']}")
    assert get_resp.status_code == 200

    post_resp = await client.post(
        "/api/employees",
        json=_create_payload(office_id=office.id, post_id=post.id),
    )
    assert post_resp.status_code == 403
    assert post_resp.json()["error"] == "urn:accord:capability:manage_master_data"


@pytest.mark.asyncio
async def test_auditor_cannot_get_employees(client, session, dev_settings):
    org, _, office, post = await _admin_world(session, dev_settings, client)
    await _create_employee(
        client,
        _create_payload(office_id=office.id, post_id=post.id),
    )

    auditor = await seed_user(session, name="Auditor")
    await _auth_as(session, dev_settings, client, org.id, auditor, "auditor")

    resp = await client.get("/api/employees")
    assert resp.status_code == 403
    assert resp.json()["error"] == "urn:accord:capability:view_master_data"
