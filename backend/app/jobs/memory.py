"""In-memory ``JobQueue`` test double (ADR 0010 Phase 1).

Honors the ADR status machine, org-scoped dedupe, lease heartbeat, exponential
backoff, cooperative cancel, and lease reaping. Concurrent async callers are
serialized with an ``asyncio.Lock``. An injectable clock supports lease/backoff
tests without real sleeps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.jobs.protocol import (
    TERMINAL_STATUSES,
    Job,
    JobAlreadyTerminal,
    JobCancelled,
    JobNotFound,
    JobStatus,
    LeaseLost,
)


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryJobQueue:
    """Process-local job queue implementing ``JobQueue`` semantics."""

    def __init__(
        self,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._jobs: dict[UUID, Job] = {}
        self._lock = asyncio.Lock()
        self._now = now_fn or _default_now

    def _copy(self, job: Job) -> Job:
        return job.model_copy(deep=True)

    def _require(self, job_id: UUID) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(
                "job not found",
                details={"job_id": str(job_id)},
            )
        return job

    def _require_lease(self, job_id: UUID, worker_id: str) -> Job:
        job = self._require(job_id)
        if job.status != JobStatus.running or job.lease_owner != worker_id:
            raise LeaseLost(
                "lease not held by worker",
                details={
                    "job_id": str(job_id),
                    "worker_id": worker_id,
                    "status": str(job.status),
                    "lease_owner": job.lease_owner,
                },
            )
        return job

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
        async with self._lock:
            if dedupe_key is not None:
                for existing in self._jobs.values():
                    if (
                        existing.organization_id == organization_id
                        and existing.job_type == job_type
                        and existing.dedupe_key == dedupe_key
                        and existing.status in (JobStatus.queued, JobStatus.running)
                    ):
                        return self._copy(existing)

            now = self._now()
            job = Job(
                id=uuid4(),
                organization_id=organization_id,
                job_type=job_type,
                status=JobStatus.queued,
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
            self._jobs[job.id] = job
            return self._copy(job)

    async def reap_expired_leases(self) -> list[Job]:
        """Public reaper; also invoked at the start of ``claim``."""
        async with self._lock:
            return [self._copy(j) for j in self._reap_expired_leases_locked()]

    def _reap_expired_leases_locked(self) -> list[Job]:
        now = self._now()
        changed: list[Job] = []
        for job in list(self._jobs.values()):
            if job.status != JobStatus.running:
                continue
            if job.lease_expires_at is None or job.lease_expires_at >= now:
                continue
            # ADR §2: queued + cancel_requested → cancelled immediately.
            # Never requeue a cancel-flagged job into an unclaimable limbo.
            if job.cancel_requested:
                updated = job.model_copy(
                    update={
                        "status": JobStatus.cancelled,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "finished_at": now,
                    }
                )
            elif job.attempt_count < job.max_attempts:
                updated = job.model_copy(
                    update={
                        "status": JobStatus.queued,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "available_at": now,
                    }
                )
            else:
                updated = job.model_copy(
                    update={
                        "status": JobStatus.dead_letter,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "finished_at": now,
                        "last_error": job.last_error or "lease expired",
                    }
                )
            self._jobs[job.id] = updated
            changed.append(updated)
        return changed

    async def claim(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
        lease_seconds: int = 60,
    ) -> Job | None:
        """Claim oldest eligible job.

        Postgres implementations MUST use
        ``SELECT … FOR UPDATE SKIP LOCKED`` (ADR 0010 §2). This in-memory
        double uses an ``asyncio.Lock`` so concurrent claimers never
        double-claim within a single process.
        """
        async with self._lock:
            self._reap_expired_leases_locked()
            now = self._now()
            # ADR §2 safety net: queued + cancel_requested → cancelled.
            for job in list(self._jobs.values()):
                if job.status == JobStatus.queued and job.cancel_requested:
                    self._jobs[job.id] = job.model_copy(
                        update={
                            "status": JobStatus.cancelled,
                            "finished_at": job.finished_at or now,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "heartbeat_at": None,
                        }
                    )
            candidates = [
                j
                for j in self._jobs.values()
                if j.status == JobStatus.queued
                and j.available_at <= now
                and not j.cancel_requested
                and (job_types is None or j.job_type in job_types)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda j: (j.available_at, j.created_at, str(j.id)))
            job = candidates[0]
            lease_expires = now + timedelta(seconds=lease_seconds)
            updated = job.model_copy(
                update={
                    "status": JobStatus.running,
                    "attempt_count": job.attempt_count + 1,
                    "lease_owner": worker_id,
                    "lease_expires_at": lease_expires,
                    "heartbeat_at": now,
                    "started_at": now,
                    "last_error": None,
                }
            )
            self._jobs[job.id] = updated
            return self._copy(updated)

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Job:
        async with self._lock:
            job = self._require_lease(job_id, worker_id)
            if job.cancel_requested:
                raise JobCancelled(
                    "cancel requested; worker should acknowledge_cancel",
                    details={"job_id": str(job_id)},
                )
            now = self._now()
            updated = job.model_copy(
                update={
                    "heartbeat_at": now,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                }
            )
            self._jobs[job_id] = updated
            return self._copy(updated)

    async def complete(
        self,
        job_id: UUID,
        worker_id: str,
        result: dict | None = None,
    ) -> Job:
        async with self._lock:
            job = self._require_lease(job_id, worker_id)
            if job.cancel_requested:
                raise JobCancelled(
                    "cancel requested; worker should acknowledge_cancel",
                    details={"job_id": str(job_id)},
                )
            now = self._now()
            updated = job.model_copy(
                update={
                    "status": JobStatus.succeeded,
                    "result": None if result is None else dict(result),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                    "finished_at": now,
                }
            )
            self._jobs[job_id] = updated
            return self._copy(updated)

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        error: str,
        *,
        retryable: bool = True,
    ) -> Job:
        async with self._lock:
            job = self._require_lease(job_id, worker_id)
            if job.cancel_requested:
                raise JobCancelled(
                    "cancel requested; worker should acknowledge_cancel",
                    details={"job_id": str(job_id)},
                )
            now = self._now()
            if retryable and job.attempt_count < job.max_attempts:
                delay = timedelta(seconds=2 ** min(job.attempt_count, 8))
                updated = job.model_copy(
                    update={
                        "status": JobStatus.queued,
                        "last_error": error,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "available_at": now + delay,
                        "finished_at": None,
                    }
                )
            else:
                updated = job.model_copy(
                    update={
                        "status": JobStatus.dead_letter,
                        "last_error": error,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                        "finished_at": now,
                    }
                )
            self._jobs[job_id] = updated
            return self._copy(updated)

    async def cancel(self, job_id: UUID) -> Job:
        async with self._lock:
            job = self._require(job_id)
            if job.status in TERMINAL_STATUSES:
                raise JobAlreadyTerminal(
                    "job is already terminal",
                    details={
                        "job_id": str(job_id),
                        "status": str(job.status),
                    },
                )
            now = self._now()
            if job.status == JobStatus.queued:
                updated = job.model_copy(
                    update={
                        "status": JobStatus.cancelled,
                        "cancel_requested": True,
                        "finished_at": now,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "heartbeat_at": None,
                    }
                )
            elif job.status == JobStatus.running:
                updated = job.model_copy(update={"cancel_requested": True})
            else:
                # ``failed`` is in the closed set but not used as a sticky
                # state by this queue; treat unexpected non-terminal oddly.
                updated = job.model_copy(update={"cancel_requested": True})
            self._jobs[job_id] = updated
            return self._copy(updated)

    async def acknowledge_cancel(self, job_id: UUID, worker_id: str) -> Job:
        """Complete cooperative cancel: running + cancel_requested → cancelled."""
        async with self._lock:
            job = self._require_lease(job_id, worker_id)
            if not job.cancel_requested:
                raise LeaseLost(
                    "cancel was not requested for this running job",
                    details={"job_id": str(job_id)},
                )
            now = self._now()
            updated = job.model_copy(
                update={
                    "status": JobStatus.cancelled,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                    "finished_at": now,
                }
            )
            self._jobs[job_id] = updated
            return self._copy(updated)
