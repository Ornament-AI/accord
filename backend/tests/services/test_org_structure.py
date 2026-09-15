"""Service tests for org-structure master data (T1.13 audit coverage)."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import AuditEvent
from app.schemas.org_structure import PostUpdate
from app.services import org_structure
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


async def _world(session: AsyncSession):
    org = await seed_organization(session, name="Org Svc Org", slug=f"os-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"os_{uuid4().hex[:10]}")
    await session.commit()
    await session.begin()
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    return org, user


async def _audit(session: AsyncSession, *, organization_id, command: str, entity_id) -> AuditEvent:
    return (
        await session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.command == command,
                AuditEvent.entity_id == entity_id,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_office_create_and_update_audit(session):
    org, user = await _world(session)

    office = await org_structure.create_office(
        session,
        org.id,
        actor_user_id=user.id,
        name="Head Office",
        jurisdiction="mumbai",
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="office.create",
        entity_id=office.id,
    )
    assert event.entity_type == "office"
    assert event.event_kind == "mutation"
    assert event.actor_user_id == user.id
    assert event.before_state == {}
    assert event.after_state["name"] == "Head Office"

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await org_structure.update_office(
        session,
        org.id,
        office.id,
        actor_user_id=user.id,
        name="HQ Renamed",
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="office.update",
        entity_id=office.id,
    )
    assert event.before_state["name"] == "Head Office"
    assert event.after_state["name"] == "HQ Renamed"


@pytest.mark.asyncio
async def test_post_create_and_update_audit(session):
    org, user = await _world(session)

    post = await org_structure.create_post(
        session,
        org.id,
        actor_user_id=user.id,
        designation=f"Clerk-{uuid4().hex[:6]}",
        class_name="III",
        sanctioned_strength=5,
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="post.create",
        entity_id=post.id,
    )
    assert event.entity_type == "post"
    assert event.actor_user_id == user.id
    assert event.before_state == {}
    assert event.after_state["sanctioned_strength"] == 5

    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
    await org_structure.update_post(
        session,
        org.id,
        post.id,
        actor_user_id=user.id,
        body=PostUpdate(vacant_count=2),
    )
    event = await _audit(
        session,
        organization_id=org.id,
        command="post.update",
        entity_id=post.id,
    )
    assert event.before_state["vacant_count"] is None
    assert event.after_state["vacant_count"] == 2
    assert event.summary["updated_fields"] == ["vacant_count"]
