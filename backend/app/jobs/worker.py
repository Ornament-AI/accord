"""Durable job worker loop (ADR 0010 Phase 6 worker lane).

Claims are **per-organization** because ``jobs`` has forced RLS: each cycle
lists active org ids (``organizations`` has no RLS), then
``PostgresJobQueue(...).for_organization(org_id).claim(...)``.

Handler tenant context
----------------------
Handlers keep the protocol signature ``async (job) -> dict | None``. For the
duration of a handler call the loop opens a short-lived session, begins a
transaction, ``bind_tenant_context(..., organization_id=job.organization_id)``,
and exposes that session via :func:`app.jobs.handlers.current_job_session`.
The handler transaction is committed (or rolled back on error) **before**
``complete`` / ``fail`` runs on the queue (queue methods use their own sessions).

Outbox
------
Each cycle also pumps the transactional outbox via ``dispatch_pending`` with a
log-and-mark handler. ``outbox_events`` has forced RLS keyed on
``app.organization_id``, so the pump runs **per active org** with that org's
tenant context bound (the deployed worker uses ``accord_worker``, which does not
bypass RLS); otherwise the claim query would see no rows. Concrete delivery
sinks (webhooks, etc.) are TBD; this phase records structured logs and marks
rows processed so the dispatcher does not stall.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import os
import socket
import traceback
import uuid
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.handlers import bind_job_session
from app.jobs.postgres import PostgresJobQueue
from app.jobs.protocol import (
    Job,
    JobCancelled,
    JobHandler,
    JobHandlerRegistry,
    JobQueue,
    LeaseLost,
    UnknownJobType,
)
from app.models.identity import Organization
from app.models.platform import OutboxEvent
from app.services.outbox import dispatch_pending
from app.tenancy import bind_tenant_context

logger = structlog.get_logger(__name__)

_DEFAULT_LEASE_SECONDS = 60
_DEFAULT_HEARTBEAT_INTERVAL = 20.0
_DEFAULT_IDLE_BACKOFF_MIN = 1.0
_DEFAULT_IDLE_BACKOFF_MAX = 5.0
_DEFAULT_OUTBOX_BATCH_SIZE = 50
_ERROR_EXCERPT_CHARS = 2000


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _error_excerpt(exc: BaseException) -> str:
    text_out = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(text_out) > _ERROR_EXCERPT_CHARS:
        return text_out[:_ERROR_EXCERPT_CHARS]
    return text_out


async def _log_outbox_event(event: OutboxEvent) -> None:
    """Log-and-mark delivery sink (concrete targets TBD in a later phase)."""
    logger.info(
        "outbox_event_dispatch",
        event_id=str(event.id),
        organization_id=str(event.organization_id),
        event_type=event.event_type,
        delivery="log_and_mark",
    )


class WorkerLoop:
    """Poll orgs, claim/execute jobs with heartbeats, and pump the outbox."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: JobHandlerRegistry,
        *,
        worker_id: str | None = None,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL,
        idle_backoff_min: float = _DEFAULT_IDLE_BACKOFF_MIN,
        idle_backoff_max: float = _DEFAULT_IDLE_BACKOFF_MAX,
        outbox_batch_size: int = _DEFAULT_OUTBOX_BATCH_SIZE,
        queue_factory: Callable[[UUID], JobQueue] | None = None,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be >= 1")
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be > 0")
        if idle_backoff_min <= 0 or idle_backoff_max < idle_backoff_min:
            raise ValueError("idle backoff bounds are invalid")
        if outbox_batch_size < 1:
            raise ValueError("outbox_batch_size must be >= 1")

        self._session_factory = session_factory
        self._registry = registry
        self.worker_id = worker_id or _default_worker_id()
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval
        self._idle_backoff_min = idle_backoff_min
        self._idle_backoff_max = idle_backoff_max
        self._outbox_batch_size = outbox_batch_size
        self._shutdown = asyncio.Event()
        # Job-queue interactions go through the JobQueue protocol; the default
        # factory yields org-scoped Postgres queues (RLS-bound, ADR 0010).
        if queue_factory is None:
            queue_factory = PostgresJobQueue(session_factory).for_organization
        self._queue_factory = queue_factory

    def request_shutdown(self) -> None:
        """Stop claiming after the in-flight job finishes; wake idle waits."""
        self._shutdown.set()

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown.is_set()

    async def run(self) -> None:
        """Run claim/execute/outbox cycles until :meth:`request_shutdown`."""
        backoff = self._idle_backoff_min
        logger.info("worker_started", worker_id=self.worker_id)
        try:
            while not self._shutdown.is_set():
                claimed_any = await self.run_once()
                if self._shutdown.is_set():
                    break
                if claimed_any:
                    backoff = self._idle_backoff_min
                    continue
                await self._idle_wait(backoff)
                backoff = min(backoff * 2.0, self._idle_backoff_max)
        finally:
            logger.info("worker_stopped", worker_id=self.worker_id)

    async def run_once(self) -> bool:
        """Run a single poll cycle (outbox + per-org claim/execute).

        Returns ``True`` when at least one job was claimed (idle backoff resets).
        Designed for tests and as the body of :meth:`run`.
        """
        org_ids = await self._list_active_org_ids()
        claimed_any = False
        claimed_count = 0
        outbox_processed = 0
        outbox_failed = 0

        for org_id in org_ids:
            if self._shutdown.is_set():
                break
            outbox_counts = await self._pump_outbox(org_id)
            outbox_processed += outbox_counts.get("processed", 0)
            outbox_failed += outbox_counts.get("failed", 0)

            queue = self._queue_factory(org_id)
            try:
                job = await queue.claim(
                    self.worker_id,
                    lease_seconds=self._lease_seconds,
                )
            except Exception:
                logger.exception(
                    "job_claim_failed",
                    worker_id=self.worker_id,
                    organization_id=str(org_id),
                )
                continue
            if job is None:
                continue
            claimed_any = True
            claimed_count += 1
            await self._execute_claimed_job(queue, job)

        logger.debug(
            "worker_cycle",
            worker_id=self.worker_id,
            org_count=len(org_ids),
            claimed_count=claimed_count,
            claimed_any=claimed_any,
            outbox_processed=outbox_processed,
            outbox_failed=outbox_failed,
            shutdown=self._shutdown.is_set(),
        )
        return claimed_any

    async def _idle_wait(self, timeout: float) -> None:
        """Sleep up to ``timeout`` seconds, returning immediately on shutdown."""
        try:
            await asyncio.wait_for(self._shutdown.wait(), timeout=timeout)
        except TimeoutError:
            return

    async def _list_active_org_ids(self) -> list[UUID]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Organization.id)
                .where(Organization.is_active.is_(True))
                .order_by(Organization.id)
            )
            return list(result.scalars().all())

    async def _pump_outbox(self, organization_id: UUID) -> dict[str, int]:
        # ``outbox_events`` has forced RLS keyed on ``app.organization_id`` and
        # the deployed worker runs as ``accord_worker`` (NOBYPASSRLS), so the
        # claim query only sees rows once tenant context is bound. Pump per
        # active org, binding that org's GUCs first (mirrors per-org job claim).
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await bind_tenant_context(session, organization_id=organization_id)
                    counts = await dispatch_pending(
                        session,
                        dispatcher_id=self.worker_id,
                        handler=_log_outbox_event,
                        batch_size=self._outbox_batch_size,
                    )
                return dict(counts)
        except Exception:
            logger.exception(
                "outbox_pump_failed",
                worker_id=self.worker_id,
                organization_id=str(organization_id),
            )
            return {"processed": 0, "failed": 0}

    async def _execute_claimed_job(
        self,
        queue: JobQueue,
        job: Job,
    ) -> None:
        """Execute one claimed job; never raises into the outer loop."""
        try:
            await self._execute_claimed_job_inner(queue, job)
        except Exception:
            logger.exception(
                "job_execution_unhandled",
                worker_id=self.worker_id,
                job_id=str(job.id),
                job_type=job.job_type,
            )

    async def _execute_claimed_job_inner(
        self,
        queue: JobQueue,
        job: Job,
    ) -> None:
        try:
            handler = self._registry.get(job.job_type)
        except UnknownJobType as exc:
            await self._safe_fail(
                queue,
                job,
                error=str(exc),
                retryable=False,
            )
            return

        handler_task = asyncio.create_task(
            self._run_handler_with_tenant(job, handler),
            name=f"job-handler-{job.id}",
        )
        hb_task = asyncio.create_task(
            self._heartbeat_loop(queue, job, handler_task),
            name=f"job-heartbeat-{job.id}",
        )
        try:
            await asyncio.wait({handler_task}, return_when=asyncio.ALL_COMPLETED)
        finally:
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb_task

        if handler_task.cancelled():
            await self._safe_acknowledge_cancel(queue, job)
            return

        exc = handler_task.exception()
        if exc is not None:
            await self._safe_fail(
                queue,
                job,
                error=_error_excerpt(exc),
                retryable=True,
            )
            return

        result = handler_task.result()
        await self._safe_complete(queue, job, result)

    async def _run_handler_with_tenant(
        self,
        job: Job,
        handler: JobHandler,
    ) -> dict | None:
        # Do NOT wrap the handler in ``async with session.begin()``. Handlers
        # such as ``generate_report`` (via ``create_artifact``) intentionally
        # commit mid-flight and re-open a transaction to finalize the artifact
        # after the object upload; an enclosing ``begin()`` block would treat
        # that first commit as the end of its context, so the later finalize
        # would run outside a transaction and the job would fail after upload.
        # Instead open a transaction, bind tenant GUCs, and commit whatever
        # transaction the handler leaves open (self-committing handlers leave
        # none). This preserves the commit-before-complete ordering.
        async with self._session_factory() as session:
            await session.begin()
            await bind_tenant_context(
                session,
                organization_id=job.organization_id,
            )
            try:
                with bind_job_session(session):
                    result = await handler(job)
            except BaseException:
                if session.in_transaction():
                    await session.rollback()
                raise
            if session.in_transaction():
                await session.commit()
            return result

    async def _heartbeat_loop(
        self,
        queue: JobQueue,
        job: Job,
        handler_task: asyncio.Task[dict | None],
    ) -> None:
        while not handler_task.done():
            await asyncio.sleep(self._heartbeat_interval)
            if handler_task.done():
                return
            try:
                await queue.heartbeat(
                    job.id,
                    self.worker_id,
                    lease_seconds=self._lease_seconds,
                )
            except JobCancelled:
                handler_task.cancel()
                return
            except LeaseLost:
                handler_task.cancel()
                return
            except Exception:
                logger.exception(
                    "job_heartbeat_failed",
                    worker_id=self.worker_id,
                    job_id=str(job.id),
                )

    async def _safe_complete(
        self,
        queue: JobQueue,
        job: Job,
        result: dict | None,
    ) -> None:
        try:
            await queue.complete(job.id, self.worker_id, result)
        except JobCancelled:
            await self._safe_acknowledge_cancel(queue, job)
        except Exception:
            logger.exception(
                "job_complete_failed",
                worker_id=self.worker_id,
                job_id=str(job.id),
            )

    async def _safe_fail(
        self,
        queue: JobQueue,
        job: Job,
        *,
        error: str,
        retryable: bool,
    ) -> None:
        try:
            await queue.fail(
                job.id,
                self.worker_id,
                error,
                retryable=retryable,
            )
        except JobCancelled:
            await self._safe_acknowledge_cancel(queue, job)
        except Exception:
            logger.exception(
                "job_fail_failed",
                worker_id=self.worker_id,
                job_id=str(job.id),
            )

    async def _safe_acknowledge_cancel(
        self,
        queue: JobQueue,
        job: Job,
    ) -> None:
        try:
            await queue.acknowledge_cancel(job.id, self.worker_id)
        except Exception:
            logger.exception(
                "job_acknowledge_cancel_failed",
                worker_id=self.worker_id,
                job_id=str(job.id),
            )
