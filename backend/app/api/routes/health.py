"""Health and readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import session_context

router = APIRouter(tags=["health"])

_PROBE_OBJECT_KEY = "00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002"


def _report_type_count(registry: Any) -> int:
    """Return registered report type count (supports ``report_types()`` or ``_entries``)."""
    report_types = getattr(registry, "report_types", None)
    if callable(report_types):
        return len(report_types())
    entries = getattr(registry, "_entries", None)
    if isinstance(entries, dict):
        return len(entries)
    return 0


async def _probe_object_storage(storage: Any) -> None:
    """Bucket-exists / liveness probe for a configured object storage backend."""
    ensure_bucket = getattr(storage, "ensure_bucket", None)
    if callable(ensure_bucket):
        await ensure_bucket()
        return
    exists = getattr(storage, "exists", None)
    if callable(exists):
        await exists(_PROBE_OBJECT_KEY)
        return
    raise RuntimeError("object storage has no health probe")


@router.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
async def readiness_check(request: Request) -> dict[str, str] | JSONResponse:
    # Database remains a hard-fail with the stable Problem Detail message.
    try:
        async with session_context() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is not ready.",
        ) from None

    if not getattr(request.app.state, "auth_ready", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth provider is not ready.",
        ) from None

    components: dict[str, str] = {
        "database": "ok",
        "auth": "ok",
    }

    try:
        async with session_context() as session:
            await session.execute(text("SELECT 1 FROM jobs LIMIT 1"))
        components["jobs"] = "ok"
    except Exception:
        components["jobs"] = "unavailable"

    storage = getattr(request.app.state, "object_storage", None)
    if storage is None:
        components["storage"] = "unconfigured"
    else:
        try:
            await _probe_object_storage(storage)
            components["storage"] = "ok"
        except Exception:
            components["storage"] = "unavailable"

    registry = getattr(request.app.state, "report_registry", None)
    if registry is None:
        components["reports"] = "missing"
    elif _report_type_count(registry) == 0:
        components["reports"] = "empty"
    else:
        components["reports"] = "ok"

    # Unconfigured storage is OK; any other non-ok component is degraded.
    # Return JSONResponse directly so component detail is not stringified by
    # the HTTPException → Problem Detail handler.
    if any(value not in ("ok", "unconfigured") for value in components.values()):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", **components},
        )

    return {"status": "ok", **components}
