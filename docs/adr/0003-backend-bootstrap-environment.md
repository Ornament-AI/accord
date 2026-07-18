# ADR-0003: Backend Bootstrap and Environment

**Status:** Proposed

## Context

Accord’s backend is FastAPI/Python with PostgreSQL, mirroring Atlas operational conventions where they remain valid under multi-tenancy and WorkOS: pydantic-settings fail-fast config, structlog JSON logging with request IDs, Problem Detail error envelopes, security headers, health/readiness probes, and async SQLAlchemy lifecycle.

Atlas constructs a module-level `app`. Accord should keep Atlas’s safety conventions but improve testability. Auth moves from Firebase to WorkOS ([0002-workos-authentication-sessions.md](0002-workos-authentication-sessions.md)); tenancy requires separate migrator vs runtime DSNs ([0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)).

## Decision

### 1. App factory (`create_app()`)

Use an explicit application factory:

```python
def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Accord",
        lifespan=lifespan,
        default_response_class=JSONResponse,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    # middleware, routers, exception handlers...
    return app


app = create_app()  # ASGI entrypoint may still expose module-level app
```

**Deviation from Atlas:** Atlas uses a module-level app built at import time. Accord uses `create_app()` so tests can construct an app with overridden settings/dependencies without re-importing a singleton. Other conventions (settings, logging, Problem Detail, security headers, health, lifespan dispose) stay aligned with Atlas.

### 2. pydantic-settings with fail-fast validation

