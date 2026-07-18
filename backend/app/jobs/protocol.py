"""Durable job queue protocol, models, and handler registry (ADR 0010).

Phase 1 defines contracts and in-memory semantics only. The Postgres-backed
queue (``SELECT … FOR UPDATE SKIP LOCKED``), worker loop, and reaper process
land in Phase 6.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobQueueError(Exception):
    """Base error for job queue operations."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class JobNotFound(JobQueueError):
    """Raised when a job id is unknown to the queue."""


class LeaseLost(JobQueueError):
    """Raised when the caller no longer holds the running lease.

    Typical causes: wrong ``worker_id``, job not ``running``, or lease already
    reaped / completed by another path.
    """


class JobCancelled(JobQueueError):
    """Raised when a heartbeat/checkpoint observes cooperative cancel.

    Per ADR 0010 §2: a zero-row heartbeat (``cancel_requested`` flipped) means
    the worker must stop and finish via ``acknowledge_cancel``.
    """


class JobAlreadyTerminal(JobQueueError):
    """Raised when an operation requires a non-terminal job."""


class UnknownJobType(JobQueueError):
    """Raised when no handler is registered for a ``job_type``."""


class JobStatus(StrEnum):
    """Closed job status set (ADR 0010 §1).

    Note on ``failed``: the ADR closed set includes ``failed`` for transient
    failures. This Phase 1 queue transitions retryable failures directly back
    to ``queued`` (with backoff) or to ``dead_letter``, matching the ADR §2
    fail SQL path. ``failed`` is retained for wire/DB compatibility and is
    not a sticky state produced by ``InMemoryJobQueue``.
    """

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    dead_letter = "dead_letter"
    cancelled = "cancelled"


TERMINAL_STATUSES = frozenset(
    {
        JobStatus.succeeded,
        JobStatus.dead_letter,
        JobStatus.cancelled,
    }
)


class Job(BaseModel):
    """Job row mirror of the ADR 0010 ``jobs`` table (application model)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    job_type: str
    status: JobStatus
    payload: dict = Field(default_factory=dict)
    result: dict | None = None
    dedupe_key: str | None = None
    attempt_count: int = 0
    max_attempts: int = 5
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancel_requested: bool = False
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    created_by: UUID | None = None


JobHandler = Callable[[Job], Awaitable[dict | None]]


class JobHandlerRegistry:
    """Maps ``job_type`` strings to async handler callables."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str) -> Callable[[JobHandler], JobHandler]:
        """Decorator that registers an async ``(job) -> dict | None`` handler."""

        def decorator(handler: JobHandler) -> JobHandler:
            self._handlers[job_type] = handler
            return handler

        return decorator

    def get(self, job_type: str) -> JobHandler:
        """Return the handler for ``job_type``, or raise ``UnknownJobType``."""
        try:
            return self._handlers[job_type]
        except KeyError as exc:
            raise UnknownJobType(
                f"no handler registered for job_type={job_type!r}",
                details={"job_type": job_type},
            ) from exc


@runtime_checkable
class JobQueue(Protocol):
    """Async durable job queue contract (ADR 0010 §§1–3).

    Postgres implementations **must** claim with
    ``SELECT … FOR UPDATE SKIP LOCKED`` (ADR 0010 §2). In-memory doubles only
    need equivalent single-process mutual exclusion around claim mutations.
    """

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
        """Enqueue a job, honoring org-scoped in-flight dedupe.

        If ``dedupe_key`` is set and a job with the same
        ``(organization_id, job_type, dedupe_key)`` already exists in status
        ``queued`` or ``running``, return that existing job (idempotent
        enqueue; mirrors the ADR partial unique index).
        """
        ...

    async def claim(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
        lease_seconds: int = 60,
    ) -> Job | None:
        """Claim the oldest eligible queued job for ``worker_id``.

        Eligibility: ``status=queued``, ``available_at <= now``,
        ``cancel_requested=false``, optionally filtered by ``job_types``.
        Sets ``running``, increments ``attempt_count``, and assigns lease
        fields. Returns ``None`` when nothing is eligible.

        Implementations should reap expired running leases before selecting
        a candidate (see ``reap_expired_leases``).
        """
        ...

    async def heartbeat(
        self,
        job_id: UUID,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Job:
        """Extend the lease for a running job owned by ``worker_id``.

        Raises ``LeaseLost`` if the job is not running or ``lease_owner``
        mismatches. Raises ``JobCancelled`` when ``cancel_requested`` is set
        (cooperative stop — caller should invoke ``acknowledge_cancel``).
        """
        ...

    async def complete(
        self,
        job_id: UUID,
        worker_id: str,
        result: dict | None = None,
    ) -> Job:
        """Mark a running job ``succeeded`` and set ``finished_at``."""
        ...

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        error: str,
        *,
        retryable: bool = True,
    ) -> Job:
        """Record failure with ADR exponential backoff or ``dead_letter``.

        If ``retryable`` and ``attempt_count < max_attempts``: requeue as
        ``queued``, clear lease fields, set
        ``available_at = now + 2**min(attempt_count, 8)`` seconds.
        Otherwise: ``dead_letter`` with ``finished_at`` and ``last_error``.

        Raises ``JobCancelled`` when ``cancel_requested`` is set — the worker
        must finish via ``acknowledge_cancel`` rather than retry/dead-letter.
        """
        ...

    async def cancel(self, job_id: UUID) -> Job:
        """Request cancellation.

        - ``queued`` → ``cancelled`` immediately (terminal).
        - ``running`` → set ``cancel_requested=True`` (cooperative); the
          worker must later call ``acknowledge_cancel`` to finish as
          ``cancelled``.
        - Terminal jobs → raise ``JobAlreadyTerminal``.
        """
        ...

    async def acknowledge_cancel(self, job_id: UUID, worker_id: str) -> Job:
        """Finish cooperative cancel for a running job owned by ``worker_id``.

        Transitions ``running`` + ``cancel_requested`` → ``cancelled`` with
        ``finished_at`` set. Raises ``LeaseLost`` / ``JobNotFound`` when the
        caller is not the lease owner of a cancellable running job.
        """
        ...

    async def reap_expired_leases(self) -> list[Job]:
        """Requeue or dead-letter running jobs whose lease has expired.

        ADR 0010 §3: ``running`` with ``lease_expires_at < now()`` →
        ``queued`` (clear lease) if ``attempt_count < max_attempts``, else
        ``dead_letter``. ``claim`` should invoke this opportunistically.
        """
        ...
