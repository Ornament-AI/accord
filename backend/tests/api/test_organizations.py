"""Integration tests for POST /api/organizations."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.capabilities import CAPABILITIES
from app.models.identity import Organization, OrganizationMembership
from tests.identity_helpers import login_dev, session_cookie_from_response


@pytest.mark.asyncio
async def test_create_organization_201_defaults_and_admin_capabilities(
    client, dev_settings, session
):
    await login_dev(client)

    resp = await client.post(
        "/api/organizations",
        json={"name": "Acme Payroll", "slug": "acme-payroll"},
    )
    assert resp.status_code == 201
    rotated = session_cookie_from_response(resp)
    if rotated:
        client.cookies.set("accord_session", rotated)
    body = resp.json()
    assert body["active_organization"] is not None
    active = body["active_organization"]
    assert active["name"] == "Acme Payroll"
    assert active["slug"] == "acme-payroll"
    assert active["role"] == "organization_administrator"
    assert set(active["capabilities"]) == set(CAPABILITIES)
    assert any(o["slug"] == "acme-payroll" for o in body["organizations"])

    org = (
        await session.execute(select(Organization).where(Organization.slug == "acme-payroll"))
    ).scalar_one()
    assert org.is_active is True

    membership = (
        await session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org.id,
            )
        )
    ).scalar_one()
    assert membership.role == "organization_administrator"
    assert membership.is_active is True


@pytest.mark.asyncio
async def test_create_organization_409_slug_conflict(client, dev_settings):
    await login_dev(client)
    first = await client.post(
        "/api/organizations",
        json={"name": "First", "slug": "taken-slug"},
    )
    assert first.status_code == 201
    rotated = session_cookie_from_response(first)
    assert rotated
    client.cookies.set("accord_session", rotated)

    second = await client.post(
        "/api/organizations",
        json={"name": "Second", "slug": "taken-slug"},
    )
    assert second.status_code == 409
    assert second.json()["error"] == "ConflictError"


@pytest.mark.parametrize(
    "slug",
    [
        "UPPERCASE",
        "a",  # too short
        "a" * 51,  # too long
        "api",  # reserved
    ],
)
@pytest.mark.asyncio
async def test_create_organization_422_invalid_slug(client, dev_settings, slug):
    await login_dev(client)
    resp = await client.post(
        "/api/organizations",
        json={"name": "Bad Slug Org", "slug": slug},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "RequestValidationError"
