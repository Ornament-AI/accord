"""PostgreSQL-backed ``JobQueue`` (ADR 0010).

Constructor choice
------------------
``PostgresJobQueue`` takes an ``async_sessionmaker[AsyncSession]`` (a
*session factory*), matching ``app.db.get_session_factory()``. Each protocol
method opens its own short-lived session and commits. Callers that already
hold a request-scoped session should not share it with the queue — enqueue
from the API path that owns the tenant transaction can still use the same
factory; the worker loop uses the factory for claim/heartbeat/complete.

Optional ``organization_id`` binds ``app.organization_id`` via
``set_config(..., is_local=true)`` at the start of every queue transaction.
``enqueue`` always binds the org from its ``organization_id`` argument so
tenant inserts succeed under forced RLS.

Worker-lane / RLS note
----------------------
The ``jobs`` table has **forced** RLS for ``accord_app`` and ``accord_worker``
(``organization_id = current_setting('app.organization_id')::uuid``). A
worker connection running as those roles can only see and claim rows for the
currently bound org. Cross-org claim is therefore **not** available on the
normal app/worker role.

The worker loop must either:

1. **Per-org claim** — iterate known org ids, ``SET LOCAL app.organization_id``
   (or construct ``PostgresJobQueue(factory, organization_id=org)``), then
   ``claim``; or
2. **Privileged / maintenance connection** — a role that bypasses RLS (or is
   not subject to the tenant policies), claim across orgs, then set the org
   GUC to the claimed row's ``organization_id`` before tenant writes.

This module implements (1): ``claim`` runs under the session's current org
context as-is. No privileged bypass and no new migrations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from asyncpg.exceptions import UniqueViolationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.protocol import (
    TERMINAL_STATUSES,
    Job,
    JobAlreadyTerminal,
    JobCancelled,
    JobNotFound,
    JobStatus,
    LeaseLost,
)
from app.models.platform import Job as JobRow


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _integrity_is_unique(exc: IntegrityError) -> bool:
    """Return True when ``exc`` wraps an asyncpg unique violation."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, UniqueViolationError):
            return True
        current = current.__cause__ or getattr(current, "orig", None)
    orig = getattr(exc, "orig", None)
    if orig is not None and "unique" in str(orig).lower():
        return True
    return "unique" in str(exc).lower()


def _row_to_job(row: JobRow | Any) -> Job:
    """Map an ORM row or mapping to the protocol ``Job`` model."""
    if isinstance(row, JobRow):
        data = {
            "id": row.id,
            "organization_id": row.organization_id,
            "job_type": row.job_type,
            "status": row.status,
            "payload": dict(row.payload or {}),
            "result": None if row.result is None else dict(row.result),
            "dedupe_key": row.dedupe_key,
            "attempt_count": row.attempt_count,
            "max_attempts": row.max_attempts,
            "available_at": row.available_at,
            "lease_owner": row.lease_owner,
            "lease_expires_at": row.lease_expires_at,
            "heartbeat_at": row.heartbeat_at,
            "cancel_requested": row.cancel_requested,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "last_error": row.last_error,
            "created_by": row.created_by,
        }
    else:
        mapping = dict(row)
        data = {
            "id": mapping["id"],
            "organization_id": mapping["organization_id"],
            "job_type": mapping["job_type"],
            "status": mapping["status"],
            "payload": dict(mapping.get("payload") or {}),
            "result": None if mapping.get("result") is None else dict(mapping["result"]),
            "dedupe_key": mapping.get("dedupe_key"),
            "attempt_count": mapping["attempt_count"],
            "max_attempts": mapping["max_attempts"],
            "available_at": mapping["available_at"],
            "lease_owner": mapping.get("lease_owner"),
            "lease_expires_at": mapping.get("lease_expires_at"),
            "heartbeat_at": mapping.get("heartbeat_at"),
            "cancel_requested": mapping["cancel_requested"],
            "created_at": mapping["created_at"],
            "started_at": mapping.get("started_at"),
            "finished_at": mapping.get("finished_at"),
            "last_error": mapping.get("last_error"),
            "created_by": mapping.get("created_by"),
        }
    data["status"] = JobStatus(data["status"])
    return Job.model_validate(data)


