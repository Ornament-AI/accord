"""Integration tests for audit-event read routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.audit import router as audit_router
from app.main import create_app
from app.models.platform import AuditEvent
from app.tenancy import bind_tenant_context
from tests.identity_helpers import (
    login_dev,
    seed_membership,
    seed_organization,
    seed_user,
    session_cookie_from_response,
)


def _audit_app():
    # main.py is not modified in this lane; mount the router for exercise.
    application = create_app()
    application.include_router(audit_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _audit_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_org_as_admin(client) -> tuple[UUID, UUID]:
    await login_dev(client)
    slug = f"audit-{uuid4().hex[:8]}"
    resp = await client.post("/api/organizations", json={"name": "Audit Org", "slug": slug})
    assert resp.status_code == 201, resp.text
    cookie = session_cookie_from_response(resp)
    if cookie:
        client.cookies.set("accord_session", cookie)
    body = resp.json()
    org_id = UUID(body["active_organization"]["id"])
    user_id = UUID(body["id"])
    return org_id, user_id


async def _seed_audit_event(
    session,
    *,
    org_id: UUID,
    actor_user_id: UUID | None,
    command: str,
    entity_type: str,
    entity_id: UUID,
    summary: dict | None = None,
    request_id: str | None = None,
    created_at: datetime | None = None,
    bind_user_id: UUID | None = None,
    event_kind: str | None = None,
    entity_label: str | None = None,
    actor_snapshot: dict | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    """Insert an audit_events row under tenant GUC (same seed pattern as other API tests)."""
    async with session.begin():
        await bind_tenant_context(
            session,
            organization_id=org_id,
            user_id=bind_user_id or actor_user_id or uuid4(),
        )
        event = AuditEvent(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            command=command,
            entity_type=entity_type,
            entity_id=entity_id,
            event_kind=event_kind,
            entity_label=entity_label,
            actor_snapshot=actor_snapshot,
            before_state=before_state,
            after_state=after_state,
            metadata_=metadata or {},
            changed_count=1 if before_state != after_state and event_kind == "mutation" else 0,
            summary=summary or {"before": {}, "after": {}},
        )
        if created_at is not None:
            event.created_at = created_at
        session.add(event)
        await session.flush()
        event_id = event.id
    await session.commit()
    loaded = await session.get(AuditEvent, event_id)
    assert loaded is not None
    return loaded


# --- Unauthenticated ----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_audit_events_unauthenticated_401(client):
    # Every org role has view_audit, so the capability gate is nominal;
    # unauthenticated requests still fail at the auth layer.
    resp = await client.get("/api/audit-events")
    assert resp.status_code == 401


# --- List: pagination, ordering, filters, actor shape -------------------------


@pytest.mark.asyncio
async def test_list_pagination_newest_first_and_actor_shapes(client, session):
    org_a, user_a = await _create_org_as_admin(client)
    org_b = await seed_organization(session, name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    user_b = await seed_user(session, email=f"b-{uuid4().hex[:8]}@example.com", name="Org B Admin")
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=user_b.id,
        role="organization_administrator",
    )
    await session.commit()

    t0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    entity = uuid4()
    e1 = await _seed_audit_event(
        session,
        org_id=org_a,
        actor_user_id=user_a,
        command="submit",
        entity_type="payroll_run",
        entity_id=entity,
        created_at=t0,
        request_id="req-1",
        summary={"before": {"status": "draft"}, "after": {"status": "submitted"}},
        bind_user_id=user_a,
    )
    e2 = await _seed_audit_event(
        session,
        org_id=org_a,
        actor_user_id=None,
        command="artifact.download",
        entity_type="export_artifact",
        entity_id=uuid4(),
        created_at=t0 + timedelta(hours=1),
        summary={"action": "download"},
        bind_user_id=user_a,
    )
    e3 = await _seed_audit_event(
        session,
        org_id=org_a,
        actor_user_id=user_a,
        command="post",
        entity_type="payroll_run",
        entity_id=entity,
        created_at=t0 + timedelta(hours=2),
        bind_user_id=user_a,
    )
    # Other-org row must not appear in org A list.
    await _seed_audit_event(
        session,
        org_id=org_b.id,
        actor_user_id=user_b.id,
        command="approve",
        entity_type="payroll_run",
        entity_id=uuid4(),
        created_at=t0 + timedelta(hours=3),
        bind_user_id=user_b.id,
    )

    page1 = await client.get("/api/audit-events", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert body1["total"] == 3
    assert body1["page"] == 1
    assert body1["page_size"] == 2
    assert body1["total_pages"] == 2
    assert [item["id"] for item in body1["items"]] == [str(e3.id), str(e2.id)]

    # System event: actor null. User event: nested {id, name, email}.
    assert body1["items"][1]["actor"] is None
    actor = body1["items"][0]["actor"]
    assert actor is not None
    assert actor["id"] == str(user_a)
    assert actor["name"]
    assert actor["email"]

    page2 = await client.get("/api/audit-events", params={"page": 2, "page_size": 2})
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    assert [item["id"] for item in body2["items"]] == [str(e1.id)]
    assert "request_id" not in body2["items"][0]
    assert "summary" not in body2["items"][0]
    assert body2["items"][0]["has_structured_detail"] is False


@pytest.mark.asyncio
async def test_list_filter_entity_type(client, session):
    org_id, user_id = await _create_org_as_admin(client)
    run_id = uuid4()
    art_id = uuid4()
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="post",
        entity_type="payroll_run",
        entity_id=run_id,
        bind_user_id=user_id,
    )
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="artifact.download",
        entity_type="export_artifact",
        entity_id=art_id,
        bind_user_id=user_id,
    )

    resp = await client.get("/api/audit-events", params={"entity_type": "export_artifact"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "export_artifact"
    assert body["items"][0]["entity_id"] == str(art_id)


@pytest.mark.asyncio
async def test_list_filter_entity_id(client, session):
    org_id, user_id = await _create_org_as_admin(client)
    target = uuid4()
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="submit",
        entity_type="payroll_run",
        entity_id=target,
        bind_user_id=user_id,
    )
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="submit",
        entity_type="payroll_run",
        entity_id=uuid4(),
        bind_user_id=user_id,
    )

    resp = await client.get("/api/audit-events", params={"entity_id": str(target)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_id"] == str(target)


@pytest.mark.asyncio
async def test_list_filter_command(client, session):
    org_id, user_id = await _create_org_as_admin(client)
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="approve",
        entity_type="payroll_run",
        entity_id=uuid4(),
        bind_user_id=user_id,
    )
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="post",
        entity_type="payroll_run",
        entity_id=uuid4(),
        bind_user_id=user_id,
    )

    resp = await client.get("/api/audit-events", params={"command": "approve"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["command"] == "approve"


@pytest.mark.asyncio
async def test_list_filter_actor_user_id(client, session):
    org_id, admin_id = await _create_org_as_admin(client)
    other = await seed_user(session, email=f"other-{uuid4().hex[:8]}@example.com", name="Other")
    await seed_membership(
        session,
        organization_id=org_id,
        user_id=other.id,
        role="payroll_preparer",
    )
    await session.commit()

    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=admin_id,
        command="submit",
        entity_type="payroll_run",
        entity_id=uuid4(),
        bind_user_id=admin_id,
    )
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=other.id,
        command="submit",
        entity_type="payroll_run",
        entity_id=uuid4(),
        bind_user_id=admin_id,
    )

    resp = await client.get("/api/audit-events", params={"actor_user_id": str(other.id)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["actor"]["id"] == str(other.id)


@pytest.mark.asyncio
async def test_list_filter_from_to_window(client, session):
    org_id, user_id = await _create_org_as_admin(client)
    t0 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    early = await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="submit",
        entity_type="payroll_run",
        entity_id=uuid4(),
        created_at=t0,
        bind_user_id=user_id,
    )
    mid = await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="approve",
        entity_type="payroll_run",
        entity_id=uuid4(),
        created_at=t0 + timedelta(days=1),
        bind_user_id=user_id,
    )
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="post",
        entity_type="payroll_run",
        entity_id=uuid4(),
        created_at=t0 + timedelta(days=3),
        bind_user_id=user_id,
    )

    resp = await client.get(
        "/api/audit-events",
        params={
            "from": (t0 + timedelta(hours=12)).isoformat(),
            "to": (t0 + timedelta(days=2)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(mid.id)
    assert str(early.id) not in {i["id"] for i in body["items"]}


@pytest.mark.asyncio
async def test_list_from_after_to_422(client, session):
    await _create_org_as_admin(client)
    resp = await client.get(
        "/api/audit-events",
        params={
            "from": "2026-05-02T00:00:00Z",
            "to": "2026-05-01T00:00:00Z",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_invalid_command_pattern_422(client, session):
    await _create_org_as_admin(client)
    resp = await client.get("/api/audit-events", params={"command": "Bad Command!"})
    assert resp.status_code == 422


# --- Detail -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_happy_path(client, session):
    org_id, user_id = await _create_org_as_admin(client)
    entity_id = uuid4()
    event = await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="post",
        entity_type="payroll_run",
        entity_id=entity_id,
        request_id="detail-req",
        summary={"before": {"status": "approved"}, "after": {"status": "posted"}},
        bind_user_id=user_id,
        event_kind="mutation",
        entity_label="2026-07 Regular run",
        actor_snapshot={
            "id": str(user_id),
            "name": "Actor at event time",
            "email": "snapshot@example.com",
        },
        before_state={"status": "approved", "lock_version": 4},
        after_state={"status": "posted", "lock_version": 5},
    )

    resp = await client.get(f"/api/audit-events/{event.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(event.id)
    assert body["command"] == "post"
    assert body["entity_type"] == "payroll_run"
    assert body["entity_id"] == str(entity_id)
    assert body["request_id"] == "detail-req"
    assert body["event_kind"] == "mutation"
    assert body["entity_label"] == "2026-07 Regular run"
    assert body["changed_count"] == 1
    assert body["before_state"]["status"] == "approved"
    assert body["after_state"]["status"] == "posted"
    assert "summary" not in body
    assert body["actor"]["id"] == str(user_id)
    assert body["actor"]["name"] == "Actor at event time"
    assert body["actor"]["email"] == "snapshot@example.com"


@pytest.mark.asyncio
async def test_filter_options_are_exact_and_tenant_scoped(client, session):
    org_id, user_id = await _create_org_as_admin(client)
    await _seed_audit_event(
        session,
        org_id=org_id,
        actor_user_id=user_id,
        command="payroll_run.post",
        entity_type="payroll_run",
        entity_id=uuid4(),
        event_kind="mutation",
        entity_label="2026-07 Regular run",
        actor_snapshot={
            "id": str(user_id),
            "name": "Captured Actor",
            "email": "captured@example.com",
        },
        before_state={"status": "approved"},
        after_state={"status": "posted"},
        bind_user_id=user_id,
    )

    response = await client.get("/api/audit-events/filter-options")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entity_types"] == ["payroll_run"]
    assert body["commands"] == ["payroll_run.post"]
    assert body["actors"] == [
        {
            "id": str(user_id),
            "name": "Captured Actor",
            "email": "captured@example.com",
        }
    ]


@pytest.mark.asyncio
async def test_detail_cross_org_404(client, session):
    org_a, user_a = await _create_org_as_admin(client)
    org_b = await seed_organization(session, name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    user_b = await seed_user(session, email=f"b-{uuid4().hex[:8]}@example.com", name="Org B Admin")
    await seed_membership(
        session,
        organization_id=org_b.id,
        user_id=user_b.id,
        role="organization_administrator",
    )
    await session.commit()

    foreign = await _seed_audit_event(
        session,
        org_id=org_b.id,
        actor_user_id=user_b.id,
        command="post",
        entity_type="payroll_run",
        entity_id=uuid4(),
        bind_user_id=user_b.id,
    )
    # Stay authenticated as org A.
    _ = org_a, user_a
    resp = await client.get(f"/api/audit-events/{foreign.id}")
    assert resp.status_code == 404
