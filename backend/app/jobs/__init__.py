"""Durable job queue protocol and in-memory test double (ADR 0010 Phase 1)."""

from app.jobs.memory import InMemoryJobQueue
from app.jobs.protocol import (
    Job,
    JobAlreadyTerminal,
    JobCancelled,
    JobHandler,
    JobHandlerRegistry,
    JobNotFound,
    JobQueue,
    JobQueueError,
    JobStatus,
    LeaseLost,
    UnknownJobType,
)

__all__ = [
    "InMemoryJobQueue",
    "Job",
    "JobAlreadyTerminal",
    "JobCancelled",
    "JobHandler",
    "JobHandlerRegistry",
    "JobNotFound",
    "JobQueue",
    "JobQueueError",
    "JobStatus",
    "LeaseLost",
    "UnknownJobType",
]
