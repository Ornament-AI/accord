"""Accord API — FastAPI application entry point."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.responses import problem_content, problem_response
from app.jobs.postgres import PostgresJobQueue
from app.platform_setup import wire_report_platform
from app.api.routes import (
    artifacts,
    audit,
    auth,
    employees,
    health,
    org_structure,
    organizations,
    pay_setup,
    payroll_runs,
    reports,
    run_commands,
    run_posting,
    run_results,
    run_workflow,
)
from app.config import Settings, get_settings
from app.db import dispose_engine, session_context
from app.exceptions import AccordError
from app.logging_config import configure_logging
from app.middleware.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.observability import setup_observability
from app.reports.registry_setup import build_report_registry

logger = structlog.get_logger()

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _auth_provider_ready(settings: Settings) -> bool:
    """Mark auth readiness for the WorkOS / DevTest seam.

    A later lane initializes real providers. Until then:
    - DEV_AUTH_BYPASS ⇒ DevTest ready
    - WorkOS client id + API key present ⇒ config seam ready
    - non-production with neither ⇒ allow skeleton boot
    """
    if settings.dev_auth_bypass:
        return True
    if settings.workos_client_id and settings.workos_api_key:
        return True
    return not settings.is_production


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fail loudly if the database is unreachable; dispose the engine on shutdown."""
    startup_settings = get_settings()
    app.state.auth_ready = _auth_provider_ready(startup_settings)
    registry, storage = wire_report_platform(startup_settings)
    app.state.report_registry = registry
    if storage is not None:
        app.state.object_storage = storage
    try:
        async with session_context() as session:
            await session.execute(text("SELECT 1"))
        from app.db import get_session_factory

        app.state.job_queue = PostgresJobQueue(get_session_factory())
        logger.info(
            "startup_complete",
            database="ok",
            auth=app.state.auth_ready,
            report_types=len(registry.report_types())
            if hasattr(registry, "report_types")
            else None,
        )
    except Exception:
        logger.error("startup_database_unavailable")
        raise

    try:
        yield
    finally:
        await dispose_engine()
        logger.info("shutdown_complete")


def _request_id_from_header(request: Request) -> str | None:
    request_id = request.headers.get("X-Request-ID")
    if request_id is None:
        return None
    if REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    logger.warning(
        "invalid_request_id_rejected",
        path=str(request.url.path),
        request_id_length=len(request_id),
    )
    return None


def _request_id_headers(
    request: Request,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Preserve caller headers while adding the trusted request ID."""
    headers = dict(extra_headers or {})
    request_id = getattr(request.state, "request_id", None) or _request_id_from_header(request)
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


def _build_problem_detail(
    *,
    request: Request,
    status_code: int,
    detail: str,
    error: str | None = None,
    errors=None,
) -> dict:
    """Build the RFC 9457 Problem Detail payload used by every API failure."""
    return problem_content(
        status_code=status_code,
        detail=detail,
        instance=str(request.url.path),
        error=error,
        request_id=getattr(request.state, "request_id", None),
        errors=errors,
    )


def _problem_json_response(
    request: Request,
    *,
    status_code: int,
    detail: str,
    request_id: str,
) -> JSONResponse:
    """Return a ProblemDetail response for middleware-level rejections."""
    return problem_response(
        status_code=status_code,
        detail=detail,
        instance=str(request.url.path),
        request_id=request_id,
        headers={"X-Request-ID": request_id},
    )


async def handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded):
    """Normalize SlowAPI 429s into the public ProblemDetail contract."""
    request_id = getattr(request.state, "request_id", None) or _request_id_from_header(request)
    return problem_response(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=str(getattr(exc, "detail", "Rate limit exceeded.")),
        instance=str(request.url.path),
        error="RateLimitExceeded",
        request_id=request_id,
        headers=_request_id_headers(request, getattr(exc, "headers", None)),
    )


async def handle_accord_error(request: Request, exc: AccordError):
    """Serialize domain errors into the public ProblemDetail contract."""
    body = _build_problem_detail(
        request=request,
        status_code=exc.status_code,
        detail=exc.detail,
        error=exc.error,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=_request_id_headers(request),
    )


async def handle_http_exception(request: Request, exc: HTTPException):
    """Normalize FastAPI HTTP errors into the public ProblemDetail contract."""
    body = _build_problem_detail(
        request=request,
        status_code=exc.status_code,
        detail=str(exc.detail or "Request failed."),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=_request_id_headers(request, exc.headers),
    )


async def handle_validation_error(request: Request, exc: RequestValidationError):
    """Expose request validation failures as structured client errors."""
    serialized = [
        {
            "loc": [str(p) for p in e.get("loc", ())],
            "msg": str(e.get("msg", "")),
            "type": str(e.get("type", "")),
        }
        for e in exc.errors()
    ]
    body = _build_problem_detail(
        request=request,
        status_code=422,
        detail="Request validation failed.",
        error="RequestValidationError",
        errors=serialized,
    )
    return JSONResponse(
        status_code=422,
        content=body,
        headers=_request_id_headers(request),
    )


async def handle_unhandled(request: Request, exc: Exception):
    """Log unexpected failures and return a stable 500 response."""
    logger.exception("unhandled_error", path=str(request.url))
    body = _build_problem_detail(
        request=request,
        status_code=500,
        detail="An unexpected error occurred.",
        error="InternalServerError",
    )
    return JSONResponse(
        status_code=500,
        content=body,
        headers=_request_id_headers(request),
    )


async def request_context_middleware(request: Request, call_next):
    """Bind request context and reject malformed Content-Length early."""
    settings = get_settings()
    request_id = _request_id_from_header(request) or uuid4().hex
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        content_length_raw = request.headers.get("content-length")
        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw)
            except (ValueError, OverflowError):
                return _problem_json_response(
                    request,
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Content-Length header",
                    request_id=request_id,
                )
            if content_length > settings.max_request_body_bytes:
                return _problem_json_response(
                    request,
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Request body too large",
                    request_id=request_id,
                )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        structlog.contextvars.clear_contextvars()


def create_app() -> FastAPI:
    """Build and configure the Accord FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Accord",
        version=settings.app_version,
        lifespan=lifespan,
        default_response_class=JSONResponse,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    cors_origins = [o for o in (s.strip() for s in settings.cors_origins.split(",")) if o]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
            "Idempotency-Key",
        ],
        allow_credentials=True,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.middleware("http")(request_context_middleware)

    app.add_exception_handler(RateLimitExceeded, handle_rate_limit_exceeded)
    app.add_exception_handler(AccordError, handle_accord_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unhandled)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(organizations.router, prefix="/api")
    app.include_router(employees.router, prefix="/api")
    app.include_router(org_structure.router, prefix="/api")
    app.include_router(pay_setup.router, prefix="/api")
    app.include_router(payroll_runs.router, prefix="/api")
    app.include_router(run_commands.router, prefix="/api")
    app.include_router(run_workflow.router, prefix="/api")
    app.include_router(run_posting.router, prefix="/api")
    app.include_router(run_results.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")

    # Seed registry so readiness works when ASGI test clients skip lifespan.
    # Lifespan re-wires via wire_report_platform() on real process start.
    if not getattr(app.state, "report_registry", None):
        app.state.report_registry = build_report_registry()

    setup_observability(app)
    return app


app = create_app()
