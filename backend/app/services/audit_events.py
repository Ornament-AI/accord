"""Single transactional writer for immutable audit history events."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.platform import AuditEvent

VISIBLE_DIFF_IGNORES = frozenset(
    {"organization_id", "created_at", "updated_at", "lock_version", "version"}
)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def entity_snapshot(entity: Any) -> dict[str, Any]:
    mapper = inspect(type(entity))
    return {
        attribute.key: json_safe(getattr(entity, attribute.key))
        for attribute in mapper.column_attrs
    }


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in before.keys() | after.keys()
        if key not in VISIBLE_DIFF_IGNORES and before.get(key) != after.get(key)
    )


async def _actor_snapshot(db: AsyncSession, actor_user_id: UUID | None) -> dict[str, Any] | None:
    if actor_user_id is None:
        return None
    actor = await db.get(User, actor_user_id)
    if actor is None:
        return {"id": str(actor_user_id), "name": "Unknown user", "email": ""}
    return {"id": str(actor.id), "name": actor.name, "email": actor.email}


async def _request_id(db: AsyncSession) -> str | None:
    value = await db.scalar(sa.select(sa.func.current_setting("app.request_id", True)))
    return None if value is None or not str(value).strip() else str(value)


async def write_mutation_event(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None,
    command: str,
    entity_type: str,
    entity_id: UUID,
    entity_label: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> AuditEvent:
    before = json_safe(before_state)
    after = json_safe(after_state)
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        request_id=await _request_id(db),
        command=command,
        entity_type=entity_type,
        entity_id=entity_id,
        event_kind="mutation",
        actor_snapshot=await _actor_snapshot(db, actor_user_id),
        entity_label=entity_label,
        before_state=before,
        after_state=after,
        metadata_=json_safe(metadata or {}),
        idempotency_key=idempotency_key,
        changed_count=len(changed_fields(before, after)),
        summary=json_safe(summary or {}),
    )
    db.add(event)
    return event


async def write_access_event(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None,
    command: str,
    entity_type: str,
    entity_id: UUID,
    entity_label: str,
    resource_state: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> AuditEvent:
    event_metadata = json_safe(metadata or {})
    event_metadata["resource"] = json_safe(resource_state)
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        request_id=await _request_id(db),
        command=command,
        entity_type=entity_type,
        entity_id=entity_id,
        event_kind="access",
        actor_snapshot=await _actor_snapshot(db, actor_user_id),
        entity_label=entity_label,
        before_state=None,
        after_state=None,
        metadata_=event_metadata,
        changed_count=0,
        summary=json_safe(summary or {}),
    )
    db.add(event)
    return event
