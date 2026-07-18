"""API tests for export artifact routes (ADR 0010)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.artifacts import router as artifacts_router
from app.auth.capabilities import ROLE_CAPABILITIES
from app.main import create_app
from app.models.platform import ExportArtifact
from app.services.artifacts import create_artifact
from app.storage.memory import InMemoryObjectStorage
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import seed_membership, seed_organization, seed_user


def _artifacts_app(storage: InMemoryObjectStorage):
    application = create_app()
    application.include_router(artifacts_router, prefix="/api")
    application.state.auth_ready = True
    application.state.object_storage = storage
    return application


@pytest_asyncio.fixture
async def storage():
    return InMemoryObjectStorage()


@pytest_asyncio.fixture
async def client(dev_settings, storage):
    application = _artifacts_app(storage)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_world(session, dev_settings, client, *, slug: str | None = None):
    org = await seed_organization(
        session,
        name="Artifact API Org",
        slug=slug or f"art-api-{uuid4().hex[:10]}",
    )
    admin = await seed_user(session, name="Org Admin")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=admin.id,
        role="organization_administrator",
    )
    await session.commit()
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=admin.id,
        active_organization_id=org.id,
    )
    apply_session_cookie(client, cookie)
    return org, admin


async def _bind(session, org_id, user_id) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


@pytest.mark.asyncio
async def test_download_returns_bytes_content_type_disposition(
    client, session, dev_settings, storage
):
    org, admin = await _admin_world(session, dev_settings, client)
    await _bind(session, org.id, admin.id)
    content = b"api-download-exact-bytes"
    artifact = await create_artifact(
        session,
        storage,
        organization_id=org.id,
        report_type="bank_file",
        template_version="v1",
        content=content,
        content_type="text/csv",
        requested_by=admin.id,
    )

    resp = await client.get(f"/api/artifacts/{artifact.id}/download")
    assert resp.status_code == 200, resp.text
    assert resp.content == content
    assert resp.headers["content-type"].startswith("text/csv")
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "bank_file-v1" in disposition
    assert disposition.endswith('.csv"') or '.csv"' in disposition


@pytest.mark.asyncio
async def test_download_404_other_org(client, session, dev_settings, storage):
    org_a, admin_a = await _admin_world(
        session, dev_settings, client, slug=f"art-a-{uuid4().hex[:8]}"
    )
    await _bind(session, org_a.id, admin_a.id)
    artifact = await create_artifact(
        session,
        storage,
        organization_id=org_a.id,
        report_type="bank_file",
        template_version="v1",
        content=b"secret-a",
        content_type="text/csv",
        requested_by=admin_a.id,
    )

    org_b, admin_b = await _admin_world(
        session, dev_settings, client, slug=f"art-b-{uuid4().hex[:8]}"
    )
    assert org_b.id != org_a.id
    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=admin_b.id,
            active_organization_id=org_b.id,
        ),
    )

    resp = await client.get(f"/api/artifacts/{artifact.id}/download")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_409_non_finalized(client, session, dev_settings, storage):
    org, admin = await _admin_world(session, dev_settings, client)
    await _bind(session, org.id, admin.id)
    pending = ExportArtifact(
        organization_id=org.id,
        report_type="bank_file",
        template_version="v1",
        object_key=f"{org.id}/{uuid4()}",
        checksum_sha256="a" * 64,
        content_type="text/csv",
        size_bytes=0,
        status="pending",
        requested_by=admin.id,
    )
    session.add(pending)
    await session.commit()

    resp = await client.get(f"/api/artifacts/{pending.id}/download")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_download_410_expired(client, session, dev_settings, storage):
    org, admin = await _admin_world(session, dev_settings, client)
    await _bind(session, org.id, admin.id)
    artifact = await create_artifact(
        session,
        storage,
        organization_id=org.id,
        report_type="bank_file",
        template_version="v1",
        content=b"expired-bytes",
        content_type="text/csv",
        requested_by=admin.id,
        retention_days=1,
    )
    artifact_id = artifact.id
    await _bind(session, org.id, admin.id)
    row = await session.get(ExportArtifact, artifact_id)
    assert row is not None
    row.status = "expired"
    row.retention_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()

    resp = await client.get(f"/api/artifacts/{artifact_id}/download")
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_capability_gates_enforced(client, session, dev_settings, storage, monkeypatch):
    resp = await client.get("/api/artifacts")
    assert resp.status_code == 401

    org, admin = await _admin_world(session, dev_settings, client)
    await _bind(session, org.id, admin.id)
    artifact = await create_artifact(
        session,
        storage,
        organization_id=org.id,
        report_type="bank_file",
        template_version="v1",
        content=b"gated",
        content_type="text/csv",
        requested_by=admin.id,
    )

    # Strip generate_reports so require_capability rejects the admin role.
    monkeypatch.setitem(
        ROLE_CAPABILITIES,
        "organization_administrator",
        ROLE_CAPABILITIES["organization_administrator"] - frozenset({"generate_reports"}),
    )
    # Re-mint session so principal is resolved with patched capabilities.
    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=admin.id,
            active_organization_id=org.id,
        ),
    )
    for path in (
        "/api/artifacts",
        f"/api/artifacts/{artifact.id}",
        f"/api/artifacts/{artifact.id}/download",
    ):
        denied = await client.get(path)
        assert denied.status_code == 403, path


@pytest.mark.asyncio
async def test_list_endpoint_and_filters(client, session, dev_settings, storage):
    org, admin = await _admin_world(session, dev_settings, client)
    await _bind(session, org.id, admin.id)
    await create_artifact(
        session,
        storage,
        organization_id=org.id,
        report_type="bank_file",
        template_version="v1",
        content=b"list-1",
        content_type="text/csv",
        requested_by=admin.id,
    )
    await create_artifact(
        session,
        storage,
        organization_id=org.id,
        report_type="payslip",
        template_version="v1",
        content=b"list-2",
        content_type="application/pdf",
        requested_by=admin.id,
    )

    all_resp = await client.get("/api/artifacts")
    assert all_resp.status_code == 200, all_resp.text
    body = all_resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    filtered = await client.get("/api/artifacts", params={"report_type": "bank_file"})
    assert filtered.status_code == 200
    fbody = filtered.json()
    assert fbody["total"] == 1
    assert fbody["items"][0]["report_type"] == "bank_file"

    status_filtered = await client.get("/api/artifacts", params={"status": "finalized"})
    assert status_filtered.status_code == 200
    assert status_filtered.json()["total"] == 2

    meta = await client.get(f"/api/artifacts/{UUID(fbody['items'][0]['id'])}")
    assert meta.status_code == 200
    assert meta.json()["checksum_sha256"]
    assert "object_key" not in meta.json()
