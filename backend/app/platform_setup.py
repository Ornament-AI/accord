"""Shared platform wiring for the API and worker processes (Lane 1 integration).

Builds the object storage adapter and configures the report-generation
pipeline so both processes assemble identical registries and dependencies.
"""

from __future__ import annotations

import structlog

from app.config import Settings
from app.domain.payroll.engine import ENGINE_VERSION
from app.jobs.handlers import configure_generate_report
from app.reports.base import ReportRegistry
from app.reports.registry_setup import build_report_registry
from app.storage.protocol import ObjectStorage
from app.storage.s3 import S3ObjectStorage

logger = structlog.get_logger(__name__)


def build_object_storage(settings: Settings) -> ObjectStorage | None:
    """S3-compatible storage when configured; None otherwise (endpoints 503)."""
    if not (settings.object_storage_endpoint and settings.object_storage_bucket):
        logger.info("object_storage_not_configured")
        return None
    return S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint,
        bucket=settings.object_storage_bucket,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
    )


def wire_report_platform(settings: Settings) -> tuple[ReportRegistry, ObjectStorage | None]:
    """Build the report registry and, when storage is available, configure
    the generate_report job handler. Returns both for app.state / worker use."""
    registry = build_report_registry()
    storage = build_object_storage(settings)
    if storage is not None:
        configure_generate_report(
            storage=storage,
            registry=registry,
            engine_version=ENGINE_VERSION,
        )
    return registry, storage
