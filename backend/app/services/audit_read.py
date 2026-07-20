"""Read-side service for tenant-scoped audit history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.identity import User
from app.models.platform import AuditEvent
from app.schemas.audit import (
    AuditActor,
    AuditEventDetailResponse,
    AuditEventListItem,
    AuditEventListPage,
    AuditFilterOptionsResponse,
)
from app.schemas.pagination import page_count, page_offset


def _actor(row: sa.RowMapping) -> AuditActor | None:
    snapshot = row.get("actor_snapshot")
    if snapshot and snapshot.get("id"):
        return AuditActor.model_validate(snapshot)
    if row.get("actor_user_id") is not None and row.get("actor_id") is not None:
        return AuditActor(
            id=row["actor_id"],
            name=row["actor_name"],
            email=row["actor_email"],
        )
    return None


def _fallback_label(entity_type: str, entity_id: UUID) -> str:
    return f"{entity_type.replace('_', ' ').title()} {str(entity_id)[:8]}"


def _list_item(row: sa.RowMapping) -> AuditEventListItem:
    return AuditEventListItem(
        id=row["id"],
        command=row["command"],
        event_kind=row["event_kind"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        entity_label=row["entity_label"] or _fallback_label(row["entity_type"], row["entity_id"]),
        actor=_actor(row),
        changed_count=row["changed_count"] or 0,
        created_at=row["created_at"],
    )


def _base_select(*, include_detail: bool = False) -> sa.Select:
    columns: list[Any] = [
        AuditEvent.id.label("id"),
        AuditEvent.command.label("command"),
        AuditEvent.event_kind.label("event_kind"),
        AuditEvent.entity_type.label("entity_type"),
        AuditEvent.entity_id.label("entity_id"),
        AuditEvent.entity_label.label("entity_label"),
        AuditEvent.actor_user_id.label("actor_user_id"),
        AuditEvent.actor_snapshot.label("actor_snapshot"),
        AuditEvent.changed_count.label("changed_count"),
        AuditEvent.created_at.label("created_at"),
        User.id.label("actor_id"),
        User.name.label("actor_name"),
        User.email.label("actor_email"),
    ]
    if include_detail:
        columns.extend(
            [
                AuditEvent.request_id.label("request_id"),
                AuditEvent.before_state.label("before_state"),
                AuditEvent.after_state.label("after_state"),
                AuditEvent.metadata_.label("metadata"),
            ]
        )
    return (
        sa.select(*columns)
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

    total = int(
        (await db.execute(sa.select(sa.func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        (
            await db.execute(
                base.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        )
        .mappings()
        .all()
    )
    return AuditEventListPage(
        items=[_list_item(row) for row in rows],
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
) -> AuditEventDetailResponse:
    row = (
        (
            await db.execute(
                _base_select(include_detail=True)
                .where(AuditEvent.organization_id == organization_id, AuditEvent.id == event_id)
                .limit(1)
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFoundError("Audit event not found.")
    item = _list_item(row)
    metadata = dict(row["metadata"] or {})
    resource = metadata.pop("resource", None)
    return AuditEventDetailResponse(
        **item.model_dump(),
        request_id=row["request_id"],
        before_state=row["before_state"],
        after_state=row["after_state"],
        resource_state=resource,
        access_details=metadata,
    )


async def get_filter_options(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> AuditFilterOptionsResponse:
    entity_types = list(
        (
            await db.scalars(
                sa.select(AuditEvent.entity_type)
                .where(AuditEvent.organization_id == organization_id)
                .distinct()
                .order_by(AuditEvent.entity_type)
            )
        ).all()
    )
    commands = list(
        (
            await db.scalars(
                sa.select(AuditEvent.command)
                .where(AuditEvent.organization_id == organization_id)
                .distinct()
                .order_by(AuditEvent.command)
            )
        ).all()
    )
    # DISTINCT ON keeps one latest row per actor without materializing full history.
    actor_rows = (
        (
            await db.execute(
                sa.select(
                    AuditEvent.actor_user_id.label("actor_user_id"),
                    AuditEvent.actor_snapshot.label("actor_snapshot"),
                    User.id.label("actor_id"),
                    User.name.label("actor_name"),
                    User.email.label("actor_email"),
                )
                .select_from(AuditEvent)
                .outerjoin(User, User.id == AuditEvent.actor_user_id)
                .where(
                    AuditEvent.organization_id == organization_id,
                    AuditEvent.actor_user_id.is_not(None),
                )
                .distinct(AuditEvent.actor_user_id)
                .order_by(
                    AuditEvent.actor_user_id,
                    AuditEvent.created_at.desc(),
                    AuditEvent.id.desc(),
                )
            )
        )
        .mappings()
        .all()
    )
    actors_by_id: dict[UUID, AuditActor] = {}
    for row in actor_rows:
        actor = _actor(row)
        if actor is not None:
            actors_by_id.setdefault(actor.id, actor)
    actors = sorted(actors_by_id.values(), key=lambda actor: (actor.name.casefold(), actor.email))
    return AuditFilterOptionsResponse(
        entity_types=entity_types,
        commands=commands,
        actors=actors,
    )
