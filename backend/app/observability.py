"""Prometheus HTTP metrics and scrape-time platform gauges for Accord.

Deploy expectation: ``GET /metrics`` is for private scrapers only (sidecar,
internal network, or mesh). Do **not** expose it on the public internet.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select

from app.db import session_context
from app.models.platform import ExportArtifact, Job, OutboxEvent

# Dedicated registry avoids Counter/Gauge double-registration when tests recreate apps.
REGISTRY = CollectorRegistry(auto_describe=True)

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=("route",),
    registry=REGISTRY,
)

accord_jobs = Gauge(
    "accord_jobs",
    "Count of jobs by status",
    labelnames=("status",),
    registry=REGISTRY,
)

accord_outbox_pending = Gauge(
    "accord_outbox_pending",
    "Count of unprocessed outbox events",
    registry=REGISTRY,
)

accord_outbox_oldest_age_seconds = Gauge(
    "accord_outbox_oldest_age_seconds",
    "Age in seconds of the oldest unprocessed outbox event (0 when none)",
    registry=REGISTRY,
)

accord_artifacts = Gauge(
    "accord_artifacts",
    "Count of export artifacts by status",
    labelnames=("status",),
    registry=REGISTRY,
)

_JOB_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
)
_ARTIFACT_STATUSES = (
    "pending",
    "uploaded",
    "finalized",
    "expired",
    "deleted",
)


def matched_route_template(request: Request) -> str:
    """Return the matched route path template, or ``unmatched``.

    Uses Starlette's ``route.path`` (the parameterized template, e.g.
    ``/api/employees/{employee_id}``) directly so cardinality stays bounded
    (never raw IDs). Routers are mounted via ``include_router(prefix="/api")``,
    so ``route.path`` already carries the full prefixed template. Reading it
    directly avoids naive string replacement that could clobber static segments
    when a param value is a substring of a static path or another parameter.
    """
    route = request.scope.get("route")
    if route is None:
        return "unmatched"
    route_path = getattr(route, "path", None)
    if not route_path:
        return "unmatched"
    return route_path


async def refresh_platform_gauges() -> None:
    """Refresh scrape-time gauges with a short DB query.

    Cost: one session and a handful of aggregated ``COUNT`` / ``MIN`` queries
    over ``jobs``, ``outbox_events``, and ``export_artifacts``. Acceptable at
    Accord's current scale when scrapes are infrequent (e.g. 15–60s).
    """
    async with session_context() as session:
        for status in _JOB_STATUSES:
            accord_jobs.labels(status=status).set(0)
        job_rows = await session.execute(select(Job.status, func.count()).group_by(Job.status))
        for status, count in job_rows.all():
            accord_jobs.labels(status=str(status)).set(int(count))

        pending = await session.execute(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
        )
        pending_count = int(pending.scalar_one())
        accord_outbox_pending.set(pending_count)

        oldest = await session.execute(
            select(func.min(OutboxEvent.occurred_at)).where(OutboxEvent.processed_at.is_(None))
        )
        oldest_at = oldest.scalar_one()
        if oldest_at is None:
            accord_outbox_oldest_age_seconds.set(0)
        else:
            if oldest_at.tzinfo is None:
                oldest_at = oldest_at.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - oldest_at).total_seconds()
            accord_outbox_oldest_age_seconds.set(max(age, 0.0))

        for status in _ARTIFACT_STATUSES:
            accord_artifacts.labels(status=status).set(0)
        artifact_rows = await session.execute(
            select(ExportArtifact.status, func.count()).group_by(ExportArtifact.status)
        )
        for status, count in artifact_rows.all():
            accord_artifacts.labels(status=str(status)).set(int(count))


async def metrics_endpoint() -> Response:
    """Prometheus scrape handler (unauthenticated; keep off the public internet)."""
    await refresh_platform_gauges()
    payload = generate_latest(REGISTRY)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


async def prometheus_http_middleware(request: Request, call_next):
    """Record request count and latency using matched route templates."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = matched_route_template(request)
    method = request.method
    status = str(response.status_code)
    http_requests_total.labels(method=method, route=route, status=status).inc()
    http_request_duration_seconds.labels(route=route).observe(elapsed)
    return response


def setup_observability(app: FastAPI) -> None:
    """Mount metrics middleware and ``GET /metrics`` on the application."""
    app.middleware("http")(prometheus_http_middleware)
    app.add_api_route(
        "/metrics",
        metrics_endpoint,
        methods=["GET"],
        include_in_schema=False,
        name="metrics",
    )
