"""Prometheus /metrics and extended readiness checks."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest

from app.main import app
from app.models.identity import Organization
from app.models.platform import Job
from app.observability import (
    accord_jobs,
    accord_outbox_oldest_age_seconds,
    accord_outbox_pending,
    refresh_platform_gauges,
)
from app.reports.base import ReportRegistry


@pytest.mark.asyncio
async def test_metrics_http_labels_use_route_templates(client):
    # Drive a static route through the middleware so counters/histograms update.
    health = await client.get("/api/healthz")
    assert health.status_code == 200

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text

    assert "http_requests_total" in body
    assert 'method="GET"' in body
    assert 'route="/api/healthz"' in body
    assert 'status="200"' in body

    assert "http_request_duration_seconds" in body
    assert 'route="/api/healthz"' in body

    # Parameterized path must never appear as a raw UUID in the route label.
    employee_id = uuid4()
    await client.get(f"/api/employees/{employee_id}")
    metrics = (await client.get("/metrics")).text
    assert not re.search(rf'route="[^"]*{employee_id}[^"]*"', metrics)
    assert (
        re.search(r'route="[^"]*\{[^}]+\}[^"]*"', metrics) is not None
        or 'route="unmatched"' in metrics
    )

    assert "accord_jobs" in metrics
    assert "accord_outbox_pending" in metrics
    assert "accord_outbox_oldest_age_seconds" in metrics
    assert "accord_artifacts" in metrics


@pytest.mark.asyncio
async def test_readyz_all_ok_with_configured_storage(client, monkeypatch):
    class _OkStorage:
        async def ensure_bucket(self) -> None:
            return None

    monkeypatch.setattr(app.state, "object_storage", _OkStorage(), raising=False)
    resp = await client.get("/api/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "status": "ok",
        "database": "ok",
        "auth": "ok",
        "jobs": "ok",
        "storage": "ok",
        "reports": "ok",
    }


@pytest.mark.asyncio
async def test_readyz_storage_unconfigured_is_ok(client, monkeypatch):
    monkeypatch.delattr(app.state, "object_storage", raising=False)
    resp = await client.get("/api/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["storage"] == "unconfigured"
    assert data["database"] == "ok"
    assert data["jobs"] == "ok"
    assert data["reports"] == "ok"


@pytest.mark.asyncio
async def test_readyz_empty_report_registry_is_degraded(client, monkeypatch):
    monkeypatch.setattr(app.state, "report_registry", ReportRegistry())
    resp = await client.get("/api/readyz")
    assert resp.status_code == 503
    body: dict[str, Any] = resp.json()
    assert body["status"] == "degraded"
    assert body["reports"] == "empty"
    assert body["database"] == "ok"
    assert body["auth"] == "ok"


@pytest.mark.asyncio
async def test_platform_gauges_reflect_seeded_jobs(session, clean_identity_tables):
    """Scrape-time gauges must see tenant rows (they are forced-RLS protected)."""
    org = Organization(id=uuid4(), name="Metrics Org", slug=f"metrics-{uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    session.add(
        Job(
            organization_id=org.id,
            job_type="export.generate",
            status="queued",
            payload={},
        )
    )
    await session.commit()

    await refresh_platform_gauges()

    assert accord_jobs.labels(status="queued")._value.get() == 1


@pytest.mark.asyncio
async def test_platform_gauges_zero_on_fresh_install(session, clean_identity_tables):
    """No organization (pre-bootstrap): gauges report honest zeros, no error."""
    await refresh_platform_gauges()

    assert accord_jobs.labels(status="queued")._value.get() == 0
    assert accord_outbox_pending._value.get() == 0
    assert accord_outbox_oldest_age_seconds._value.get() == 0