async def bind_organization(session: AsyncSession, organization_id: UUID) -> None:
    """Set transaction-local ``app.organization_id`` for forced RLS."""
    await session.execute(
        text("SELECT set_config('app.organization_id', :org, true)"),
        {"org": str(organization_id)},
    )


class PostgresJobQueue:
    """Durable job queue backed by the ``jobs`` table."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        organization_id: UUID | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._organization_id = organization_id

    def for_organization(self, organization_id: UUID) -> PostgresJobQueue:
        """Return a queue bound to ``organization_id`` for RLS-scoped ops."""
        return PostgresJobQueue(
            self._session_factory,
            organization_id=organization_id,
        )

    async def _prepare_session(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID | None = None,
    ) -> None:
        org = organization_id if organization_id is not None else self._organization_id
        if org is not None:
            await bind_organization(session, org)

    async def enqueue(
        self,
        organization_id: UUID,
        job_type: str,
        payload: dict,
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
        created_by: UUID | None = None,
    ) -> Job:
        async with self._session_factory() as session:
            await self._prepare_session(session, organization_id=organization_id)
            job_id = uuid4()
            now = _utcnow()
            row = JobRow(
                id=job_id,
                organization_id=organization_id,
                job_type=job_type,
                status=JobStatus.queued.value,
                payload=dict(payload),
                result=None,
                dedupe_key=dedupe_key,
                attempt_count=0,
                max_attempts=max_attempts,
                available_at=available_at if available_at is not None else now,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=None,
                cancel_requested=False,
                created_at=now,
                started_at=None,
                finished_at=None,
                last_error=None,
                created_by=created_by,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if dedupe_key is None or not _integrity_is_unique(exc):
                    raise
                await self._prepare_session(session, organization_id=organization_id)
                existing = await session.execute(
                    text(
                        """
                        SELECT *
                          FROM jobs
                         WHERE organization_id = :org_id
                           AND job_type = :job_type
                           AND dedupe_key = :dedupe_key
                           AND status IN ('queued', 'running')
                         LIMIT 1
                        """
                    ),
                    {
                        "org_id": organization_id,
                        "job_type": job_type,
                        "dedupe_key": dedupe_key,
                    },
                )
                found = existing.mappings().first()
                if found is None:
                    raise
                return _row_to_job(found)
            await session.refresh(row)
            return _row_to_job(row)

    async def reap_expired_leases(self) -> list[Job]:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            changed = await self._reap_expired_leases(session)
            await session.commit()
            return changed

    async def _reap_expired_leases(self, session: AsyncSession) -> list[Job]:
        """Reap expired running leases (cancel → cancelled; else requeue/dead-letter)."""
        changed: list[Job] = []

        cancelled = await session.execute(
            text(
                """
                UPDATE jobs
                   SET status = 'cancelled',
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL,
                       finished_at = now()
                 WHERE status = 'running'
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < now()
                   AND cancel_requested = true
                RETURNING *
                """
            )
        )
        changed.extend(_row_to_job(r) for r in cancelled.mappings().all())

        requeued = await session.execute(
            text(
                """
                UPDATE jobs
                   SET status = 'queued',
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL,
                       available_at = now()
                 WHERE status = 'running'
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < now()
                   AND cancel_requested = false
                   AND attempt_count < max_attempts
                RETURNING *
                """
            )
        )
        changed.extend(_row_to_job(r) for r in requeued.mappings().all())

        dead = await session.execute(
            text(
                """
                UPDATE jobs
                   SET status = 'dead_letter',
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL,
                       finished_at = now(),
                       last_error = COALESCE(last_error, 'lease expired')
                 WHERE status = 'running'
                   AND lease_expires_at IS NOT NULL
                   AND lease_expires_at < now()
                   AND cancel_requested = false
                   AND attempt_count >= max_attempts
                RETURNING *
                """
            )
        )
        changed.extend(_row_to_job(r) for r in dead.mappings().all())
        return changed

    async def _cancel_queued_cancel_requested(self, session: AsyncSession) -> None:
        """Safety net: queued + cancel_requested → cancelled (ADR §2 / memory.py)."""
        await session.execute(
            text(
                """
                UPDATE jobs
                   SET status = 'cancelled',
                       finished_at = COALESCE(finished_at, now()),
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL
                 WHERE status = 'queued'
                   AND cancel_requested = true
                """
            )
        )

    async def claim(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
        lease_seconds: int = 60,
    ) -> Job | None:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            await self._reap_expired_leases(session)
            await self._cancel_queued_cancel_requested(session)

            type_filter = ""
            params: dict[str, Any] = {
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            }
            if job_types is not None:
                type_filter = "AND job_type = ANY(CAST(:job_types AS text[]))"
                params["job_types"] = job_types

            result = await session.execute(
                text(
                    f"""
                    UPDATE jobs AS j
                       SET status = 'running',
                           attempt_count = j.attempt_count + 1,
                           lease_owner = :worker_id,
                           lease_expires_at = now()
                               + (:lease_seconds * interval '1 second'),
                           heartbeat_at = now(),
                           started_at = now(),
                           last_error = NULL
                     WHERE j.id = (
                        SELECT id
                          FROM jobs
                         WHERE status = 'queued'
                           AND available_at <= now()
                           AND cancel_requested = false
                           {type_filter}
                         ORDER BY available_at ASC, created_at ASC
                         FOR UPDATE SKIP LOCKED
                         LIMIT 1
                     )
                    RETURNING j.*
                    """
                ),
                params,
            )
            row = result.mappings().first()
            await session.commit()
            if row is None:
                return None
            return _row_to_job(row)

    async def _require(self, session: AsyncSession, job_id: UUID) -> Any:
        result = await session.execute(
            text("SELECT * FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        )
        row = result.mappings().first()
        if row is None:
            raise JobNotFound(
                "job not found",
                details={"job_id": str(job_id)},
            )
        return row

    def _require_lease_row(self, row: Any, job_id: UUID, worker_id: str) -> None:
        if row["status"] != JobStatus.running.value or row["lease_owner"] != worker_id:
            raise LeaseLost(
                "lease not held by worker",
                details={
                    "job_id": str(job_id),
                    "worker_id": worker_id,
                    "status": str(row["status"]),
                    "lease_owner": row["lease_owner"],
                },
            )

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Job:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            row = await self._require(session, job_id)
            self._require_lease_row(row, job_id, worker_id)
            if row["cancel_requested"]:
                raise JobCancelled(
                    "cancel requested; worker should acknowledge_cancel",
                    details={"job_id": str(job_id)},
                )
            result = await session.execute(
                text(
                    """
                    UPDATE jobs
                       SET heartbeat_at = now(),
                           lease_expires_at = now()
                               + (:lease_seconds * interval '1 second')
                     WHERE id = :job_id
                       AND status = 'running'
                       AND lease_owner = :worker_id
                       AND cancel_requested = false
                    RETURNING *
                    """
                ),
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "lease_seconds": lease_seconds,
                },
            )
            updated = result.mappings().first()
            if updated is None:
                raise LeaseLost(
                    "lease not held by worker",
                    details={
                        "job_id": str(job_id),
                        "worker_id": worker_id,
                    },
                )
            await session.commit()
            return _row_to_job(updated)

    async def complete(
        self,
        job_id: UUID,
        worker_id: str,
        result: dict | None = None,
    ) -> Job:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            row = await self._require(session, job_id)
            self._require_lease_row(row, job_id, worker_id)
            if row["cancel_requested"]:
                raise JobCancelled(
                    "cancel requested; worker should acknowledge_cancel",
                    details={"job_id": str(job_id)},
                )
            updated = await session.execute(
                text(
                    """
                    UPDATE jobs
                       SET status = 'succeeded',
                           result = CAST(:result AS jsonb),
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           heartbeat_at = NULL,
                           finished_at = now()
                     WHERE id = :job_id
                       AND status = 'running'
                       AND lease_owner = :worker_id
                       AND cancel_requested = false
                    RETURNING *
                    """
                ),
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "result": None if result is None else json.dumps(result),
                },
            )
            out = updated.mappings().first()
            if out is None:
                raise LeaseLost(
                    "lease not held by worker",
                    details={"job_id": str(job_id), "worker_id": worker_id},
                )
            await session.commit()
            return _row_to_job(out)

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        error: str,
        *,
        retryable: bool = True,
    ) -> Job:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            row = await self._require(session, job_id)
            self._require_lease_row(row, job_id, worker_id)
            if row["cancel_requested"]:
                raise JobCancelled(
                    "cancel requested; worker should acknowledge_cancel",
                    details={"job_id": str(job_id)},
                )

            attempt_count = int(row["attempt_count"])
            max_attempts = int(row["max_attempts"])
            if retryable and attempt_count < max_attempts:
                delay = 2 ** min(attempt_count, 8)
                updated = await session.execute(
                    text(
                        """
                        UPDATE jobs
                           SET status = 'queued',
                               last_error = :error,
                               lease_owner = NULL,
                               lease_expires_at = NULL,
                               heartbeat_at = NULL,
                               available_at = now()
                                   + (:delay * interval '1 second'),
                               finished_at = NULL
                         WHERE id = :job_id
                           AND status = 'running'
                           AND lease_owner = :worker_id
                           AND cancel_requested = false
                        RETURNING *
                        """
                    ),
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "error": error,
                        "delay": delay,
                    },
                )
            else:
                updated = await session.execute(
                    text(
                        """
                        UPDATE jobs
                           SET status = 'dead_letter',
                               last_error = :error,
                               lease_owner = NULL,
                               lease_expires_at = NULL,
                               heartbeat_at = NULL,
                               finished_at = now()
                         WHERE id = :job_id
                           AND status = 'running'
                           AND lease_owner = :worker_id
                           AND cancel_requested = false
                        RETURNING *
                        """
                    ),
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "error": error,
                    },
                )
            out = updated.mappings().first()
            if out is None:
                raise LeaseLost(
                    "lease not held by worker",
                    details={"job_id": str(job_id), "worker_id": worker_id},
                )
            await session.commit()
            return _row_to_job(out)

    async def cancel(self, job_id: UUID) -> Job:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            row = await self._require(session, job_id)
            status = JobStatus(row["status"])
            if status in TERMINAL_STATUSES:
                raise JobAlreadyTerminal(
                    "job is already terminal",
                    details={
                        "job_id": str(job_id),
                        "status": str(status),
                    },
                )
            if status == JobStatus.queued:
                updated = await session.execute(
                    text(
                        """
                        UPDATE jobs
                           SET status = 'cancelled',
                               cancel_requested = true,
                               finished_at = now(),
                               lease_owner = NULL,
                               lease_expires_at = NULL,
                               heartbeat_at = NULL
                         WHERE id = :job_id
                        RETURNING *
                        """
                    ),
                    {"job_id": job_id},
                )
            else:
                # running (or unexpected non-terminal): cooperative flag
                updated = await session.execute(
                    text(
                        """
                        UPDATE jobs
                           SET cancel_requested = true
                         WHERE id = :job_id
                        RETURNING *
                        """
                    ),
                    {"job_id": job_id},
                )
            out = updated.mappings().first()
            assert out is not None
            await session.commit()
            return _row_to_job(out)

    async def acknowledge_cancel(self, job_id: UUID, worker_id: str) -> Job:
        async with self._session_factory() as session:
            await self._prepare_session(session)
            row = await self._require(session, job_id)
            self._require_lease_row(row, job_id, worker_id)
            if not row["cancel_requested"]:
                raise LeaseLost(
                    "cancel was not requested for this running job",
                    details={"job_id": str(job_id)},
                )
            updated = await session.execute(
                text(
                    """
                    UPDATE jobs
                       SET status = 'cancelled',
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           heartbeat_at = NULL,
                           finished_at = now()
                     WHERE id = :job_id
                       AND status = 'running'
                       AND lease_owner = :worker_id
                       AND cancel_requested = true
                    RETURNING *
                    """
                ),
                {"job_id": job_id, "worker_id": worker_id},
            )
            out = updated.mappings().first()
            if out is None:
                raise LeaseLost(
                    "lease not held by worker",
                    details={"job_id": str(job_id), "worker_id": worker_id},
                )
            await session.commit()
            return _row_to_job(out)
