# ADR-0003: Backend Bootstrap and Environment

**Status:** Accepted

## Context

Accord’s backend is FastAPI/Python with PostgreSQL. It keeps the Atlas habits
that still hold under the singleton-organization product and its retained RLS
kernel: fail-fast config via `pydantic-settings`, JSON logs via `structlog`
with request IDs, Problem Detail error bodies, security headers, health and
readiness probes, and an async `SQLAlchemy` lifecycle.

Atlas builds a module-level `app`. Accord should keep Atlas’s safety habits but make testing easier. Auth moves from Firebase to WorkOS ([0002-workos-authentication-sessions.md](0002-workos-authentication-sessions.md)). Tenancy needs separate migrator and runtime DSNs ([0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)).

## Decision

### 1. App factory (`create_app()`)

Use an explicit app factory:

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

**Deviation from Atlas:** Atlas builds a module-level app at import time. Accord uses `create_app()` instead. Tests can then build an app with their own settings or dependencies, without re-importing a singleton. The other pieces (settings, logging, Problem Detail, security headers, health, lifespan dispose) stay aligned with Atlas.

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
    workos_redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/callback",
        alias="WORKOS_REDIRECT_URI",
    )
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

Fail fast at the first `get_settings()` call. The process must not start “with auth disabled” in production.

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
            redact_sensitive,
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

The recursive `redact_sensitive` processor runs immediately before JSON
rendering so sensitive values are removed from nested structures. The
middleware emits `X-Request-ID`; the earlier plan to emit
`X-Organization-Id` was not implemented and is no longer part of the
single-organization product contract (see ADR 0004).

### 4. RFC 9457 Problem Detail error envelope

RFC 9457 (2023) replaces RFC 7807 and keeps the same JSON shape. Accord uses RFC 9457 naming in docs and code comments. The wire format matches Atlas’s `problem_content` / `problem_response`:

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

`AccordError` subclasses declare `status_code` and optional `error_code` class
attributes; instances carry a message and optional details. `create_app()`
registers handlers for rate limits, `AccordError`, FastAPI `HTTPException`,
request validation, and otherwise-unhandled exceptions. The implementation in
`backend/app/main.py` delegates envelope construction to
`backend/app/api/responses.py` and preserves `X-Request-ID` on error responses.

The catch-all handler **must not** leak stack traces or internal error text to clients.

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
| `GET /api/readyz` | Readiness | Database and auth are hard requirements. The response also reports the PostgreSQL jobs table, configured object storage, and report registry. |

Database or auth failure returns **503** through the Problem Detail handler.
Jobs, configured storage, or report-registry failure returns **503** with a
component-level degraded response. Unconfigured object storage is allowed so
the API can run without artifact storage in local/test environments. Example
success body without configured storage:

```json
{
  "status": "ok",
  "database": "ok",
  "auth": "ok",
  "jobs": "ok",
  "storage": "unconfigured",
  "reports": "ok"
}
```

The executable contract is
`backend/app/api/routes/health.py`, covered by
`backend/tests/api/test_health.py` and
`backend/tests/api/test_observability.py`.

### 7. Graceful shutdown / lifespan

At startup the lifespan builds the report registry and configured object
storage, records auth readiness, proves the database with `SELECT 1`, and
installs a `PostgresJobQueue` on application state. A database failure aborts
startup. On shutdown, `dispose_engine()` closes the async engine after
in-flight requests drain; the process manager still owns the graceful timeout.

Pool tuning (Atlas defaults unless overridden): `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`, `pool_pre_ping=True`, `pool_use_lifo=True`, `statement_timeout` via asyncpg `server_settings`, `application_name=accord-api`.

### 8. Environment variable matrix

