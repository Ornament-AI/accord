"""State-machine + concurrency + RLS tests for ``PostgresJobQueue``.

Mirrors ``test_job_queue_state_machine.py`` against real PostgreSQL using the
migration scratch-DB fixtures (same conventions as ``tests/models/conftest.py``).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.jobs import (
    JobAlreadyTerminal,
    JobCancelled,
    JobStatus,
    LeaseLost,
)
from app.jobs.postgres import PostgresJobQueue, bind_organization
from app.models.identity import Organization
from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
    scratch_db as scratch_db,  # noqa: F401
)


def _grant_table_dml(database_url: str) -> None:
    import psycopg

    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


@pytest_asyncio.fixture
async def pg_env(
    scratch_db: str,
) -> AsyncIterator[tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str]]:
    """Migrated scratch DB + session factory + unbound queue."""
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    queue = PostgresJobQueue(session_factory)
    try:
        yield queue, session_factory, scratch_db
    finally:
        await engine.dispose()


async def _create_org(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: uuid.UUID | None = None,
) -> uuid.UUID:
    org_id = org_id or uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Organization(
                id=org_id,
                name=f"Org {org_id.hex[:8]}",
                slug=f"org-{org_id.hex[:12]}",
            )
        )
        await session.commit()
    return org_id


async def _expire_lease(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await bind_organization(session, organization_id)
        await session.execute(
            text(
                "UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :job_id"
            ),
            {"job_id": job_id},
        )
        await session.commit()


async def _force_available_now(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await bind_organization(session, organization_id)
        await session.execute(
            text("UPDATE jobs SET available_at = now() WHERE id = :job_id"),
            {"job_id": job_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_enqueue_basic(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
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
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    first = await bound.enqueue(
        org,
        "export.generate",
        {"n": 1},
        dedupe_key="run-1",
    )
    second = await bound.enqueue(
        org,
        "export.generate",
        {"n": 2},
        dedupe_key="run-1",
    )
    assert second.id == first.id
    assert second.payload == {"n": 1}

    claimed = await bound.claim("worker-a")
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == JobStatus.running

    third = await bound.enqueue(
        org,
        "export.generate",
        {"n": 3},
        dedupe_key="run-1",
    )
    assert third.id == first.id
    assert third.status == JobStatus.running


@pytest.mark.asyncio
async def test_enqueue_dedupe_does_not_collide_across_job_type(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    """Same dedupe_key may coexist for different job types (singleton org)."""
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    a = await queue.enqueue(org, "export.generate", {}, dedupe_key="same")
    b = await queue.enqueue(org, "storage.purge_expired", {}, dedupe_key="same")
    assert a.id != b.id
    # Same org + type + key collapses to one job.
    again = await queue.enqueue(org, "export.generate", {}, dedupe_key="same")
    assert again.id == a.id


@pytest.mark.asyncio
async def test_claim_sets_running_and_lease(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    enqueued = await bound.enqueue(org, "export.generate", {})
    before = datetime.now(timezone.utc)
    claimed = await bound.claim("worker-1", lease_seconds=30)
    after = datetime.now(timezone.utc)
    assert claimed is not None
    assert claimed.id == enqueued.id
    assert claimed.status == JobStatus.running
    assert claimed.attempt_count == 1
    assert claimed.lease_owner == "worker-1"
    assert claimed.started_at is not None
    assert claimed.heartbeat_at is not None
    assert claimed.lease_expires_at is not None
    assert (
        before + timedelta(seconds=29) <= claimed.lease_expires_at <= after + timedelta(seconds=31)
    )


@pytest.mark.asyncio
async def test_claim_returns_none_when_nothing_eligible(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    assert await bound.claim("worker-1") is None
    await bound.enqueue(
        org,
        "export.generate",
        {},
        available_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert await bound.claim("worker-1") is None


@pytest.mark.asyncio
async def test_claim_oldest_available_first(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    now = datetime.now(timezone.utc)
    await bound.enqueue(
        org,
        "export.generate",
        {"which": "newer"},
        available_at=now - timedelta(seconds=10),
    )
    older = await bound.enqueue(
        org,
        "export.generate",
        {"which": "older"},
        available_at=now - timedelta(seconds=60),
    )
    claimed = await bound.claim("w")
    assert claimed is not None
    assert claimed.id == older.id


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_and_guards_owner(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    claimed = await bound.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    assert claimed.lease_expires_at is not None
    previous_expiry = claimed.lease_expires_at

    await asyncio.sleep(0.05)
    beat = await bound.heartbeat(claimed.id, "worker-1", lease_seconds=60)
    assert beat.heartbeat_at is not None
    assert beat.lease_expires_at is not None
    assert beat.lease_expires_at >= previous_expiry

    with pytest.raises(LeaseLost):
        await bound.heartbeat(claimed.id, "other-worker")


@pytest.mark.asyncio
async def test_heartbeat_raises_when_cancel_requested(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    claimed = await bound.claim("worker-1")
    assert claimed is not None
    await bound.cancel(claimed.id)
    with pytest.raises(JobCancelled):
        await bound.heartbeat(claimed.id, "worker-1")


@pytest.mark.asyncio
async def test_fail_retryable_requeues_with_backoff(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=5)
    claimed = await bound.claim("worker-1")
    assert claimed is not None
    assert claimed.attempt_count == 1

    before = datetime.now(timezone.utc)
    failed = await bound.fail(claimed.id, "worker-1", "boom", retryable=True)
    assert failed.status == JobStatus.queued
    assert failed.lease_owner is None
    assert failed.last_error == "boom"
    # backoff = 2 ** min(attempt_count, 8) = 2 ** 1 = 2s
    delay = (failed.available_at - before).total_seconds()
    assert 1.5 <= delay <= 3.5

    assert await bound.claim("worker-1") is None
    await _force_available_now(factory, claimed.id, org)
    reclaimed = await bound.claim("worker-1")
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_fail_backoff_grows_exponentially_across_attempts(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=5)

    delays: list[float] = []
    job_id: uuid.UUID | None = None
    for expected_attempt in (1, 2, 3):
        if job_id is not None:
            await _force_available_now(factory, job_id, org)
        claimed = await bound.claim("w")
        assert claimed is not None
        assert claimed.attempt_count == expected_attempt
        job_id = claimed.id
        before = datetime.now(timezone.utc)
        failed = await bound.fail(claimed.id, "w", f"e{expected_attempt}", retryable=True)
        assert failed.status == JobStatus.queued
        delays.append((failed.available_at - before).total_seconds())

    # 2**1=2, 2**2=4, 2**3=8
    assert 1.5 <= delays[0] <= 3.5
    assert 3.5 <= delays[1] <= 5.5
    assert 7.0 <= delays[2] <= 9.5
    assert delays[0] < delays[1] < delays[2]


@pytest.mark.asyncio
async def test_fail_until_max_attempts_goes_dead_letter(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=2)
    first = await bound.claim("w")
    assert first is not None
    await bound.fail(first.id, "w", "e1", retryable=True)
    await _force_available_now(factory, first.id, org)
    second = await bound.claim("w")
    assert second is not None
    assert second.attempt_count == 2
    before = datetime.now(timezone.utc)
    dead = await bound.fail(second.id, "w", "e2", retryable=True)
    assert dead.status == JobStatus.dead_letter
    assert dead.finished_at is not None
    assert before <= dead.finished_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    assert dead.last_error == "e2"


@pytest.mark.asyncio
async def test_fail_non_retryable_goes_dead_letter(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=5)
    claimed = await bound.claim("w")
    assert claimed is not None
    dead = await bound.fail(claimed.id, "w", "bad payload", retryable=False)
    assert dead.status == JobStatus.dead_letter
    assert dead.last_error == "bad payload"


@pytest.mark.asyncio
async def test_cancel_queued_is_immediate(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    job = await bound.enqueue(org, "export.generate", {})
    cancelled = await bound.cancel(job.id)
    assert cancelled.status == JobStatus.cancelled
    assert cancelled.cancel_requested is True
    assert cancelled.finished_at is not None
    assert await bound.claim("w") is None


@pytest.mark.asyncio
async def test_cancel_running_is_cooperative_then_acknowledge(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    claimed = await bound.claim("worker-1")
    assert claimed is not None
    flagged = await bound.cancel(claimed.id)
    assert flagged.status == JobStatus.running
    assert flagged.cancel_requested is True

    finished = await bound.acknowledge_cancel(claimed.id, "worker-1")
    assert finished.status == JobStatus.cancelled
    assert finished.finished_at is not None
    assert finished.lease_owner is None


@pytest.mark.asyncio
async def test_reap_expired_leases_requeues_when_attempts_remain(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=5)
    claimed = await bound.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    await _expire_lease(factory, claimed.id, org)
    reaped = await bound.reap_expired_leases()
    assert len(reaped) == 1
    assert reaped[0].status == JobStatus.queued
    assert reaped[0].lease_owner is None


@pytest.mark.asyncio
async def test_reap_expired_leases_dead_letters_when_attempts_exhausted(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=1)
    claimed = await bound.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    assert claimed.attempt_count == 1
    await _expire_lease(factory, claimed.id, org)
    reaped = await bound.reap_expired_leases()
    assert len(reaped) == 1
    assert reaped[0].status == JobStatus.dead_letter
    assert reaped[0].finished_at is not None


@pytest.mark.asyncio
async def test_claim_opportunistically_reaps_expired_leases(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=5)
    claimed = await bound.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    await _expire_lease(factory, claimed.id, org)
    reclaimed = await bound.claim("worker-2", lease_seconds=60)
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.lease_owner == "worker-2"
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_complete_succeeds(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    claimed = await bound.claim("w")
    assert claimed is not None
    done = await bound.complete(claimed.id, "w", result={"artifact_id": "a1"})
    assert done.status == JobStatus.succeeded
    assert done.result == {"artifact_id": "a1"}
    assert done.finished_at is not None


@pytest.mark.asyncio
async def test_reap_expired_lease_with_cancel_requested_becomes_cancelled(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {}, max_attempts=5)
    claimed = await bound.claim("worker-1", lease_seconds=60)
    assert claimed is not None
    await bound.cancel(claimed.id)
    await _expire_lease(factory, claimed.id, org)
    reaped = await bound.reap_expired_leases()
    assert len(reaped) == 1
    assert reaped[0].status == JobStatus.cancelled
    assert reaped[0].finished_at is not None
    assert await bound.claim("worker-2") is None


@pytest.mark.asyncio
async def test_fail_raises_when_cancel_requested(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    claimed = await bound.claim("worker-1")
    assert claimed is not None
    await bound.cancel(claimed.id)
    with pytest.raises(JobCancelled):
        await bound.fail(claimed.id, "worker-1", "ignored", retryable=True)


@pytest.mark.asyncio
async def test_cancel_terminal_raises(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    claimed = await bound.claim("w")
    assert claimed is not None
    await bound.complete(claimed.id, "w")
    with pytest.raises(JobAlreadyTerminal):
        await bound.cancel(claimed.id)


@pytest.mark.asyncio
async def test_claim_filters_by_job_types(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    await bound.enqueue(org, "export.generate", {})
    await bound.enqueue(org, "storage.purge_expired", {})
    claimed = await bound.claim("w", job_types=["storage.purge_expired"])
    assert claimed is not None
    assert claimed.job_type == "storage.purge_expired"


@pytest.mark.asyncio
async def test_concurrent_claims_get_different_jobs(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    """Two simultaneous claimers must not double-claim (FOR UPDATE SKIP LOCKED)."""
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    bound = queue.for_organization(org)
    j1 = await bound.enqueue(org, "export.generate", {"n": 1})
    j2 = await bound.enqueue(org, "export.generate", {"n": 2})

    claimed = await asyncio.gather(
        bound.claim("worker-a"),
        bound.claim("worker-b"),
    )
    ids = {c.id for c in claimed if c is not None}
    assert len(ids) == 2
    assert ids == {j1.id, j2.id}
    owners = {c.lease_owner for c in claimed if c is not None}
    assert owners == {"worker-a", "worker-b"}


@pytest.mark.asyncio
async def test_rls_wrong_guc_cannot_claim_job(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    """Under accord_app + wrong org GUC, the singleton org's job is invisible."""
    queue, factory, _db = pg_env
    org = await _create_org(factory)
    wrong_org = uuid.uuid4()

    await queue.for_organization(org).enqueue(org, "export.generate", {"org": "solo"})

    class _RlsFactory:
        """Session factory that SETs ROLE accord_app and binds a GUC org id."""

        def __init__(self, inner: async_sessionmaker[AsyncSession], org_id: uuid.UUID) -> None:
            self._inner = inner
            self._org_id = org_id

        def __call__(self) -> AsyncIterator[AsyncSession]:
            return self._cm()

        @asynccontextmanager
        async def _cm(self) -> AsyncIterator[AsyncSession]:
            async with self._inner() as session:
                await session.execute(text("SET ROLE accord_app"))
                await bind_organization(session, self._org_id)
                yield session

    wrong_queue = PostgresJobQueue(_RlsFactory(factory, wrong_org))  # type: ignore[arg-type]
    assert await wrong_queue.claim("worker-rls") is None

    # Control: correct GUC under accord_app can claim.
    ok_queue = PostgresJobQueue(_RlsFactory(factory, org))  # type: ignore[arg-type]
    claimed = await ok_queue.claim("worker-rls")
    assert claimed is not None
    assert claimed.organization_id == org
