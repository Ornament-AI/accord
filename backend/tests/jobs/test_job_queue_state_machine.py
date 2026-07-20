"""State-machine tests for ``JobQueue`` (ADR 0010 Phase 1 in-memory double).

Phase-6 seam
------------
These tests target the ``JobQueue`` contract via ``InMemoryJobQueue``. When
Phase 6 adds a Postgres-backed queue, introduce a parametrized
``QUEUE_FACTORIES`` fixture list (same pattern as
``tests/storage/test_object_storage_protocol.py``) so these bodies can run
against both implementations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.jobs import (
    InMemoryJobQueue,
    JobAlreadyTerminal,
    JobCancelled,
    JobHandlerRegistry,
    JobStatus,
    LeaseLost,
    UnknownJobType,
)


class _Clock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def queue(clock: _Clock) -> InMemoryJobQueue:
    return InMemoryJobQueue(now_fn=clock)


@pytest.mark.asyncio
async def test_enqueue_basic(queue: InMemoryJobQueue) -> None:
    org = uuid4()
    job = await queue.enqueue(org, "export.generate", {"run_id": "r1"})
    assert job.organization_id == org
    assert job.job_type == "export.generate"
    assert job.status == JobStatus.queued
    assert job.payload == {"run_id": "r1"}
    assert job.attempt_count == 0
    assert job.max_attempts == 5
    assert job.cancel_requested is False


@pytest.mark.asyncio
async def test_enqueue_dedupe_returns_same_inflight_job(
    queue: InMemoryJobQueue,
) -> None:
    org = uuid4()
    first = await queue.enqueue(
        org,
        "export.generate",
        {"n": 1},
        dedupe_key="run-1",
    )
    second = await queue.enqueue(
        org,
        "export.generate",
        {"n": 2},
        dedupe_key="run-1",
    )
    assert second.id == first.id
    assert second.payload == {"n": 1}

    claimed = await queue.claim("worker-a")
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == JobStatus.running

    third = await queue.enqueue(
        org,
        "export.generate",
        {"n": 3},
        dedupe_key="run-1",
    )
    assert third.id == first.id
    assert third.status == JobStatus.running


@pytest.mark.asyncio
async def test_enqueue_dedupe_does_not_collide_across_job_type(
    queue: InMemoryJobQueue,
) -> None:
    """In-memory queue: dedupe is per (org, type, key); types stay independent."""
    org = uuid4()
    a = await queue.enqueue(org, "export.generate", {}, dedupe_key="same")
    b = await queue.enqueue(org, "storage.purge_expired", {}, dedupe_key="same")
    again = await queue.enqueue(org, "export.generate", {}, dedupe_key="same")
    assert a.id != b.id
    assert again.id == a.id


@pytest.mark.asyncio
async def test_claim_sets_running_and_lease(queue: InMemoryJobQueue, clock: _Clock) -> None:
    org = uuid4()
    enqueued = await queue.enqueue(org, "export.generate", {})
    claimed = await queue.claim("worker-1", lease_seconds=30)
    assert claimed is not None
    assert claimed.id == enqueued.id
    assert claimed.status == JobStatus.running
    assert claimed.attempt_count == 1
    assert claimed.lease_owner == "worker-1"
    assert claimed.lease_expires_at == clock.now + timedelta(seconds=30)
    assert claimed.started_at == clock.now
    assert claimed.heartbeat_at == clock.now


@pytest.mark.asyncio
async def test_claim_returns_none_when_nothing_eligible(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    assert await queue.claim("worker-1") is None
    await queue.enqueue(
        uuid4(),
        "export.generate",
        {},
        available_at=clock.now + timedelta(hours=1),
    )
    assert await queue.claim("worker-1") is None


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_and_guards_owner(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    claimed = await queue.claim("worker-1", lease_seconds=60)
    assert claimed is not None

    clock.advance(10)
    beat = await queue.heartbeat(claimed.id, "worker-1", lease_seconds=60)
    assert beat.heartbeat_at == clock.now
    assert beat.lease_expires_at == clock.now + timedelta(seconds=60)

    with pytest.raises(LeaseLost):
        await queue.heartbeat(claimed.id, "other-worker")


@pytest.mark.asyncio
async def test_heartbeat_raises_when_cancel_requested(
    queue: InMemoryJobQueue,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    claimed = await queue.claim("worker-1")
    assert claimed is not None
    await queue.cancel(claimed.id)
    with pytest.raises(JobCancelled):
        await queue.heartbeat(claimed.id, "worker-1")


@pytest.mark.asyncio
async def test_fail_retryable_requeues_with_backoff(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=5)
    claimed = await queue.claim("worker-1")
    assert claimed is not None
    assert claimed.attempt_count == 1

    failed = await queue.fail(claimed.id, "worker-1", "boom", retryable=True)
    assert failed.status == JobStatus.queued
    assert failed.lease_owner is None
    assert failed.last_error == "boom"
    # backoff = 2 ** min(attempt_count, 8) = 2 ** 1 = 2s
    assert failed.available_at == clock.now + timedelta(seconds=2)

    assert await queue.claim("worker-1") is None
    clock.advance(2)
    reclaimed = await queue.claim("worker-1")
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_fail_until_max_attempts_goes_dead_letter(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=2)
    first = await queue.claim("w")
    assert first is not None
    await queue.fail(first.id, "w", "e1", retryable=True)
    clock.advance(2)
    second = await queue.claim("w")
    assert second is not None
    assert second.attempt_count == 2
    dead = await queue.fail(second.id, "w", "e2", retryable=True)
    assert dead.status == JobStatus.dead_letter
    assert dead.finished_at == clock.now
    assert dead.last_error == "e2"


@pytest.mark.asyncio
async def test_fail_non_retryable_goes_dead_letter(
    queue: InMemoryJobQueue,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=5)
    claimed = await queue.claim("w")
    assert claimed is not None
    dead = await queue.fail(claimed.id, "w", "bad payload", retryable=False)
    assert dead.status == JobStatus.dead_letter
    assert dead.last_error == "bad payload"


@pytest.mark.asyncio
async def test_cancel_queued_is_immediate(queue: InMemoryJobQueue) -> None:
    job = await queue.enqueue(uuid4(), "export.generate", {})
    cancelled = await queue.cancel(job.id)
    assert cancelled.status == JobStatus.cancelled
    assert cancelled.cancel_requested is True
    assert cancelled.finished_at is not None
    assert await queue.claim("w") is None


@pytest.mark.asyncio
async def test_cancel_running_is_cooperative_then_acknowledge(
    queue: InMemoryJobQueue,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    claimed = await queue.claim("worker-1")
    assert claimed is not None
    flagged = await queue.cancel(claimed.id)
    assert flagged.status == JobStatus.running
    assert flagged.cancel_requested is True

    finished = await queue.acknowledge_cancel(claimed.id, "worker-1")
    assert finished.status == JobStatus.cancelled
    assert finished.finished_at is not None
    assert finished.lease_owner is None


@pytest.mark.asyncio
async def test_reap_expired_leases_requeues_when_attempts_remain(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=5)
    claimed = await queue.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    clock.advance(61)
    reaped = await queue.reap_expired_leases()
    assert len(reaped) == 1
    assert reaped[0].status == JobStatus.queued
    assert reaped[0].lease_owner is None
    assert reaped[0].available_at == clock.now


@pytest.mark.asyncio
async def test_reap_expired_leases_dead_letters_when_attempts_exhausted(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=1)
    claimed = await queue.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    assert claimed.attempt_count == 1
    clock.advance(61)
    reaped = await queue.reap_expired_leases()
    assert len(reaped) == 1
    assert reaped[0].status == JobStatus.dead_letter
    assert reaped[0].finished_at == clock.now


@pytest.mark.asyncio
async def test_claim_opportunistically_reaps_expired_leases(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=5)
    claimed = await queue.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    clock.advance(61)
    # claim() reaps first, then claims the requeued job for a new worker.
    reclaimed = await queue.claim("worker-2", lease_seconds=60)
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.lease_owner == "worker-2"
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_job_handler_registry_register_get_unknown() -> None:
    registry = JobHandlerRegistry()

    @registry.register("export.generate")
    async def _handle(job):  # noqa: ANN001
        return {"ok": True, "id": str(job.id)}

    handler = registry.get("export.generate")
    job = await InMemoryJobQueue().enqueue(uuid4(), "export.generate", {})
    result = await handler(job)
    assert result == {"ok": True, "id": str(job.id)}

    with pytest.raises(UnknownJobType):
        registry.get("missing.type")


@pytest.mark.asyncio
async def test_complete_succeeds(queue: InMemoryJobQueue) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    claimed = await queue.claim("w")
    assert claimed is not None
    done = await queue.complete(claimed.id, "w", result={"artifact_id": "a1"})
    assert done.status == JobStatus.succeeded
    assert done.result == {"artifact_id": "a1"}
    assert done.finished_at is not None


@pytest.mark.asyncio
async def test_reap_expired_lease_with_cancel_requested_becomes_cancelled(
    queue: InMemoryJobQueue,
    clock: _Clock,
) -> None:
    await queue.enqueue(uuid4(), "export.generate", {}, max_attempts=5)
    claimed = await queue.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    await queue.cancel(claimed.id)
    clock.advance(61)
    reaped = await queue.reap_expired_leases()
    assert len(reaped) == 1
    assert reaped[0].status == JobStatus.cancelled
    assert reaped[0].finished_at == clock.now
    assert await queue.claim("worker-2") is None


@pytest.mark.asyncio
async def test_fail_raises_when_cancel_requested(queue: InMemoryJobQueue) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    claimed = await queue.claim("worker-1")
    assert claimed is not None
    await queue.cancel(claimed.id)
    with pytest.raises(JobCancelled):
        await queue.fail(claimed.id, "worker-1", "ignored", retryable=True)


@pytest.mark.asyncio
async def test_cancel_terminal_raises(queue: InMemoryJobQueue) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    claimed = await queue.claim("w")
    assert claimed is not None
    await queue.complete(claimed.id, "w")
    with pytest.raises(JobAlreadyTerminal):
        await queue.cancel(claimed.id)


@pytest.mark.asyncio
async def test_claim_filters_by_job_types(queue: InMemoryJobQueue) -> None:
    await queue.enqueue(uuid4(), "export.generate", {})
    await queue.enqueue(uuid4(), "storage.purge_expired", {})
    claimed = await queue.claim("w", job_types=["storage.purge_expired"])
    assert claimed is not None
    assert claimed.job_type == "storage.purge_expired"
