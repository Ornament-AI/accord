"""Worker job handlers and the process-wide handler registry (ADR 0010).

Extension seam
--------------
Built-in handlers are registered onto the module-level :data:`registry` at
import time via :func:`register_handlers`: ``noop``, ``generate_report``, and
``consolidated_xlsx``. Future lanes, including storage maintenance, should add
their handlers in one of two ways:

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

``generate_report`` DI seam
---------------------------
:func:`handle_generate_report` needs object storage + a :class:`ReportRegistry`
that the worker process does not open itself. Call
:func:`configure_generate_report` at process startup (orchestrator / worker
entrypoint / tests) before claiming ``generate_report`` jobs::

    from app.jobs.handlers import configure_generate_report, register_handlers

    configure_generate_report(storage=object_storage, registry=report_registry)
    register_handlers(handler_registry)

``current_job_session`` / :func:`bind_job_session` remain the only session
wiring; do not edit ``worker.py`` for this lane.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Iterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.protocol import Job, JobHandlerRegistry

if TYPE_CHECKING:
    from app.reports.base import ReportRegistry
    from app.storage.protocol import ObjectStorage

_job_session: ContextVar[AsyncSession | None] = ContextVar(
    "accord_job_session",
    default=None,
)

_generate_report_storage: ObjectStorage | None = None
_generate_report_registry: ReportRegistry | None = None
_generate_report_engine_version: str | None = None

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


def configure_generate_report(
    *,
    storage: ObjectStorage,
    registry: ReportRegistry,
    engine_version: str | None = None,
) -> None:
    """Configure storage + report registry for :func:`handle_generate_report`.

    Call once at worker/API process startup (or in tests). Raises are deferred
    until a ``generate_report`` job is handled so noop workers stay lightweight.
    """
    global _generate_report_storage, _generate_report_registry, _generate_report_engine_version
    _generate_report_storage = storage
    _generate_report_registry = registry
    _generate_report_engine_version = engine_version


def _require_generate_report_deps() -> tuple[ObjectStorage, ReportRegistry, str | None]:
    if _generate_report_storage is None or _generate_report_registry is None:
        raise RuntimeError(
            "generate_report handler is not configured; call "
            "configure_generate_report(storage=..., registry=...) at startup"
        )
    return (
        _generate_report_storage,
        _generate_report_registry,
        _generate_report_engine_version,
    )


async def handle_noop(job: Job) -> dict | None:
    """Demo no-op handler — acknowledges the job with a small result payload."""
    return {"ok": True, "job_type": job.job_type, "job_id": str(job.id)}


async def handle_generate_report(job: Job) -> dict[str, Any] | None:
    """Build and persist a report artifact for a ``generate_report`` job."""
    from app.services.report_generation import (
        DEFAULT_ENGINE_VERSION,
        execute_generate_report,
    )

    session = current_job_session()
    storage, report_registry, engine_version = _require_generate_report_deps()
    return await execute_generate_report(
        session,
        storage,
        job,
        registry=report_registry,
        engine_version=engine_version or DEFAULT_ENGINE_VERSION,
    )


async def handle_consolidated_xlsx(job: Job) -> dict[str, Any] | None:
    """Build the v3 workbook or explicit legacy v2 ZIP for a consolidated job."""
    from app.services.report_generation import (
        DEFAULT_ENGINE_VERSION,
        execute_consolidated_xlsx,
    )

    session = current_job_session()
    storage, report_registry, engine_version = _require_generate_report_deps()
    return await execute_consolidated_xlsx(
        session,
        storage,
        job,
        registry=report_registry,
        engine_version=engine_version or DEFAULT_ENGINE_VERSION,
    )


# --- artifacts.maintenance --------------------------------------------------
#
# One scheduled job per org per hour (dedupe bucket ``<date>T<HH>``) reconciles
# stuck ``pending`` artifact rows against object storage and expires artifacts
# past retention (M-data-12). Enqueueing is status-agnostic — a succeeded job
# for the current hour also suppresses re-enqueue, so a fast cycle cannot run
# maintenance twice in the same hour.


def artifact_maintenance_configured() -> bool:
    """True when object storage is configured (maintenance is a no-op without it)."""
    return _generate_report_storage is not None


def _maintenance_dedupe_key(now: Any) -> str:
    return f"artifacts.maintenance:{now.strftime('%Y-%m-%dT%H')}"


async def maybe_enqueue_maintenance(
    session: AsyncSession,
    queue: Any,
    organization_id: Any,
) -> bool:
    """Enqueue this org's hourly ``artifacts.maintenance`` job if absent.

    ``session`` must already be tenant-bound (``bind_tenant_context``); it is
    used only for the existence check. ``queue`` performs the enqueue on its
    own session. Returns True when a job was enqueued.
    """
    import sqlalchemy as sa

    from app.models.platform import Job as JobRow

    from datetime import UTC, datetime

    dedupe_key = _maintenance_dedupe_key(datetime.now(UTC))
    exists = await session.execute(
        sa.select(JobRow.id).where(
            JobRow.organization_id == organization_id,
            JobRow.job_type == "artifacts.maintenance",
            JobRow.dedupe_key == dedupe_key,
        )
    )
    if exists.first() is not None:
        return False
    await queue.enqueue(
        organization_id,
        "artifacts.maintenance",
        {},
        dedupe_key=dedupe_key,
        max_attempts=3,
    )
    return True


async def handle_artifact_maintenance(job: Job) -> dict[str, Any] | None:
    """Reconcile orphaned artifacts and expire artifacts past retention."""
    from datetime import UTC, datetime

    from app.services.artifacts import expire_artifacts, reconcile_orphans

    session = current_job_session()
    storage, _registry, _engine_version = _require_generate_report_deps()
    counts = await reconcile_orphans(session, storage, organization_id=job.organization_id)
    expired = await expire_artifacts(
        session, organization_id=job.organization_id, now=datetime.now(UTC)
    )
    return {
        "reconciled": {
            "finalized": counts.finalized,
            "deleted": counts.deleted,
            "checksum_mismatch": counts.checksum_mismatch,
        },
        "expired": expired,
    }


def register_handlers(target: JobHandlerRegistry) -> JobHandlerRegistry:
    """Register built-in worker handlers onto ``target``.

    Safe to call on a fresh registry (tests / alternate entrypoints) or on the
    module-level :data:`registry`. Lane packages should call this (or equivalent)
    then register their own ``job_type`` handlers on the same instance.
    """
    target.register("noop")(handle_noop)
    target.register("generate_report")(handle_generate_report)
    target.register("consolidated_xlsx")(handle_consolidated_xlsx)
    target.register("artifacts.maintenance")(handle_artifact_maintenance)
    return target


register_handlers(registry)
