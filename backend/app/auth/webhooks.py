"""WorkOS webhook verification and durable DB-backed event dedup.

Dedup semantics (single transaction):
- After signature verification (done in the route), claim the event by INSERT
  into ``webhook_events`` with ``ON CONFLICT (event_id) DO NOTHING``.
- Conflict (0 rows inserted) means the event id was already claimed: treat as
  replay, log ``workos_webhook_replay_ignored``, and return False without
  re-applying. The route still returns plain 200.
- On insert win: apply handlers, set ``processed_at``, and commit once.
  If handling raises before that commit, the transaction rolls back — including
  the dedup row — so WorkOS redelivery can retry. ``processed_at`` is only set
  when handling succeeds in the same commit (a failed attempt never leaves a
  durable claim).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from workos.webhooks._verification import verify_header

from app.config import Settings
from app.models.base import utcnow
from app.models.identity import User
from app.models.platform import WebhookEvent

logger = structlog.get_logger()


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


async def handle_workos_event(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    raw_body: bytes,
) -> bool:
    """Apply a verified WorkOS event. Returns False if this was a replay no-op.

    Dedup insert + handler + ``processed_at`` share one transaction: failure
    rolls back the claim so redelivery can retry; success commits with
    ``processed_at`` set.
    """
    event_id = event.get("id")
    event_type = event.get("event") or event.get("type")
    if not event_id:
        logger.warning("workos_webhook_missing_event_id", event_type=event_type)
        return True

    event_id_str = str(event_id)
    event_type_str = str(event_type) if event_type else "unknown"
    payload_digest = hashlib.sha256(raw_body).hexdigest()

    table = WebhookEvent.__table__
    claim = (
        pg_insert(table)
        .values(
            provider="workos",
            event_id=event_id_str,
            event_type=event_type_str,
            payload_digest=payload_digest,
        )
        .on_conflict_do_nothing(constraint="uq_webhook_events_event_id")
        .returning(table.c.id)
    )
    claim_result = await db.execute(claim)
    claimed = claim_result.first()
    if claimed is None:
        logger.warning(
            "workos_webhook_replay_ignored",
            event_id=event_id_str,
            event_type=event_type_str,
        )
        return False

    webhook_row_id = claimed.id

    if event_type == "user.updated":
        data = event.get("data") or {}
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
    else:
        logger.info("workos_webhook_acked", event_id=event_id_str, event_type=event_type)

    await db.execute(
        update(table).where(table.c.id == webhook_row_id).values(processed_at=utcnow())
    )
    await db.commit()
    return True
