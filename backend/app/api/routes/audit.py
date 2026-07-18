"""Audit-event read routes.

Register with: ``app.include_router(audit.router, prefix="/api")``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Session, TenantCtx, require_capability
from app.auth.principal import AuthPrincipal
from app.schemas.audit import COMMAND_NAME_PATTERN, AuditEventListPage, AuditEventResponse
from app.services import audit_read as audit_read_service

router = APIRouter(tags=["audit"])


def _org_id(tenant: TenantCtx) -> UUID:
    return UUID(tenant.organization_id)


def _to_utc_naive(value: datetime) -> datetime:
    """Normalize to UTC-naive so aware/naive bounds compare without TypeError.

    Accord stores clock timestamps as UTC-naive; aware inputs are converted to
    UTC (preserving their offset) and naive inputs are assumed already UTC.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _validate_time_bounds(from_time: datetime | None, to_time: datetime | None) -> None:
    if (
        from_time is not None
        and to_time is not None
        and _to_utc_naive(from_time) > _to_utc_naive(to_time)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="from must be on or before to.",
        )


@router.get("/audit-events", response_model=AuditEventListPage)
async def list_audit_events(
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_audit")),
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    command: str | None = Query(default=None, pattern=COMMAND_NAME_PATTERN),
    actor_user_id: UUID | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AuditEventListPage:
    _validate_time_bounds(from_time, to_time)
    return await audit_read_service.list_audit_events(
        db,
        organization_id=_org_id(tenant),
        entity_type=entity_type,
        entity_id=entity_id,
        command=command,
        actor_user_id=actor_user_id,
        from_time=from_time,
        to_time=to_time,
        page=page,
        page_size=page_size,
    )


@router.get("/audit-events/{event_id}", response_model=AuditEventResponse)
async def get_audit_event(
    event_id: UUID,
    tenant: TenantCtx,
    db: Session,
    _: AuthPrincipal = Depends(require_capability("view_audit")),
) -> AuditEventResponse:
    return await audit_read_service.get_audit_event(
        db,
        organization_id=_org_id(tenant),
        event_id=event_id,
    )
