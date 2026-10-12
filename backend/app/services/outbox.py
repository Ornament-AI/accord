"""Transactional outbox enqueue / claim / dispatch (ADR 0009).

Delivery is **at-least-once**: a dispatcher may crash after a successful sink
call but before ``mark_processed``. Consumers **MUST** dedupe by
``outbox_events.id``.

Failed deliveries clear the lock and retry until ``attempts`` exceeds
:data:`DEAD_LETTER_ATTEMPTS`, when the row is marked ``dead_lettered_at`` and
leaves the claimable set permanently — an operator must then inspect and, if
needed, re-drive the event manually. A WARNING is logged once ``attempts``
exceeds :data:`ATTEMPT_WARNING_THRESHOLD` so stuck sinks surface early.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import Any, TypedDict
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ValidationError
from app.models.base import utcnow
from app.models.platform import OutboxEvent

logger = structlog.get_logger()

# Warn early, dead-letter after sustained failure.
ATTEMPT_WARNING_THRESHOLD = 20
DEAD_LETTER_ATTEMPTS = 50

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

OutboxHandler = Callable[[OutboxEvent], Awaitable[None]]


class DispatchCounts(TypedDict):
    processed: int
    failed: int


def _validate_event_type(event_type: str) -> None:
    if not _EVENT_TYPE_RE.fullmatch(event_type):
        raise ValidationError(
            "event_type must be dotted lowercase segments (e.g. 'payroll.run.approved').",
            details={"event_type": event_type},
        )


async def emit_event(
    session: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """Insert an outbox row in the caller's open transaction (no commit)."""
    _validate_event_type(event_type)
    event = OutboxEvent(
        organization_id=organization_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    await session.flush()
    return event


async def claim_batch(
    session: AsyncSession,
    *,
    dispatcher_id: str,
    batch_size: int = 50,
    lock_seconds: int = 60,
) -> list[OutboxEvent]:
    """Claim up to ``batch_size`` unprocessed rows via ``FOR UPDATE SKIP LOCKED``.

    Returns claimed events ordered oldest-first by ``occurred_at``.
    """
    if batch_size < 1:
        raise ValidationError("batch_size must be >= 1.")
    if lock_seconds < 1:
        raise ValidationError("lock_seconds must be >= 1.")

    locked_until = utcnow() + timedelta(seconds=lock_seconds)
    claimable = (
        sa.select(OutboxEvent.id)
        .where(OutboxEvent.processed_at.is_(None))
        .where(OutboxEvent.dead_lettered_at.is_(None))
        .where(
            sa.or_(
                OutboxEvent.locked_until.is_(None),
                OutboxEvent.locked_until < sa.func.now(),
            )
        )
        .order_by(OutboxEvent.occurred_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    stmt = (
        sa.update(OutboxEvent)
        .where(OutboxEvent.id.in_(claimable))
        .values(locked_by=dispatcher_id, locked_until=locked_until)
        .returning(OutboxEvent)
    )
    result = await session.execute(stmt)
    events = list(result.scalars().all())
    events.sort(key=lambda e: (e.occurred_at, str(e.id)))
    return events


async def mark_processed(
    session: AsyncSession,
    *,
    event_ids: Sequence[UUID],
    dispatcher_id: str,
) -> int:
    """Set ``processed_at`` for rows still owned by ``dispatcher_id``.

    Returns the number of rows updated (wrong ``dispatcher_id`` is a no-op).
    """
    if not event_ids:
        return 0
    stmt = (
        sa.update(OutboxEvent)
        .where(OutboxEvent.id.in_(list(event_ids)))
        .where(OutboxEvent.locked_by == dispatcher_id)
        .where(OutboxEvent.processed_at.is_(None))
        .values(
            processed_at=sa.func.now(),
            locked_by=None,
            locked_until=None,
        )
    )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def release_or_retry(
    session: AsyncSession,
    *,
    event_id: UUID,
    dispatcher_id: str,
    error: str | None = None,
) -> None:
    """Increment ``attempts`` and clear the lock so the row can be retried.

    Once ``attempts`` exceeds :data:`DEAD_LETTER_ATTEMPTS` the row is marked
    ``dead_lettered_at`` and is never claimed again — operators must triage it
    out of band. Consumers must dedupe by event id (at-least-once delivery).
    """
    stmt = (
        sa.update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .where(OutboxEvent.locked_by == dispatcher_id)
        .where(OutboxEvent.processed_at.is_(None))
        .values(
            attempts=OutboxEvent.attempts + 1,
            locked_by=None,
            locked_until=None,
            last_error=None if error is None else error[:2000],
            dead_lettered_at=sa.case(
                (OutboxEvent.attempts + 1 > DEAD_LETTER_ATTEMPTS, sa.func.now()),
                else_=None,
            ),
        )
        .returning(OutboxEvent.attempts)
    )
    result = await session.execute(stmt)
    attempts = result.scalar_one_or_none()
    if attempts is None:
        return
    if attempts > DEAD_LETTER_ATTEMPTS:
        logger.error(
            "outbox_event_dead_lettered",
            event_id=str(event_id),
            dispatcher_id=dispatcher_id,
            attempts=attempts,
        )
    elif attempts > ATTEMPT_WARNING_THRESHOLD:
        logger.warning(
            "outbox_event_high_attempts",
            event_id=str(event_id),
            dispatcher_id=dispatcher_id,
            attempts=attempts,
            threshold=ATTEMPT_WARNING_THRESHOLD,
        )


async def dispatch_pending(
    session: AsyncSession,
    *,
    dispatcher_id: str,
    handler: OutboxHandler,
    batch_size: int = 50,
) -> DispatchCounts:
    """Claim a batch and invoke ``handler`` per event.

    Successful handler calls are ``mark_processed``; exceptions trigger
    ``release_or_retry``. The delivery sink is injected — integrations wire
    the concrete handler later.
    """
    events = await claim_batch(
        session,
        dispatcher_id=dispatcher_id,
        batch_size=batch_size,
    )
    processed = 0
    failed = 0
    for event in events:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "outbox_handler_failed",
                event_id=str(event.id),
                event_type=event.event_type,
                dispatcher_id=dispatcher_id,
            )
            await release_or_retry(
                session,
                event_id=event.id,
                dispatcher_id=dispatcher_id,
                error=traceback.format_exc(),
            )
            failed += 1
            continue
        await mark_processed(
            session,
            event_ids=[event.id],
            dispatcher_id=dispatcher_id,
        )
        processed += 1
    return DispatchCounts(processed=processed, failed=failed)
