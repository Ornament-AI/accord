"""Integration tests for ``WorkerLoop`` against real PostgreSQL."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.jobs.handlers import current_job_session, register_handlers
from app.jobs.postgres import PostgresJobQueue, bind_organization
from app.jobs.protocol import Job, JobHandlerRegistry, JobStatus
from app.jobs.worker import WorkerLoop
from app.models.identity import Organization
from app.services import outbox
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


@pytest_asyncio.fixture(autouse=True)
async def _truncate_jobs_and_outbox(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> AsyncIterator[None]:
    _, factory, _ = pg_env
    async with factory() as session:
        await session.execute(text("TRUNCATE TABLE jobs, outbox_events RESTART IDENTITY CASCADE"))
        await session.commit()
    yield


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


async def _load_job(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict:
    async with session_factory() as session:
        await bind_organization(session, organization_id)
        result = await session.execute(
            text("SELECT * FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        )
        row = result.mappings().one()
        return dict(row)


def _worker(
    factory: async_sessionmaker[AsyncSession],
    registry: JobHandlerRegistry,
    *,
    worker_id: str = "test-worker",
    lease_seconds: int = 5,
    heartbeat_interval: float = 0.1,
) -> WorkerLoop:
    return WorkerLoop(
        factory,
        registry,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        heartbeat_interval=heartbeat_interval,
        idle_backoff_min=0.05,
        idle_backoff_max=0.2,
        outbox_batch_size=50,
    )


@pytest.mark.asyncio
async def test_happy_path_tenant_guc_and_result(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    registry = JobHandlerRegistry()
    register_handlers(registry)
    seen_org: dict[str, str] = {}

    @registry.register("tenant.check")
    async def tenant_check(job: Job) -> dict | None:
        session = current_job_session()
        value = (
            await session.execute(text("SELECT current_setting('app.organization_id', true)"))
        ).scalar_one()
        seen_org["value"] = value
        return {"checked": True, "org": value}

    bound = queue.for_organization(org)
    enqueued = await bound.enqueue(org, "tenant.check", {"n": 1})
    worker = _worker(factory, registry)
    claimed = await worker.run_once()
    assert claimed is True

    row = await _load_job(factory, org, enqueued.id)
    assert row["status"] == JobStatus.succeeded.value
    assert row["result"] == {"checked": True, "org": str(org)}
    assert seen_org["value"] == str(org)


@pytest.mark.asyncio
async def test_handler_raises_requeues_and_loop_continues(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    registry = JobHandlerRegistry()

    @registry.register("boom")
    async def boom(_job: Job) -> dict | None:
        raise RuntimeError("handler exploded")

    bound = queue.for_organization(org)
    enqueued = await bound.enqueue(org, "boom", {}, max_attempts=5)
    worker = _worker(factory, registry)
    before = datetime.now(timezone.utc)
    assert await worker.run_once() is True

    row = await _load_job(factory, org, enqueued.id)
    assert row["status"] == JobStatus.queued.value
    assert row["last_error"] is not None
    assert "handler exploded" in row["last_error"]
    assert row["available_at"] > before
    assert row["lease_owner"] is None

    # Loop remains usable after a handler failure.
    await bound.enqueue(org, "noop", {})
    register_handlers(registry)
    assert await worker.run_once() is True


@pytest.mark.asyncio
async def test_lease_heartbeat_extends_during_long_handler(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    registry = JobHandlerRegistry()
    started = asyncio.Event()

    @registry.register("slow.beat")
    async def slow_beat(_job: Job) -> dict | None:
        started.set()
        await asyncio.sleep(0.45)
        return {"ok": True}

    bound = queue.for_organization(org)
    enqueued = await bound.enqueue(org, "slow.beat", {})
    worker = _worker(
        factory,
        registry,
        lease_seconds=2,
        heartbeat_interval=0.1,
    )

    cycle = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(started.wait(), timeout=2.0)
    await asyncio.sleep(0.25)
    mid = await _load_job(factory, org, enqueued.id)
    assert mid["status"] == JobStatus.running.value
    assert mid["heartbeat_at"] is not None
    assert mid["started_at"] is not None
    assert mid["heartbeat_at"] > mid["started_at"]
    assert mid["lease_expires_at"] is not None

    assert await asyncio.wait_for(cycle, timeout=3.0) is True
    done = await _load_job(factory, org, enqueued.id)
    assert done["status"] == JobStatus.succeeded.value
    assert done["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_shutdown_finishes_in_flight_and_stops_claiming(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org = await _create_org(factory)
    registry = JobHandlerRegistry()
    started = asyncio.Event()

    @registry.register("slow.shutdown")
    async def slow_shutdown(_job: Job) -> dict | None:
        started.set()
        await asyncio.sleep(0.35)
        return {"done": True}

    bound = queue.for_organization(org)
    first = await bound.enqueue(org, "slow.shutdown", {"n": 1})
    second = await bound.enqueue(org, "slow.shutdown", {"n": 2})

    worker = _worker(factory, registry, heartbeat_interval=0.05)
    run_task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), timeout=2.0)
    worker.request_shutdown()
    await asyncio.wait_for(run_task, timeout=3.0)

    row_first = await _load_job(factory, org, first.id)
    row_second = await _load_job(factory, org, second.id)
    assert row_first["status"] == JobStatus.succeeded.value
    assert row_first["result"] == {"done": True}
    assert row_second["status"] == JobStatus.queued.value
    assert row_second["lease_owner"] is None
    assert worker.shutdown_requested is True


@pytest.mark.asyncio
async def test_outbox_pump_marks_events_processed(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    _queue, factory, _ = pg_env
    org = await _create_org(factory)
    registry = JobHandlerRegistry()

    async with factory() as session:
        event = await outbox.emit_event(
            session,
            organization_id=org,
            event_type="payroll.run.approved",
            payload={"run_id": "r1"},
        )
        await session.commit()
        event_id = event.id

    worker = _worker(factory, registry)
    await worker.run_once()

    async with factory() as session:
        processed_at = (
            await session.execute(
                text("SELECT processed_at FROM outbox_events WHERE id = :event_id"),
                {"event_id": event_id},
            )
        ).scalar_one()
    assert processed_at is not None


@pytest.mark.asyncio
async def test_multi_org_jobs_completed_across_cycles(
    pg_env: tuple[PostgresJobQueue, async_sessionmaker[AsyncSession], str],
) -> None:
    queue, factory, _ = pg_env
    org_a = await _create_org(factory)
    org_b = await _create_org(factory)
    registry = JobHandlerRegistry()
    seen: list[str] = []

    @registry.register("multi.org")
    async def multi_org(job: Job) -> dict | None:
        seen.append(str(job.organization_id))
        return {"org": str(job.organization_id)}

    job_a = await queue.for_organization(org_a).enqueue(org_a, "multi.org", {})
    job_b = await queue.for_organization(org_b).enqueue(org_b, "multi.org", {})

    worker = _worker(factory, registry)
    # One cycle claims at most one job per org — both should finish in one pass.
    assert await worker.run_once() is True

    row_a = await _load_job(factory, org_a, job_a.id)
    row_b = await _load_job(factory, org_b, job_b.id)
    assert row_a["status"] == JobStatus.succeeded.value
    assert row_b["status"] == JobStatus.succeeded.value
    assert set(seen) == {str(org_a), str(org_b)}
