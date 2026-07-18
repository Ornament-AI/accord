"""Worker job handlers and the process-wide handler registry (ADR 0010).

Extension seam
--------------
Built-in handlers are registered onto the module-level :data:`registry` at
import time via :func:`register_handlers`. Future lanes (artifact generation,
report jobs, storage maintenance) should add their handlers in one of two ways:

1. **Compose at startup** — create or reuse a ``JobHandlerRegistry``, call
   ``register_handlers(registry)`` for the built-ins, then register lane-specific
   handlers with ``registry.register("export.generate")(handler)`` (or the
   decorator form) before constructing :class:`~app.jobs.worker.WorkerLoop`.
2. **Decorate the shared registry** — import :data:`registry` from this module
   and decorate handlers with ``@registry.register("your.job_type")``.

Handlers keep the protocol signature ``async (job) -> dict | None``. When a
handler needs a database session under the claimed job's tenant GUC, call
:func:`current_job_session` — :class:`~app.jobs.worker.WorkerLoop` binds an
org-scoped ``AsyncSession`` into a contextvar for the duration of the
invocation (see that class for the commit-before-complete ordering).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.protocol import Job, JobHandlerRegistry

_job_session: ContextVar[AsyncSession | None] = ContextVar(
    "accord_job_session",
    default=None,
)

registry = JobHandlerRegistry()


def current_job_session() -> AsyncSession:
    """Return the org-bound session for the currently executing job handler.

    Raises ``RuntimeError`` when called outside a ``WorkerLoop`` handler
    invocation (no session bound).
    """
    session = _job_session.get()
    if session is None:
        raise RuntimeError("current_job_session() called outside a WorkerLoop handler invocation")
    return session


def _set_job_session(session: AsyncSession | None) -> Token[AsyncSession | None]:
    return _job_session.set(session)


def _reset_job_session(token: Token[AsyncSession | None]) -> None:
    _job_session.reset(token)


@contextmanager
def bind_job_session(session: AsyncSession) -> Iterator[AsyncSession]:
    """Bind ``session`` as :func:`current_job_session` for a handler call."""
    token = _set_job_session(session)
    try:
        yield session
    finally:
        _reset_job_session(token)


async def handle_noop(job: Job) -> dict | None:
    """Demo no-op handler — acknowledges the job with a small result payload."""
    return {"ok": True, "job_type": job.job_type, "job_id": str(job.id)}


def register_handlers(target: JobHandlerRegistry) -> JobHandlerRegistry:
    """Register built-in worker handlers onto ``target``.

    Safe to call on a fresh registry (tests / alternate entrypoints) or on the
    module-level :data:`registry`. Lane packages should call this (or equivalent)
    then register their own ``job_type`` handlers on the same instance.
    """
    target.register("noop")(handle_noop)
    return target


register_handlers(registry)
