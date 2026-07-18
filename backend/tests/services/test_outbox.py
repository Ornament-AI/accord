"""Integration tests for the transactional outbox service (ADR 0009)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.db import get_session_factory
from app.exceptions import ValidationError
from app.models.base import utcnow
from app.models.identity import OrganizationSettings
from app.models.platform import OutboxEvent
from app.services import outbox
from tests.identity_helpers import seed_organization


async def _emit(
    session,
    org_id: UUID,
    event_type: str = "payroll.run.approved",
    payload: dict | None = None,
) -> OutboxEvent:
    return await outbox.emit_event(
        session,
        organization_id=org_id,
        event_type=event_type,
        payload=payload if payload is not None else {"ok": True},
    )


async def _set_occurred_at(session, event_id: UUID, when) -> None:
    await session.execute(
        update(OutboxEvent).where(OutboxEvent.id == event_id).values(occurred_at=when)
    )
    await session.flush()


@pytest.mark.asyncio
async def test_emit_event_type_validation(session):
    org = await seed_organization(session, slug="outbox-validate")
    await session.commit()

    with pytest.raises(ValidationError, match="dotted lowercase"):
        await outbox.emit_event(
            session,
            organization_id=org.id,
            event_type="Payroll.Run.Approved",
            payload={},
        )
    with pytest.raises(ValidationError, match="dotted lowercase"):
        await outbox.emit_event(
            session,
            organization_id=org.id,
            event_type="nodot",
            payload={},
        )


@pytest.mark.asyncio
async def test_emit_atomic_with_other_writes_commit_and_rollback(session):
    org = await seed_organization(session, slug="outbox-atomic", with_settings=False)
    await session.commit()
    org_id = org.id

    # Commit path: outbox + settings land together.
    settings = OrganizationSettings(organization_id=org_id, timezone="Asia/Kolkata")
    session.add(settings)
    event = await _emit(session, org_id, payload={"path": "commit"})
    await session.commit()

    factory = get_session_factory()
    async with factory() as other:
        loaded = (
            await other.execute(select(OutboxEvent).where(OutboxEvent.id == event.id))
        ).scalar_one()
        assert loaded.payload == {"path": "commit"}
        settings_row = (
            await other.execute(
                select(OrganizationSettings).where(OrganizationSettings.organization_id == org_id)
            )
        ).scalar_one()
        assert settings_row.timezone == "Asia/Kolkata"

    # Rollback path: both writes disappear.
    async with factory() as db:
        existing = (
            await db.execute(
                select(OrganizationSettings).where(OrganizationSettings.organization_id == org_id)
            )
        ).scalar_one()
        existing.timezone = "UTC"
        rolled = await outbox.emit_event(
            db,
            organization_id=org_id,
            event_type="payroll.run.posted",
            payload={"path": "rollback"},
        )
        rolled_id = rolled.id
        await db.rollback()

    async with factory() as other:
        assert (
            await other.execute(select(OutboxEvent).where(OutboxEvent.id == rolled_id))
        ).scalar_one_or_none() is None
        settings_row = (
            await other.execute(
                select(OrganizationSettings).where(OrganizationSettings.organization_id == org_id)
            )
        ).scalar_one()
        assert settings_row.timezone == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_claim_skips_locked_and_processed_rows(session):
    org = await seed_organization(session, slug="outbox-skip")
    await session.commit()

    e1 = await _emit(session, org.id, payload={"n": 1})
    e2 = await _emit(session, org.id, payload={"n": 2})
    e3 = await _emit(session, org.id, payload={"n": 3})
    await session.commit()

    claimed = await outbox.claim_batch(
        session, dispatcher_id="d-lock", batch_size=1, lock_seconds=120
    )
    assert len(claimed) == 1
    locked_id = claimed[0].id
    await outbox.mark_processed(
        session, event_ids=[e2.id], dispatcher_id="nobody"
    )  # no-op (not owner)
    # Mark e2 processed via direct update to simulate a completed row.
    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == e2.id)
        .values(processed_at=utcnow(), locked_by=None, locked_until=None)
    )
    await session.commit()

    again = await outbox.claim_batch(
        session, dispatcher_id="d-next", batch_size=10, lock_seconds=60
    )
    claimed_ids = {e.id for e in again}
    assert locked_id not in claimed_ids
    assert e2.id not in claimed_ids
    assert e3.id in claimed_ids or e1.id in claimed_ids
    assert claimed_ids <= {e1.id, e3.id}


@pytest.mark.asyncio
async def test_two_dispatchers_claim_disjoint_sets_skip_locked(session):
    org = await seed_organization(session, slug="outbox-skip-locked")
    await session.commit()

    for i in range(5):
        await _emit(session, org.id, payload={"i": i})
    await session.commit()

    factory = get_session_factory()
    started = asyncio.Event()
    release = asyncio.Event()
    results: dict[str, set[UUID]] = {}

    async def claimer(name: str, batch_size: int, hold: bool) -> None:
        async with factory() as db:
            claimed = await outbox.claim_batch(
                db,
                dispatcher_id=name,
                batch_size=batch_size,
                lock_seconds=60,
            )
            results[name] = {e.id for e in claimed}
            if hold:
                started.set()
                await release.wait()
            await db.commit()

    task_a = asyncio.create_task(claimer("dispatcher-a", batch_size=2, hold=True))
    await asyncio.wait_for(started.wait(), timeout=5.0)
    task_b = asyncio.create_task(claimer("dispatcher-b", batch_size=10, hold=False))
    await asyncio.wait_for(task_b, timeout=5.0)
    release.set()
    await asyncio.wait_for(task_a, timeout=5.0)

    assert results["dispatcher-a"]
    assert results["dispatcher-b"]
    assert results["dispatcher-a"].isdisjoint(results["dispatcher-b"])
    assert len(results["dispatcher-a"]) + len(results["dispatcher-b"]) == 5


@pytest.mark.asyncio
async def test_mark_processed_owner_check(session):
    org = await seed_organization(session, slug="outbox-owner")
    await session.commit()

    event = await _emit(session, org.id)
    await session.commit()

    claimed = await outbox.claim_batch(
        session, dispatcher_id="owner", batch_size=1, lock_seconds=60
    )
    assert claimed[0].id == event.id
    await session.commit()

    updated = await outbox.mark_processed(session, event_ids=[event.id], dispatcher_id="intruder")
    assert updated == 0
    await session.commit()

    row = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.id == event.id))
    ).scalar_one()
    assert row.processed_at is None
    assert row.locked_by == "owner"

    updated = await outbox.mark_processed(session, event_ids=[event.id], dispatcher_id="owner")
    assert updated == 1
    await session.commit()

    row = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.id == event.id))
    ).scalar_one()
    assert row.processed_at is not None
    assert row.locked_by is None


@pytest.mark.asyncio
async def test_release_or_retry_increments_attempts_and_reclaim_after_expiry(session):
    org = await seed_organization(session, slug="outbox-retry")
    await session.commit()

    event = await _emit(session, org.id)
    await session.commit()

    claimed = await outbox.claim_batch(session, dispatcher_id="d1", batch_size=1, lock_seconds=60)
    assert claimed[0].id == event.id
    await session.commit()

    await outbox.release_or_retry(session, event_id=event.id, dispatcher_id="d1")
    await session.commit()

    row = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.id == event.id))
    ).scalar_one()
    assert row.attempts == 1
    assert row.locked_by is None
    assert row.locked_until is None

    # Re-claim, then expire the lease without releasing — another dispatcher wins.
    claimed2 = await outbox.claim_batch(session, dispatcher_id="d2", batch_size=1, lock_seconds=60)
    assert claimed2[0].id == event.id
    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event.id)
        .values(locked_until=utcnow() - timedelta(seconds=1))
    )
    await session.commit()

    claimed3 = await outbox.claim_batch(session, dispatcher_id="d3", batch_size=1, lock_seconds=60)
    assert len(claimed3) == 1
    assert claimed3[0].id == event.id
    assert claimed3[0].locked_by == "d3"
    assert claimed3[0].attempts == 1


@pytest.mark.asyncio
async def test_dispatch_pending_happy_path(session):
    org = await seed_organization(session, slug="outbox-dispatch-ok")
    await session.commit()

    e1 = await _emit(session, org.id, payload={"n": 1})
    e2 = await _emit(session, org.id, payload={"n": 2})
    await session.commit()

    seen: list[UUID] = []

    async def handler(event: OutboxEvent) -> None:
        seen.append(event.id)

    counts = await outbox.dispatch_pending(
        session,
        dispatcher_id="disp-ok",
        handler=handler,
        batch_size=10,
    )
    await session.commit()

    assert counts == {"processed": 2, "failed": 0}
    assert set(seen) == {e1.id, e2.id}

    for event_id in (e1.id, e2.id):
        row = (
            await session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))
        ).scalar_one()
        assert row.processed_at is not None


@pytest.mark.asyncio
async def test_dispatch_pending_mixed_success_failure(session):
    org = await seed_organization(session, slug="outbox-dispatch-mix")
    await session.commit()

    ok = await _emit(session, org.id, event_type="payroll.run.approved", payload={"k": "ok"})
    bad = await _emit(session, org.id, event_type="payroll.run.posted", payload={"k": "bad"})
    await session.commit()

    async def handler(event: OutboxEvent) -> None:
        if event.payload.get("k") == "bad":
            raise RuntimeError("sink down")

    counts = await outbox.dispatch_pending(
        session,
        dispatcher_id="disp-mix",
        handler=handler,
        batch_size=10,
    )
    await session.commit()

    assert counts["processed"] == 1
    assert counts["failed"] == 1

    ok_row = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.id == ok.id))
    ).scalar_one()
    bad_row = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.id == bad.id))
    ).scalar_one()
    assert ok_row.processed_at is not None
    assert bad_row.processed_at is None
    assert bad_row.attempts == 1
    assert bad_row.locked_by is None


@pytest.mark.asyncio
async def test_outbox_delete_forbidden_by_trigger(session):
    org = await seed_organization(session, slug="outbox-nodelete")
    await session.commit()

    event = await _emit(session, org.id)
    await session.commit()

    row = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.id == event.id))
    ).scalar_one()
    await session.delete(row)
    with pytest.raises(IntegrityError, match="(?i)DELETE forbidden"):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_claim_ordering_oldest_first_by_occurred_at(session):
    org = await seed_organization(session, slug="outbox-order")
    await session.commit()

    first = await _emit(session, org.id, payload={"order": 1})
    second = await _emit(session, org.id, payload={"order": 2})
    third = await _emit(session, org.id, payload={"order": 3})
    await session.flush()

    base = utcnow()
    await _set_occurred_at(session, third.id, base - timedelta(minutes=30))
    await _set_occurred_at(session, first.id, base - timedelta(minutes=10))
    await _set_occurred_at(session, second.id, base - timedelta(minutes=20))
    await session.commit()

    claimed = await outbox.claim_batch(
        session, dispatcher_id="orderer", batch_size=3, lock_seconds=60
    )
    assert [e.id for e in claimed] == [third.id, second.id, first.id]
    assert [e.payload["order"] for e in claimed] == [3, 2, 1]


@pytest.mark.asyncio
async def test_claim_respects_raw_skip_locked_sql_shape(session):
    """Sanity: claimable predicate matches the ADR/task SQL shape."""
    org = await seed_organization(session, slug="outbox-sql-shape")
    await session.commit()
    await _emit(session, org.id)
    await session.commit()

    result = await session.execute(
        text(
            """
            SELECT id FROM outbox_events
            WHERE processed_at IS NULL
              AND (locked_until IS NULL OR locked_until < now())
            ORDER BY occurred_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
    )
    assert result.first() is not None
    await session.rollback()
