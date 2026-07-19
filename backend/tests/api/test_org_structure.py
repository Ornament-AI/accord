"""Integration tests for organization-structure master data routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.org_structure import router as org_structure_router
from app.main import create_app
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_organization,
    seed_user,
    session_cookie_from_response,
)


def _org_structure_app():
    application = create_app()
    application.include_router(org_structure_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _org_structure_app()
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
    return UUID(body["active_organization"]["id"]), UUID(body["id"])


# --- CRUD happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_office_crud(client, session):
    await _create_org_as_admin(client)

    created = await client.post(
        "/api/offices",
        json={"name": "Mumbai HQ", "code": "MUM-01", "jurisdiction": "mumbai"},
    )
    assert created.status_code == 201, created.text
    office = created.json()
    assert office["jurisdiction"] == "mumbai"

    listed = (await client.get("/api/offices")).json()
    assert [o["code"] for o in listed] == ["MUM-01"]

    patched = await client.patch(
        f"/api/offices/{office['id']}",
        json={"name": "Mumbai Head Office", "jurisdiction": "worli"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Mumbai Head Office"
    assert patched.json()["jurisdiction"] == "worli"


@pytest.mark.asyncio
async def test_payroll_unit_and_employee_group_crud(client, session):
    await _create_org_as_admin(client)

    for path, payload in (
        ("/api/payroll-units", {"name": "Unit A", "code": "UNIT-A"}),
        ("/api/employee-groups", {"name": "Group 1", "code": "GRP-1"}),
    ):
        created = await client.post(path, json=payload)
        assert created.status_code == 201, created.text
        listed = (await client.get(path)).json()
        assert [x["code"] for x in listed] == [payload["code"]]
        patched = await client.patch(
            f"{path}/{created.json()['id']}",
            json={"name": "Renamed"},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_post_crud_with_class_field_mapping(client, session):
    await _create_org_as_admin(client)

    created = await client.post(
        "/api/posts",
        json={"designation": "Junior Engineer", "class_name": "Class III"},
    )
    assert created.status_code == 201, created.text
    post = created.json()
    assert post["class_name"] == "Class III"

    patched = await client.patch(
        f"/api/posts/{post['id']}",
        json={"class_name": "Class II"},
    )
    assert patched.status_code == 200
    assert patched.json()["class_name"] == "Class II"


# --- Conflicts and immutability -------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_codes_conflict(client, session):
    await _create_org_as_admin(client)

    for path, payload in (
        ("/api/offices", {"name": "A", "code": "DUP", "jurisdiction": "other"}),
        ("/api/payroll-units", {"name": "A", "code": "DUP"}),
        ("/api/employee-groups", {"name": "A", "code": "DUP"}),
        ("/api/posts", {"designation": "DUP", "class_name": "Class I"}),
    ):
        first = await client.post(path, json=payload)
        assert first.status_code == 201, first.text
        second = await client.post(path, json={**payload, "name": "B"})
        assert second.status_code == 409, f"{path}: {second.text}"


@pytest.mark.asyncio
async def test_immutable_natural_keys(client, session):
    await _create_org_as_admin(client)

    office = (
        await client.post(
            "/api/offices",
            json={"name": "A", "code": "OFF-1", "jurisdiction": "other"},
        )
    ).json()
    resp = await client.patch(f"/api/offices/{office['id']}", json={"code": "OFF-2"})
    assert resp.status_code == 409

    post = (
        await client.post(
            "/api/posts",
            json={"designation": "Engineer", "class_name": "Class I"},
        )
    ).json()
    resp = await client.patch(f"/api/posts/{post['id']}", json={"designation": "Manager"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_missing_entity_404(client, session):
    await _create_org_as_admin(client)
    resp = await client.patch(f"/api/offices/{uuid4()}", json={"name": "X"})
    assert resp.status_code == 404


# --- Capability gates ------------------------------------------------------------


@pytest.mark.asyncio
async def test_reviewer_reads_structure_but_cannot_write(client, dev_settings, session):
    org_id, _admin_id = await _create_org_as_admin(client)
    await client.post(
        "/api/offices",
        json={"name": "A", "code": "OFF-1", "jurisdiction": "other"},
    )

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

    assert (await client.get("/api/offices")).status_code == 200

    write = await client.post(
        "/api/offices",
        json={"name": "B", "code": "OFF-2", "jurisdiction": "other"},
    )
    assert write.status_code == 403
    assert write.json()["error"] == "urn:accord:capability:manage_master_data"


# --- Tenant isolation -------------------------------------------------------------


@pytest.mark.asyncio
async def test_offices_are_tenant_isolated_with_same_code(client, dev_settings, session):
    org_a_id, admin_id = await _create_org_as_admin(client)
    resp = await client.post(
        "/api/offices",
        json={"name": "Org A Office", "code": "SHARED", "jurisdiction": "mumbai"},
    )
    assert resp.status_code == 201

    org_b = await seed_organization(session, name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=admin_id,
        role="organization_administrator",
    )
    await session.commit()

    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=admin_id,
        active_organization_id=org_b.id,
    )
    apply_session_cookie(client, cookie)

    # Same code is creatable in org B and org A's office is invisible.
    assert (await client.get("/api/offices")).json() == []
    dup = await client.post(
        "/api/offices",
        json={"name": "Org B Office", "code": "SHARED", "jurisdiction": "nagpur"},
    )
    assert dup.status_code == 201, dup.text
    listed = (await client.get("/api/offices")).json()
    assert [o["name"] for o in listed] == ["Org B Office"]
