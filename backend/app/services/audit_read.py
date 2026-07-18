"""Read-side service for tenant-scoped audit events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.identity import User
from app.models.platform import AuditEvent
from app.schemas.audit import AuditActor, AuditEventListPage, AuditEventResponse
from app.schemas.pagination import page_count, page_offset


def _row_to_response(row: sa.RowMapping) -> AuditEventResponse:
    actor: AuditActor | None = None
    if row["actor_user_id"] is not None and row["actor_id"] is not None:
        actor = AuditActor(
            id=row["actor_id"],
            name=row["actor_name"],
            email=row["actor_email"],
        )
    return AuditEventResponse(
        id=row["id"],
        command=row["command"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        actor=actor,
        request_id=row["request_id"],
        summary=row["summary"],
        created_at=row["created_at"],
    )


def _base_select() -> sa.Select:
    return (
        sa.select(
            AuditEvent.id.label("id"),
            AuditEvent.command.label("command"),
            AuditEvent.entity_type.label("entity_type"),
            AuditEvent.entity_id.label("entity_id"),
            AuditEvent.actor_user_id.label("actor_user_id"),
            AuditEvent.request_id.label("request_id"),
            AuditEvent.summary.label("summary"),
            AuditEvent.created_at.label("created_at"),
            User.id.label("actor_id"),
            User.name.label("actor_name"),
            User.email.label("actor_email"),
        )
        .select_from(AuditEvent)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
    )


async def list_audit_events(
    db: AsyncSession,
    *,
    organization_id: UUID,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    command: str | None = None,
    actor_user_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AuditEventListPage:
    """List audit events for an org, newest-first, with optional filters."""
    offset = page_offset(page=page, page_size=page_size)

    base = _base_select().where(AuditEvent.organization_id == organization_id)
    if entity_type is not None:
        base = base.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        base = base.where(AuditEvent.entity_id == entity_id)
    if command is not None:
        base = base.where(AuditEvent.command == command)
    if actor_user_id is not None:
        base = base.where(AuditEvent.actor_user_id == actor_user_id)
    if from_time is not None:
        base = base.where(AuditEvent.created_at >= from_time)
    if to_time is not None:
        base = base.where(AuditEvent.created_at <= to_time)

    count_stmt = sa.select(sa.func.count()).select_from(base.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    page_stmt = (
        base.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(page_size)
        .offset(offset)
    )
    rows = (await db.execute(page_stmt)).mappings().all()
    items = [_row_to_response(row) for row in rows]
    return AuditEventListPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=page_count(total=total, page_size=page_size),
    )


async def get_audit_event(
    db: AsyncSession,
    *,
    organization_id: UUID,
    event_id: UUID,
) -> AuditEventResponse:
    """Return one audit event; other-tenant rows are invisible (404)."""
    stmt = (
        _base_select()
        .where(
            AuditEvent.organization_id == organization_id,
            AuditEvent.id == event_id,
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).mappings().first()
    if row is None:
        raise NotFoundError("Audit event not found.")
    return _row_to_response(row)
