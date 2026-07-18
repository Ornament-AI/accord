# GATE-D-FINDING: Any authenticated user can create unlimited organizations.
# Exact location: backend/app/api/routes/organizations.py
#   create_organization_route (POST /api/organizations) depends only on CurrentUser
#   — it does NOT call require_capability("manage_organization") or otherwise gate
#   on role/capabilities. backend/app/services/organizations.py then inserts the
#   creator as organization_administrator of the new org.
# Expected (adversarial / least-privilege): creating orgs should require a
#   platform-level or explicit capability, not merely "has a valid session".
# Actual: a payroll_preparer without manage_organization (and, by the same
#   CurrentUser-only gate, any authenticated principal including users with
#   zero memberships) receives HTTP 201 and becomes admin of a new org.
# Reproduce:
#   1) preparer_a + active org A → mint cookie →
#      POST /api/organizations {"name":"X","slug":"gate-d-prep-spawn"} → 201
#   2) outsider (no memberships) → mint cookie →
#      POST /api/organizations {"name":"Y","slug":"gate-d-outsider-spawn"} → 201
# Do not "fix" here — Gate D documents the behavior only.

"""HTTP-level cross-tenant isolation: switch-org, /me dual-session, deactivation."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.capabilities import capabilities_for_role
from app.models.identity import OrganizationMembership
from tests.gate_d.conftest import TwoOrgWorld, apply_session_cookie, mint_session_cookie


@pytest.mark.asyncio
async def test_admin_a_cannot_switch_to_org_b(client, dev_settings, session, two_org_world):
    world: TwoOrgWorld = two_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.admin_a.id,
        active_organization_id=world.org_a.id,
    )
    apply_session_cookie(client, cookie)

    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(world.org_b.id)},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "MembershipForbidden"
    assert body["status"] == 403


@pytest.mark.asyncio
async def test_user_ab_switch_updates_role_and_capabilities(
    client, dev_settings, session, two_org_world
):
    world: TwoOrgWorld = two_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.user_ab.id,
        active_organization_id=world.org_a.id,
    )
    apply_session_cookie(client, cookie)

    me_a = (await client.get("/api/auth/me")).json()
    assert me_a["active_organization"]["id"] == str(world.org_a.id)
    assert me_a["active_organization"]["role"] == "organization_administrator"
    assert set(me_a["active_organization"]["capabilities"]) == set(
        capabilities_for_role("organization_administrator")
    )

    resp = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(world.org_b.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_organization"]["id"] == str(world.org_b.id)
    assert body["active_organization"]["role"] == "payroll_reviewer"
    assert set(body["active_organization"]["capabilities"]) == set(
        capabilities_for_role("payroll_reviewer")
    )
    # Stale-role bug would keep admin capabilities after switching to reviewer org.
    assert "manage_organization" not in body["active_organization"]["capabilities"]
    assert "manage_members" not in body["active_organization"]["capabilities"]


@pytest.mark.asyncio
async def test_user_ab_me_lists_same_orgs_active_differs_by_session(
    client, dev_settings, session, two_org_world
):
    world: TwoOrgWorld = two_org_world
    cookie_a = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.user_ab.id,
        active_organization_id=world.org_a.id,
    )
    cookie_b = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.user_ab.id,
        active_organization_id=world.org_b.id,
    )

    apply_session_cookie(client, cookie_a)
    me_a = (await client.get("/api/auth/me")).json()
    apply_session_cookie(client, cookie_b)
    me_b = (await client.get("/api/auth/me")).json()

    orgs_a = sorted(me_a["organizations"], key=lambda o: o["id"])
    orgs_b = sorted(me_b["organizations"], key=lambda o: o["id"])
    assert orgs_a == orgs_b
    assert {o["id"] for o in orgs_a} == {str(world.org_a.id), str(world.org_b.id)}

    assert me_a["active_organization"]["id"] == str(world.org_a.id)
    assert me_b["active_organization"]["id"] == str(world.org_b.id)
    assert me_a["active_organization"]["role"] == "organization_administrator"
    assert me_b["active_organization"]["role"] == "payroll_reviewer"
    assert set(me_a["active_organization"]["capabilities"]) != set(
        me_b["active_organization"]["capabilities"]
    )


@pytest.mark.asyncio
async def test_deactivate_membership_hides_org_and_blocks_switch(
    client, dev_settings, session, two_org_world
):
    world: TwoOrgWorld = two_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.user_ab.id,
        active_organization_id=world.org_a.id,
    )
    apply_session_cookie(client, cookie)

    result = await session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == world.org_a.id,
            OrganizationMembership.user_id == world.user_ab.id,
        )
    )
    membership = result.scalar_one()
    membership.is_active = False
    await session.commit()

    me = (await client.get("/api/auth/me")).json()
    listed_ids = {o["id"] for o in me["organizations"]}
    assert str(world.org_a.id) not in listed_ids
    assert str(world.org_b.id) in listed_ids
    assert me["active_organization"] is None

    switch = await client.post(
        "/api/auth/switch-organization",
        json={"organization_id": str(world.org_a.id)},
    )
    assert switch.status_code == 403
    assert switch.json()["error"] == "MembershipForbidden"


@pytest.mark.asyncio
async def test_preparer_can_create_organization_without_manage_capability(
    client, dev_settings, session, two_org_world
):
    """Documents GATE-D-FINDING: org create is gated only by authentication."""
    world: TwoOrgWorld = two_org_world
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=world.preparer_a.id,
        active_organization_id=world.org_a.id,
    )
    apply_session_cookie(client, cookie)

    me = (await client.get("/api/auth/me")).json()
    assert me["active_organization"]["role"] == "payroll_preparer"
    assert "manage_organization" not in me["active_organization"]["capabilities"]

    resp = await client.post(
        "/api/organizations",
        json={"name": "Preparer Spawned Org", "slug": "gate-d-prep-spawn"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active_organization"]["role"] == "organization_administrator"
    assert "manage_organization" in body["active_organization"]["capabilities"]


@pytest.mark.asyncio
async def test_outsider_can_create_organization_with_no_memberships(
    client, dev_settings, session, two_org_world
):
    """Documents GATE-D-FINDING: zero-membership users can still spawn orgs."""
    world: TwoOrgWorld = two_org_world
    cookie = await mint_session_cookie(session, dev_settings, user_id=world.outsider.id)
    apply_session_cookie(client, cookie)

    me = (await client.get("/api/auth/me")).json()
    assert me["organizations"] == []
    assert me["active_organization"] is None

    resp = await client.post(
        "/api/organizations",
        json={"name": "Outsider Spawned Org", "slug": "gate-d-outsider-spawn"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active_organization"]["role"] == "organization_administrator"
    assert "manage_organization" in body["active_organization"]["capabilities"]
