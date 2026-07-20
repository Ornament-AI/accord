"""Integration tests for organization-structure master data routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.org_structure import router as org_structure_router
from app.main import create_app
from app.services.bootstrap import provision_organization
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_user,
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


# --- CRUD happy paths -----------------------------------------------------------


@pytest.mark.asyncio
async def test_office_crud(client, session):
    await _create_org_as_admin(client, session)

    created = await client.post(
        "/api/offices",
        json={"name": "Mumbai HQ", "jurisdiction": "mumbai"},
    )
    assert created.status_code == 201, created.text
    office = created.json()
    assert office["jurisdiction"] == "mumbai"
    assert "code" not in office

    listed = (await client.get("/api/offices")).json()
    assert [o["name"] for o in listed] == ["Mumbai HQ"]

    patched = await client.patch(
        f"/api/offices/{office['id']}",
        json={"name": "Mumbai Head Office", "jurisdiction": "worli"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Mumbai Head Office"
    assert patched.json()["jurisdiction"] == "worli"


@pytest.mark.asyncio
async def test_post_crud_with_class_field_mapping(client, session):
    await _create_org_as_admin(client, session)

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
async def test_remaining_natural_keys_conflict(client, session):
    await _create_org_as_admin(client, session)

    path = "/api/posts"
    payload = {"designation": "DUP", "class_name": "Class I"}
    first = await client.post(path, json=payload)
    assert first.status_code == 201, first.text
    second = await client.post(path, json={**payload, "class_name": "Class II"})
    assert second.status_code == 409, f"{path}: {second.text}"


@pytest.mark.asyncio
async def test_immutable_natural_keys(client, session):
    await _create_org_as_admin(client, session)

    post = (
        await client.post(
            "/api/posts",
            json={"designation": "Engineer", "class_name": "Class I"},
        )
    ).json()
    resp = await client.patch(f"/api/posts/{post['id']}", json={"designation": "Manager"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_legacy_office_codes_are_rejected(client, session):
    await _create_org_as_admin(client, session)

    office = await client.post(
        "/api/offices",
        json={"name": "A", "code": "OFF-1", "jurisdiction": "other"},
    )
    assert office.status_code == 422


@pytest.mark.asyncio
async def test_office_names_are_not_synthetic_keys(client, session):
    await _create_org_as_admin(client, session)

    for payload in (
        {"name": "Shared Name", "jurisdiction": "mumbai"},
        {"name": "Shared Name", "jurisdiction": "nagpur"},
    ):
        response = await client.post("/api/offices", json=payload)
        assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_update_missing_entity_404(client, session):
    await _create_org_as_admin(client, session)
    resp = await client.patch(f"/api/offices/{uuid4()}", json={"name": "X"})
    assert resp.status_code == 404


# --- Capability gates ------------------------------------------------------------


@pytest.mark.asyncio
async def test_reviewer_reads_structure_but_cannot_write(client, dev_settings, session):
    org_id, _admin_id = await _create_org_as_admin(client, session)
    await client.post(
        "/api/offices",
        json={"name": "A", "jurisdiction": "other"},
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
        json={"name": "B", "jurisdiction": "other"},
    )
    assert write.status_code == 403
    assert write.json()["error"] == "urn:accord:capability:manage_master_data"


# --- Fail-closed / unknown-id isolation (single org, ADR 0011) --------------------


@pytest.mark.asyncio
async def test_unknown_office_id_404(client, session):
    await _create_org_as_admin(client, session)
    await client.post(
        "/api/offices",
        json={"name": "Known Office", "jurisdiction": "mumbai"},
    )

    resp = await client.patch(
        f"/api/offices/{uuid4()}",
        json={"name": "Missing"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unprovisioned_user_fail_closed_on_offices(client, dev_settings, session):
    org_id, _admin_id = await _create_org_as_admin(client, session)
    resp = await client.post(
        "/api/offices",
        json={"name": "Known Office", "jurisdiction": "mumbai"},
    )
    assert resp.status_code == 201
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

    listed = await client.get("/api/offices")
    assert listed.status_code == 409
    assert listed.json()["error"] == "OrganizationContextRequired"
