"""Prometheus HTTP metrics and scrape-time platform gauges for Accord.

Deploy expectation: ``GET /metrics`` is for private scrapers only (sidecar,
internal network, or mesh). Do **not** expose it on the public internet.
"""

from __future__ import annotations

import logging
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
from app.exceptions import ConflictError
from app.models.platform import ExportArtifact, Job, OutboxEvent
from app.services.bootstrap import get_singleton_organization
from app.tenancy import bind_tenant_context

logger = logging.getLogger(__name__)

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
    """Return the matched route path template (mount prefix included), or ``unmatched``.

    Starlette stores the innermost matched route in ``scope["route"]``. For
    routers included via ``include_router(prefix="/api")`` that route's ``path``
    is the *unprefixed* template (e.g. ``/healthz`` or
    ``/employees/{employee_id}``), while ``request.url.path`` carries the full
    concrete path (e.g. ``/api/healthz``). We recombine them by segment count so
    the label keeps the mount prefix while still using the parameterized
    template (never raw IDs), and without the substring replacement that could
    clobber static segments when a param value collides with a static path.
    """
    route = request.scope.get("route")
    if route is None:
        return "unmatched"
    route_path = getattr(route, "path", None)
    if not route_path:
        return "unmatched"

    full_path = request.url.path
    route_segments = [s for s in route_path.split("/") if s]
    full_segments = [s for s in full_path.split("/") if s]
    prefix_count = len(full_segments) - len(route_segments)
    if prefix_count <= 0:
        return route_path
    prefix = "/" + "/".join(full_segments[:prefix_count])
    return prefix + route_path


def _zero_platform_gauges() -> None:
    for status in _JOB_STATUSES:
        accord_jobs.labels(status=status).set(0)
    for status in _ARTIFACT_STATUSES:
        accord_artifacts.labels(status=status).set(0)
    accord_outbox_pending.set(0)
    accord_outbox_oldest_age_seconds.set(0)


async def refresh_platform_gauges() -> None:
    """Refresh scrape-time gauges with a short DB query.

    Cost: one session and a handful of aggregated ``COUNT`` / ``MIN`` queries
    over ``jobs``, ``outbox_events``, and ``export_artifacts``. Acceptable at
    Accord's current scale when scrapes are infrequent (e.g. 15–60s).

    All three tables are forced-RLS protected, so the aggregate queries must
    run with the singleton organization's tenant context bound — without it,
    every row is invisible and the gauges silently report zero.
    """
    async with session_context() as session:
        try:
            org = await get_singleton_organization(session)
        except ConflictError:
            # Matches the codebase's singleton-org invariant everywhere else;
            # keep /metrics from 500ing and surface the violation in logs.
            logger.error("platform_gauges_skipped_multi_org")
            return
        if org is None:
            # Fresh install before organization bootstrap: report honest zeros.
            _zero_platform_gauges()
            return

        # get_singleton_organization already autobegan this transaction, so the
        # transaction-local GUC below lives until the session closes.
        await bind_tenant_context(session, organization_id=org.id)

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
    method = request.method
    try:
        response = await call_next(request)
    except Exception:
        # Unhandled errors are turned into responses by ServerErrorMiddleware,
        # which wraps all user middleware — record the 500 here so the metric
        # is not silently dropped. scope["route"] is set by the router before
        # the endpoint raised, so the template still resolves here.
        elapsed = time.perf_counter() - start
        route = matched_route_template(request)
        http_requests_total.labels(method=method, route=route, status="500").inc()
        http_request_duration_seconds.labels(route=route).observe(elapsed)
        raise
    elapsed = time.perf_counter() - start
    route = matched_route_template(request)
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
