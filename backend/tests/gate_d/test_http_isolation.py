"""HTTP-level singleton authz (ADR 0011): /me access states, removed multi-org routes."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.capabilities import capabilities_for_role
from app.models.identity import OrganizationMembership
from tests.gate_d.conftest import OneOrgWorld, apply_session_cookie, mint_session_cookie
from tests.identity_helpers import seed_user


@pytest.mark.asyncio
async def test_admin_me_is_active_with_singleton_membership(
    client, dev_settings, session, one_org_world
):
    world: OneOrgWorld = one_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.admin.id,
        active_organization_id=world.org.id,
    )
    apply_session_cookie(client, cookie)

    me = (await client.get("/api/auth/me")).json()
    assert me["access_state"] == "active"
    assert me["organization"]["id"] == str(world.org.id)
    assert me["organization"]["slug"] == "gate-d-org"
    assert me["membership"]["role"] == "organization_administrator"
    assert set(me["membership"]["capabilities"]) == set(
        capabilities_for_role("organization_administrator")
    )
    assert "organizations" not in me
    assert "active_organization" not in me


@pytest.mark.asyncio
async def test_outsider_me_is_unprovisioned(
    client, dev_settings, session, one_org_world
):
    world: OneOrgWorld = one_org_world
    cookie = await mint_session_cookie(session, dev_settings, user_id=world.outsider.id)
    apply_session_cookie(client, cookie)

    me = (await client.get("/api/auth/me")).json()
    assert me["access_state"] == "unprovisioned"
    assert me["organization"]["id"] == str(world.org.id)
    assert me["membership"] is None


@pytest.mark.asyncio
async def test_unbootstrapped_me_when_no_organization(client, dev_settings, session):
    user = await seed_user(
        session, workos_user_id="gate_d_unboot", email="unboot@gate-d.test"
    )
    await session.commit()
    cookie = await mint_session_cookie(session, dev_settings, user_id=user.id)
    apply_session_cookie(client, cookie)

    me = (await client.get("/api/auth/me")).json()
    assert me["access_state"] == "unbootstrapped"
    assert me["organization"] is None
    assert me["membership"] is None


@pytest.mark.asyncio
async def test_switch_organization_route_removed(
    client, dev_settings, session, one_org_world
):
    world: OneOrgWorld = one_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.admin.id,
        active_organization_id=world.org.id,
    )
    apply_session_cookie(client, cookie)

    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(world.org.id)},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_organization_route_removed(
    client, dev_settings, session, one_org_world
):
    world: OneOrgWorld = one_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.admin.id,
        active_organization_id=world.org.id,
    )
    apply_session_cookie(client, cookie)

    resp = await client.post(
        "/api/organizations",
        json={"name": "Spawn", "slug": "gate-d-spawn"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_membership_becomes_unprovisioned(
    client, dev_settings, session, one_org_world
):
    world: OneOrgWorld = one_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.preparer.id,
        active_organization_id=world.org.id,
    )
    apply_session_cookie(client, cookie)

    result = await session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == world.org.id,
            OrganizationMembership.user_id == world.preparer.id,
        )
    )
    membership = result.scalar_one()
    membership.is_active = False
    await session.commit()

    me = (await client.get("/api/auth/me")).json()
    assert me["access_state"] == "unprovisioned"
    assert me["organization"]["id"] == str(world.org.id)
    assert me["membership"] is None