```python
from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    migrations_database_url: str = Field(default="", alias="MIGRATIONS_DATABASE_URL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    workos_client_id: str = Field(default="", alias="WORKOS_CLIENT_ID")
    workos_api_key: str = Field(default="", alias="WORKOS_API_KEY")
    workos_redirect_uri: str = Field(default="", alias="WORKOS_REDIRECT_URI")
    workos_webhook_secret: str = Field(default="", alias="WORKOS_WEBHOOK_SECRET")
    session_secret_key: str = Field(default="", alias="SESSION_SECRET_KEY")
    dev_auth_bypass: bool = Field(default=False, alias="DEV_AUTH_BYPASS")
    # ... remaining fields from env matrix below

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def _validate_production_invariants(self) -> "Settings":
        if self.is_production and self.dev_auth_bypass:
            raise ValueError("DEV_AUTH_BYPASS cannot be enabled in production.")
        if self.is_production:
            required = {
                "WORKOS_CLIENT_ID": self.workos_client_id,
                "WORKOS_API_KEY": self.workos_api_key,
                "WORKOS_REDIRECT_URI": self.workos_redirect_uri,
                "WORKOS_WEBHOOK_SECRET": self.workos_webhook_secret,
                "SESSION_SECRET_KEY": self.session_secret_key,
                "MIGRATIONS_DATABASE_URL": self.migrations_database_url,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    "Missing required production settings: " + ", ".join(missing)
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

Fail-fast at first `get_settings()` call — the process must not start “with auth disabled” in production.

### 3. structlog JSON logging and request context

Mirror Atlas’s processor pipeline:

```python
def configure_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
            structlog.processors.JSONRenderer(serializer=json.dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

Request-context middleware:

```python
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")

async def request_context_middleware(request: Request, call_next):
    inbound = request.headers.get("X-Request-ID")
    if inbound and REQUEST_ID_PATTERN.fullmatch(inbound):
        request_id = inbound
    else:
        request_id = uuid4().hex
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        # organization_id / user_id bound later by auth dependency when known
    )
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        structlog.contextvars.clear_contextvars()
```

Also stamp `X-Organization-Id` on organization-scoped responses once auth context is known (see ADR 0004).

### 4. RFC 9457 Problem Detail error envelope

RFC 9457 (2023) succeeds RFC 7807 with the same JSON shape. Accord uses RFC 9457 naming in docs/code comments; wire format matches Atlas’s `problem_content` / `problem_response`:

```python
def problem_content(
    *,
    status_code: int,
    detail: str,
    instance: str,
    error: str | None = None,
    request_id: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status_code).phrase,
        "status": status_code,
        "detail": detail,
        "instance": instance,
    }
    if error:
        body["error"] = error
    if request_id:
        body["request_id"] = request_id
    if errors:
        body["errors"] = errors
    return body
```

Exception handlers:

```python
class AccordError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400, error: str = "AccordError"):
        self.detail = detail
        self.status_code = status_code
        self.error = error


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return problem_response(
        status_code=exc.status_code,
        detail=str(exc.detail),
        instance=str(request.url.path),
        request_id=getattr(request.state, "request_id", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return problem_response(
        status_code=422,
        detail="Request validation failed.",
        instance=str(request.url.path),
        error="RequestValidationError",
        request_id=getattr(request.state, "request_id", None),
        errors=[
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
            for err in exc.errors()
        ],
    )


@app.exception_handler(AccordError)
async def accord_error_handler(request: Request, exc: AccordError):
    return problem_response(
        status_code=exc.status_code,
        detail=exc.detail,
        instance=str(request.url.path),
        error=exc.error,
        request_id=getattr(request.state, "request_id", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception")
    return problem_response(
        status_code=500,
        detail="An unexpected error occurred.",
        instance=str(request.url.path),
        error="InternalServerError",
        request_id=getattr(request.state, "request_id", None),
    )
```

Catch-all **must not** leak stack traces or internal exception messages to clients.

### 5. Security headers middleware

Pure ASGI middleware (skip non-HTTP and `OPTIONS`), same header set as Atlas:

```python
_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "content-security-policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    ),
    "x-xss-protection": "0",
}
```

### 6. Health vs readiness

| Endpoint | Role | Checks |
| --- | --- | --- |
| `GET /api/healthz` | Liveness | None — returns `{"status": "ok"}` if the process is up |
| `GET /api/readyz` | Readiness | DB `SELECT 1` now; auth subsystem ready (WorkOS config loaded / provider initialized); **designed to extend** later with queue (Celery/Arq if adopted) and object storage checks |

On any failed readiness dependency, return **503** with a Problem Detail body (not a bare string). Example success body:

```json
{
  "status": "ok",
  "database": "ok",
  "auth": "ok"
}
```

Future keys (not required until those subsystems exist): `"queue": "ok"`, `"object_storage": "ok"`.

### 7. Graceful shutdown / lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        async with session_context() as session:
            await session.execute(text("SELECT 1"))
        logger.info("startup_complete", database="ok")
    except Exception:
        logger.error("startup_database_unavailable")
        raise
    # Mark auth provider readiness on app.state (WorkOS or DevTest)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("shutdown_complete")
```

- Startup: fail loudly if DB unreachable (do not serve traffic).
- Shutdown: `dispose_engine()` disposes the async engine after in-flight requests drain (uvicorn/gunicorn graceful timeout still applies at the process manager layer).

Pool tuning (aligned with Atlas defaults unless overridden): `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`, `pool_pre_ping=True`, `pool_use_lifo=True`, `statement_timeout` via asyncpg `server_settings`, `application_name=accord-api`.

### 8. Environment variable matrix

| Variable | Required in prod? | Default in dev | Secret? | Description |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | yes | local Postgres DSN as `accord_app` | yes | Runtime/API role DSN (`NOSUPERUSER`, `NOBYPASSRLS`) |
| `MIGRATIONS_DATABASE_URL` | yes | local DSN as `accord_migrator` | yes | Migration-owner role DSN (`BYPASSRLS` / table owner); Alembic only |
| `WORKOS_CLIENT_ID` | yes | empty / test value | no | WorkOS client id |
| `WORKOS_API_KEY` | yes | empty | yes | WorkOS server-side API key |
| `WORKOS_REDIRECT_URI` | yes | `http://localhost:8000/api/auth/callback` | no | OAuth redirect URI registered in WorkOS |
| `WORKOS_WEBHOOK_SECRET` | yes | empty | yes | Webhook signing secret |
| `SESSION_SECRET_KEY` | yes | dev-only random | yes | Signs/encrypts session cookie material / session id MAC |
| `SESSION_COOKIE_NAME` | no | `accord_session` | no | Session cookie name |
| `ENVIRONMENT` | yes | `development` | no | `development` / `staging` / `production` |
| `CORS_ORIGINS` | yes (non-empty) | Vite localhost origins | no | Comma-separated allowed browser origins |
| `BASE_URL` / `PUBLIC_APP_URL` | yes | `http://localhost:5173` | no | Public app URL for redirects/links |
| `LOG_LEVEL` | no | `INFO` | no | Logging level |
| `OBJECT_STORAGE_ENDPOINT` | when storage used | empty / local MinIO | no | S3-compatible endpoint |
| `OBJECT_STORAGE_BUCKET` | when storage used | empty | no | Bucket name |
| `OBJECT_STORAGE_ACCESS_KEY` | when storage used | empty | yes | Object storage access key |
| `OBJECT_STORAGE_SECRET_KEY` | when storage used | empty | yes | Object storage secret key |
| `DEV_AUTH_BYPASS` | must be false | `false` | no | Enables `DevTestAuthProvider`; **fails closed in production** |
| `DB_POOL_SIZE` | no | `5` | no | Async SQLAlchemy pool size |
| `DB_STATEMENT_TIMEOUT_MS` | no | `60000` | no | Postgres `statement_timeout` for API connections |

**Why migration DSN ≠ runtime DSN:** Alembic must run as `accord_migrator` (owns tables, may `BYPASSRLS` for DDL/data migrations). The API must run as `accord_app` (`NOBYPASSRLS`) so RLS is always enforced. Using one credential for both either weakens RLS in production or blocks migrations. See ADR 0001.

## Consequences

- Tests can build isolated apps via `create_app()` without fighting import-time singletons.
- Production misconfig (missing WorkOS/session secrets, dev bypass) fails at boot.
- Observability matches Atlas: JSON logs, request ids, Problem Detail errors.
- Readiness is extensible for queue/storage without changing liveness semantics.
- Dual DSNs are an operational requirement from day one.

## Alternatives Considered

1. **Module-level app only (Atlas exact)** — Rejected as the sole pattern; factory is a small deviation for testability while preserving Atlas’s safety stack.
2. **RFC 7807 naming in code** — Rejected for new Accord code comments/docs; use RFC 9457. Wire JSON shape remains compatible.
3. **Single `DATABASE_URL` for migrations and runtime** — Rejected; conflicts with mandatory RLS role separation (ADR 0001).
4. **Combine liveness and readiness** — Rejected; orchestrators need a dependency-free liveness probe.
5. **Pretty/console logging in production** — Rejected; JSON structlog only for production aggregation (dev may later add a console renderer behind `ENVIRONMENT`, optional).
