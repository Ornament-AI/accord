"""Report generation request + job execution (ADR 0010).

Request path
------------
``request_report`` validates the report type / posted run / format, then
enqueues ``job_type='generate_report'`` with org-scoped in-flight dedupe on
``{report_type}:{posted_run_id}:{format}:{template_version}``.

Execution path
--------------
``execute_generate_report`` is the handler body. Before regenerating it looks
for an existing **finalized** ``ExportArtifact`` for
``(organization_id, report_type, posted_run_id, template_version)`` whose
``content_type`` matches the requested format. If found, it returns
``{'artifact_id': ..., 'reused': True}`` without rebuilding or re-uploading
(artifact-level idempotency after the job has already succeeded once).

Template version
----------------
``ReportRegistry`` registrations do not carry a default template version today
(only ``filename_pattern`` / ``content_types``). Callers may pass
``template_version``; when omitted we default to :data:`DEFAULT_TEMPLATE_VERSION`
(``\"v1\"``). Family lanes can override per request once they version templates.

Listing
-------
:func:`list_registered_reports` iterates ``registry._entries`` (private) because
``ReportRegistry`` has no public iterator yet — do not widen ``base.py`` here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.jobs.protocol import Job, JobQueue
from app.models.payroll_runs import PayrollRun
from app.models.platform import ExportArtifact
from app.models.platform import Job as JobRow
from app.reports.base import ReportContext, ReportDTO, ReportRegistration, ReportRegistry
from app.services.artifacts import create_artifact
from app.storage.protocol import ObjectStorage

DEFAULT_TEMPLATE_VERSION = "v1"
DEFAULT_ENGINE_VERSION = "0.1.0"

SUPPORTED_FORMATS = frozenset({"excel", "pdf", "json"})
JOB_TYPE_GENERATE_REPORT = "generate_report"


class ReportTypeNotFoundError(NotFoundError):
    error_code = "report_type_not_found"

    def __init__(self, message: str = "Report type not found."):
        super().__init__(message)


class PostedRunNotFoundError(NotFoundError):
    error_code = "posted_run_not_found"

    def __init__(self, message: str = "Payroll run not found."):
        super().__init__(message)


class RunNotPostedError(ConflictError):
    error_code = "run_not_posted"

    def __init__(self, message: str = "Payroll run must be posted before generating reports."):
        super().__init__(message)


class UnsupportedReportFormatError(ValidationError):
    error_code = "unsupported_report_format"

    def __init__(self, message: str = "Unsupported report format."):
        super().__init__(message)


class ReportJobNotFoundError(NotFoundError):
    error_code = "report_job_not_found"

    def __init__(self, message: str = "Report job not found."):
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RegisteredReportInfo:
    """Public listing row for one registered report type."""

    report_type: str
    formats: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportJobInfo:
    """Org-scoped job status for the reports API."""

    job_id: UUID
    status: str
    result: dict[str, Any] | None
    last_error: str | None


def list_registered_reports(registry: ReportRegistry) -> list[RegisteredReportInfo]:
    """List registered report types and supported format keys.

    Accesses ``registry._entries`` deliberately — ``ReportRegistry`` has no
    public iteration API yet (see module docstring).
    """
    # Private access: ReportRegistry._entries until a public iterator lands.
    entries = registry._entries  # noqa: SLF001
    items: list[RegisteredReportInfo] = []
    for report_type, registration in sorted(entries.items()):
        formats = tuple(sorted(registration.formatters.content_types.keys()))
        items.append(RegisteredReportInfo(report_type=report_type, formats=formats))
    return items


async def _require_posted_run(
    session: AsyncSession,
    *,
    organization_id: UUID,
    posted_run_id: UUID,
) -> PayrollRun:
    run = await session.get(PayrollRun, posted_run_id)
    if run is None or run.organization_id != organization_id:
        raise PostedRunNotFoundError()
    if run.status != "posted":
        raise RunNotPostedError()
    return run


def _resolve_template_version(template_version: str | None) -> str:
    if template_version is None or not template_version.strip():
        return DEFAULT_TEMPLATE_VERSION
    return template_version


def _dedupe_key(
    *,
    report_type: str,
    posted_run_id: UUID,
    format: str,
    template_version: str,
) -> str:
    return f"{report_type}:{posted_run_id}:{format}:{template_version}"


async def request_report(
    session: AsyncSession,
    queue: JobQueue,
    *,
    organization_id: UUID,
    report_type: str,
    posted_run_id: UUID,
    format: str,
    requested_by: UUID,
    registry: ReportRegistry,
    template_version: str | None = None,
) -> Job:
    """Validate and enqueue a ``generate_report`` job (in-flight dedupe)."""
    if report_type not in registry:
        raise ReportTypeNotFoundError(f"Unknown report type: {report_type!r}.")

    registration = registry.get(report_type)
    if format not in SUPPORTED_FORMATS or format not in registration.formatters.content_types:
        raise UnsupportedReportFormatError(
            f"Format {format!r} is not supported for report type {report_type!r}."
        )

    await _require_posted_run(
        session,
        organization_id=organization_id,
        posted_run_id=posted_run_id,
    )

    resolved_version = _resolve_template_version(template_version)
    payload = {
        "report_type": report_type,
        "posted_run_id": str(posted_run_id),
        "format": format,
        "template_version": resolved_version,
        "requested_by": str(requested_by),
    }
    return await queue.enqueue(
        organization_id,
        JOB_TYPE_GENERATE_REPORT,
        payload,
        dedupe_key=_dedupe_key(
            report_type=report_type,
            posted_run_id=posted_run_id,
            format=format,
            template_version=resolved_version,
        ),
        created_by=requested_by,
    )


async def _find_reusable_artifact(
    session: AsyncSession,
    *,
    organization_id: UUID,
    report_type: str,
    posted_run_id: UUID,
    template_version: str,
    content_type: str,
) -> ExportArtifact | None:
    stmt = sa.select(ExportArtifact).where(
        ExportArtifact.organization_id == organization_id,
        ExportArtifact.report_type == report_type,
        ExportArtifact.posted_run_id == posted_run_id,
        ExportArtifact.template_version == template_version,
        ExportArtifact.content_type == content_type,
        ExportArtifact.status == "finalized",
    )
    return (await session.execute(stmt)).scalars().first()


def _render_content(
    registration: ReportRegistration,
    dto: ReportDTO,
    *,
    format: str,
) -> tuple[bytes, str]:
    formatters = registration.formatters
    content_type = formatters.content_types[format]
    if format == "json":
        payload = formatters.to_json(dto)
        return json.dumps(payload, separators=(",", ":")).encode("utf-8"), content_type
    if format == "excel":
        return formatters.to_excel(dto), content_type
    if format == "pdf":
        return formatters.to_pdf(dto), content_type
    raise UnsupportedReportFormatError(f"Format {format!r} is not supported.")


async def execute_generate_report(
    session: AsyncSession,
    storage: ObjectStorage,
    job: Job,
    *,
    registry: ReportRegistry,
    engine_version: str = DEFAULT_ENGINE_VERSION,
) -> dict[str, Any]:
    """Build, format, and persist a report artifact for a ``generate_report`` job.

    Idempotency: if a finalized artifact already exists for the same
    ``(organization_id, report_type, posted_run_id, template_version)`` and
    matching ``content_type``, return that artifact id with ``reused=True``
    and skip regeneration.
    """
    payload = job.payload
    report_type = str(payload["report_type"])
    posted_run_id = UUID(str(payload["posted_run_id"]))
    format_name = str(payload["format"])
    template_version = str(payload.get("template_version") or DEFAULT_TEMPLATE_VERSION)
    requested_by = UUID(str(payload["requested_by"]))
    organization_id = job.organization_id

    if report_type not in registry:
        raise ReportTypeNotFoundError(f"Unknown report type: {report_type!r}.")
    registration = registry.get(report_type)
    if format_name not in registration.formatters.content_types:
        raise UnsupportedReportFormatError(
            f"Format {format_name!r} is not supported for report type {report_type!r}."
        )
    content_type = registration.formatters.content_types[format_name]

    existing = await _find_reusable_artifact(
        session,
        organization_id=organization_id,
        report_type=report_type,
        posted_run_id=posted_run_id,
        template_version=template_version,
        content_type=content_type,
    )
    if existing is not None:
        return {"artifact_id": str(existing.id), "reused": True}

    await _require_posted_run(
        session,
        organization_id=organization_id,
        posted_run_id=posted_run_id,
    )

    ctx = ReportContext(
        organization_id=organization_id,
        posted_run_id=posted_run_id,
        template_version=template_version,
        generated_at=datetime.now(timezone.utc),
        engine_version=engine_version,
    )
    dto = await registration.builder.build(session, ctx)
    content, content_type = _render_content(registration, dto, format=format_name)

    artifact = await create_artifact(
        session,
        storage,
        organization_id=organization_id,
        report_type=report_type,
        template_version=template_version,
        content=content,
        content_type=content_type,
        requested_by=requested_by,
        posted_run_id=posted_run_id,
        engine_version=engine_version,
    )
    return {"artifact_id": str(artifact.id)}


def _job_info_from_protocol(job: Job) -> ReportJobInfo:
    return ReportJobInfo(
        job_id=job.id,
        status=str(job.status),
        result=job.result,
        last_error=job.last_error,
    )


def _job_info_from_row(row: JobRow) -> ReportJobInfo:
    return ReportJobInfo(
        job_id=row.id,
        status=str(row.status),
        result=row.result,
        last_error=row.last_error,
    )


async def get_report_job(
    session: AsyncSession,
    queue: JobQueue,
    *,
    organization_id: UUID,
    job_id: UUID,
) -> ReportJobInfo:
    """Return org-scoped job status.

    ``JobQueue`` has no get-by-id. Prefer the in-memory queue's private
    ``_jobs`` map when present (tests); otherwise query the ``jobs`` table.
    """
    jobs_map = getattr(queue, "_jobs", None)
    if isinstance(jobs_map, dict):
        job = jobs_map.get(job_id)
        if job is None:
            raise ReportJobNotFoundError()
        if job.organization_id != organization_id:
            raise ReportJobNotFoundError()
        if job.job_type != JOB_TYPE_GENERATE_REPORT:
            raise ReportJobNotFoundError()
        return _job_info_from_protocol(job)

    stmt = sa.select(JobRow).where(
        JobRow.organization_id == organization_id,
        JobRow.id == job_id,
        JobRow.job_type == JOB_TYPE_GENERATE_REPORT,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise ReportJobNotFoundError()
    return _job_info_from_row(row)


__all__ = [
    "DEFAULT_ENGINE_VERSION",
    "DEFAULT_TEMPLATE_VERSION",
    "JOB_TYPE_GENERATE_REPORT",
    "SUPPORTED_FORMATS",
    "PostedRunNotFoundError",
    "RegisteredReportInfo",
    "ReportJobInfo",
    "ReportJobNotFoundError",
    "ReportTypeNotFoundError",
    "RunNotPostedError",
    "UnsupportedReportFormatError",
    "execute_generate_report",
    "get_report_job",
    "list_registered_reports",
    "request_report",
]
