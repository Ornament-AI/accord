"""WorkOS webhook verification, in-memory dedup, and minimal event handling."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from workos.webhooks._verification import verify_header

from app.config import Settings
from app.models.base import utcnow
from app.models.identity import User

logger = structlog.get_logger()

# TODO(Phase 3): durable workos_webhook_events table for cross-restart dedup.
_SEEN_EVENTS: dict[str, float] = {}
_DEDUP_TTL_SECONDS = 24 * 60 * 60
_DEDUP_MAX_ENTRIES = 10_000


def _prune_seen(*, now: float) -> None:
    stale_before = now - _DEDUP_TTL_SECONDS
    stale_ids = [eid for eid, seen_at in _SEEN_EVENTS.items() if seen_at < stale_before]
    for eid in stale_ids:
        del _SEEN_EVENTS[eid]
    if len(_SEEN_EVENTS) > _DEDUP_MAX_ENTRIES:
        # Drop oldest entries when the process-local cache grows too large.
        ordered = sorted(_SEEN_EVENTS.items(), key=lambda item: item[1])
        for eid, _ in ordered[: len(_SEEN_EVENTS) - _DEDUP_MAX_ENTRIES]:
            del _SEEN_EVENTS[eid]


def clear_webhook_dedup_cache() -> None:
    """Test helper: reset the in-memory replay cache."""
    _SEEN_EVENTS.clear()


def is_duplicate_event(event_id: str) -> bool:
    now = time.time()
    _prune_seen(now=now)
    return event_id in _SEEN_EVENTS


def mark_event_seen(event_id: str) -> None:
    now = time.time()
    _prune_seen(now=now)
    _SEEN_EVENTS[event_id] = now


def verify_workos_webhook(
    *,
    body: bytes,
    signature: str,
    settings: Settings,
) -> dict[str, Any]:
    """Verify signature + timestamp; return parsed JSON event dict.

    Uses ``verify_header`` (not ``verify_event``) so we accept the WorkOS
    signature scheme without requiring strict SDK model deserialization of
    every event payload variant.
    """
    verify_header(
        event_body=body,
        event_signature=signature,
        secret=settings.workos_webhook_secret,
        tolerance=settings.workos_webhook_tolerance_seconds,
    )
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Webhook body must be a JSON object")
    return payload


def _event_field(event: dict[str, Any], name: str) -> Any:
    return event.get(name)


async def handle_workos_event(db: AsyncSession, event: dict[str, Any]) -> bool:
    """Apply a verified WorkOS event. Returns False if this was a replay no-op."""
    event_id = _event_field(event, "id")
    event_type = _event_field(event, "event") or _event_field(event, "type")
    if not event_id:
        logger.warning("workos_webhook_missing_event_id", event_type=event_type)
        return True

    event_id_str = str(event_id)
    if is_duplicate_event(event_id_str):
        logger.warning(
            "workos_webhook_replay_ignored",
            event_id=event_id_str,
            event_type=event_type,
        )
        return False

    if event_type == "user.updated":
        data = _event_field(event, "data") or {}
        if not isinstance(data, dict):
            data = {}
        workos_user_id = data.get("id")
        if workos_user_id:
            result = await db.execute(
                select(User).where(User.workos_user_id == str(workos_user_id))
            )
            user = result.scalar_one_or_none()
            if user is not None:
                email = (data.get("email") or "").strip()
                if email:
                    user.email = email
                name = data.get("name")
                if not name:
                    parts = [p for p in (data.get("first_name"), data.get("last_name")) if p]
                    name = " ".join(parts) if parts else None
                if name:
                    user.name = str(name)
                user.updated_at = utcnow()
                await db.commit()
                logger.info(
                    "workos_webhook_user_updated",
                    workos_user_id=str(workos_user_id),
                    user_id=str(user.id),
                )
            else:
                logger.info(
                    "workos_webhook_user_updated_unknown",
                    workos_user_id=str(workos_user_id),
                )
        # Mark after durable apply so a failed commit can still be retried.
        mark_event_seen(event_id_str)
        return True

    mark_event_seen(event_id_str)
    logger.info("workos_webhook_acked", event_id=event_id_str, event_type=event_type)
    return True
