"""Health and readiness endpoints."""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from app.db import session_context

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness_check(request: Request) -> dict[str, str]:
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

    return {"status": "ok", "database": "ok", "auth": "ok"}