| Variable | Required in prod? | Default in dev | Secret? | Description |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | yes | none | yes | Runtime/API role DSN (`NOSUPERUSER`, `NOBYPASSRLS`) |
| `MIGRATIONS_DATABASE_URL` | yes | empty | yes | Migration-owner role DSN (`BYPASSRLS` / table owner); Alembic only |
| `WORKOS_CLIENT_ID` | yes | empty | no | WorkOS client id |
| `WORKOS_API_KEY` | yes | empty | yes | WorkOS server-side API key |
| `WORKOS_REDIRECT_URI` | yes | `http://localhost:8000/api/auth/callback` | no | OAuth redirect URI registered in WorkOS |
| `WORKOS_WEBHOOK_SECRET` | yes | empty | yes | Webhook signing secret |
| `WORKOS_WEBHOOK_TOLERANCE_SECONDS` | no | `300` | no | Accepted WorkOS webhook timestamp skew |
| `SESSION_SECRET_KEY` | yes | empty | yes | Signs the opaque database-session cookie value |
| `SESSION_COOKIE_NAME` | no | `accord_session` | no | Session cookie name |
| `SESSION_IDLE_TIMEOUT_SECONDS` | no | `7200` | no | Server-side idle-session timeout |
| `ENVIRONMENT` | no | `development` | no | `production` enables production validation and secure cookies |
| `CORS_ORIGINS` | no | Vite localhost ports 5173–5176 | no | Comma-separated allowed browser origins |
| `BASE_URL` | no | `http://localhost:5173` | no | Default public app URL |
| `PUBLIC_APP_URL` | no | empty (falls back to `BASE_URL`) | no | Public redirect/link origin |
| `LOG_LEVEL` | no | `INFO` | no | Logging level |
| `APP_VERSION` | no | `dev` | no | Version exposed in FastAPI/OpenAPI application metadata |
| `MAX_REQUEST_BODY_BYTES` | no | `10485760` | no | Request-body limit |
| `OBJECT_STORAGE_ENDPOINT` | when storage used | empty | no | S3-compatible endpoint |
| `OBJECT_STORAGE_BUCKET` | when storage used | empty | no | Bucket name |
| `OBJECT_STORAGE_ACCESS_KEY` | when storage used | empty | yes | Object storage access key |
| `OBJECT_STORAGE_SECRET_KEY` | when storage used | empty | yes | Object storage secret key |
| `DEV_AUTH_BYPASS` | must be false | `false` | no | Enables `DevAuthAdapter`; **fails closed in production** |
| `DEV_AUTH_EMAIL` / `DEV_AUTH_NAME` | no | local test identity | no | Non-production bypass identity |
| `ACCORD_ALLOW_WEAK_SECRETS` | no | `false` | no | Allows a short session secret in local/test only |
| `DB_POOL_SIZE` | no | `5` | no | Async SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` | no | `5` | no | Extra pool connections above the base size |
| `DB_POOL_TIMEOUT_SECONDS` | no | `30` | no | Pool checkout timeout |
| `DB_POOL_RECYCLE_SECONDS` | no | `1800` | no | Connection recycle interval |
| `DB_STATEMENT_TIMEOUT_MS` | no | `60000` | no | Postgres `statement_timeout` for API connections |

`backend/app/config.py` is authoritative for aliases, defaults, clamps, and
production validation. The operationally complete reference, including
compose-only variables, is
[developer-reference.md](../developer-reference.md#application-configuration).

**Why migration DSN ≠ runtime DSN:** Alembic must run as `accord_migrator`. That role owns tables and may `BYPASSRLS` for DDL and data migrations. The API must run as `accord_app` (`NOBYPASSRLS`) so RLS always applies. One shared credential either weakens RLS in production or blocks migrations. See ADR 0001.

## Consequences

- Tests can build isolated apps via `create_app()` without fighting import-time singletons.
- A bad production config (missing WorkOS or session secrets, dev bypass on) fails at boot.
- Logs and errors match Atlas: JSON logs, request ids, Problem Detail bodies.
- Readiness covers jobs, storage, and reports without changing what liveness means.
- Ops must manage two DSNs from day one.

## Alternatives Considered

1. **Module-level app only (Atlas exact)** — Rejected as the sole pattern. The factory is a small deviation that helps testing while keeping Atlas’s safety stack.
2. **RFC 7807 naming in code** — Rejected for new Accord code comments and docs; use RFC 9457. The wire JSON shape stays compatible.
3. **Single `DATABASE_URL` for migrations and runtime** — Rejected. It conflicts with mandatory RLS role separation (ADR 0001).
4. **Combine liveness and readiness** — Rejected. Orchestrators need a liveness probe that depends on nothing.
5. **Pretty/console logging in production** — Rejected. Production uses JSON `structlog` only, so logs can be aggregated. Dev may later add a console renderer behind `ENVIRONMENT`, as an option.
