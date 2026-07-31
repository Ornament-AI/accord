# Developer reference

This page is the current source map for Accord's executable interfaces. It
complements the design rationale in the ADRs. When prose and code disagree,
the implementation sources named here are authoritative and the documentation
must be corrected.

## Runtime and toolchain

| Concern | Current source |
| --- | --- |
| Workspace scripts and pnpm version | root `package.json` |
| Frontend runtime and dependency versions | `frontend/package.json` and `pnpm-lock.yaml` |
| Python dependency pins | `backend/requirements.txt` and `backend/requirements-dev.txt` |
| Ruff and pytest settings | `pyproject.toml` |
| Backend configuration | `backend/app/config.py` |
| Local defaults | `backend/.env.example`, `scripts/start.sh`, `scripts/lib/` |
| Compose/production defaults | `deploy/.env.example`, `deploy/docker-compose.yml` |
| CI and release automation | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |

CI uses Node 24, pnpm 10, Python 3.14, and PostgreSQL 18. The frontend
manifest accepts Node 22.22 or newer, but using the CI version removes a
toolchain variable.

## HTTP API

`backend/app/main.py` creates the FastAPI app and mounts all application
routers under `/api`. In non-production environments FastAPI also exposes:

- `/docs` — Swagger UI
- `/redoc` — ReDoc
- `/openapi.json` — the generated schema

Those three endpoints are disabled when `ENVIRONMENT=production`. The
unauthenticated `/metrics` endpoint is intentionally outside `/api`; keep it
on a private network or behind an internal scraper.

The maintained route groups are:

| Prefix or endpoint | Owner | Purpose |
| --- | --- | --- |
| `/api/healthz`, `/api/readyz` | `api/routes/health.py` | Liveness and dependency readiness |
| `/api/auth/*` | `api/routes/auth.py` | Hosted, password, and magic-code login; logout; current identity; WorkOS webhook |
| `/api/employees*` | `api/routes/employees.py` | Employee records and effective-dated versions |
| `/api/offices*`, `/api/posts*` | `api/routes/org_structure.py` | Organization structure |
| `/api/pay-components*`, `/api/recurring-instructions*`, `/api/advances*`, `/api/accommodation*`, `/api/report-profile`, `/api/report-configurations*` | `api/routes/pay_setup.py` | Payroll setup and report defaults |
| `/api/payroll-periods*`, `/api/payroll-runs*` | payroll-run route modules | Periods, runs, roster, inputs, calculation, workflow, posting, results, and report readiness |
| `/api/reports*` | `api/routes/reports.py` | Catalog, preview, durable generation jobs, and consolidated export |
| `/api/artifacts*` | `api/routes/artifacts.py` | Artifact metadata and authenticated, audited streaming download |
| `/api/audit-events*` | `api/routes/audit.py` | Filtered immutable audit history |

Generate the exact current schema and client types with:

```bash
./scripts/generate-api-types.sh
git diff --exit-code -- frontend/src/types/api.generated.ts
```

API errors use the Problem Detail envelope built in `backend/app/main.py`.
Authenticated routes derive the principal and organization from the signed
database session. Ordinary clients never select an organization id. Mutating
routes apply the capability map in `backend/app/auth/capabilities.py`; command
routes additionally use idempotency and row locking where their service
contract requires it.

## Frontend routes

`frontend/src/router.tsx` is the route source of truth:

| Route | Surface |
| --- | --- |
| `/login` | Sign in |
| `/employees`, `/employees/:employeeId` | Employee list and detail |
| `/organization/offices`, `/organization/posts` | Organization structure |
| `/pay-components`, `/pay-components/:componentId` | Pay-component setup |
| `/pay-runs`, `/pay-runs/:runId` | Payroll run workflow |
| `/reports`, `/reports/:reportSlug` | Canonical report preview/export |
| `/audit` | Audit history |

`frontend/src/lib/nav-registry.ts` applies capability-aware navigation.
`frontend/src/route-components.tsx` handles the unbootstrapped and
unprovisioned access states before rendering the protected application.

## Application configuration

`Settings` in `backend/app/config.py` is the complete API/worker settings
contract. `DATABASE_URL` is the only field with no code default. Production
absence-checks `MIGRATIONS_DATABASE_URL`, `WORKOS_CLIENT_ID`,
`WORKOS_API_KEY`, `WORKOS_WEBHOOK_SECRET`, and `SESSION_SECRET_KEY`, and
rejects `DEV_AUTH_BYPASS=true`. `WORKOS_REDIRECT_URI` is checked for a
nonempty value but has a localhost code default, so operators must explicitly
override it with the registered production callback; omission does not
currently fail startup.

| Group | Variables |
| --- | --- |
| Database | `DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, `DB_STATEMENT_TIMEOUT_MS` |
| Runtime | `ENVIRONMENT`, `LOG_LEVEL`, `APP_VERSION`, `BASE_URL`, `PUBLIC_APP_URL`, `CORS_ORIGINS`, `MAX_REQUEST_BODY_BYTES` |
| WorkOS | `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_REDIRECT_URI`, `WORKOS_WEBHOOK_SECRET`, `WORKOS_WEBHOOK_TOLERANCE_SECONDS` |
| Session | `SESSION_SECRET_KEY`, `SESSION_COOKIE_NAME`, `SESSION_IDLE_TIMEOUT_SECONDS` |
| Local identity | `DEV_AUTH_BYPASS`, `DEV_AUTH_EMAIL`, `DEV_AUTH_NAME`, `ACCORD_ALLOW_WEAK_SECRETS` |
| Object storage | `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY` |

Compose adds operator variables rather than application settings:
`ACCORD_TAG`, `ACCORD_WEB_PORT`, `ACCORD_DB_USER`, `ACCORD_DB_NAME`,
`ACCORD_DB_PASSWORD`, `GHCR_USERNAME`, and `GHCR_TOKEN`.
`WORKER_DATABASE_URL` is a Compose-only override that is passed to the worker
container as its `DATABASE_URL`.

For development, run `./scripts/dev-setup.sh` and `./scripts/start.sh` rather
than copying production Compose settings. `start.sh` enables the local auth
adapter by default and writes selected ports and logs under `.accord-dev/`.

## Scripts

| Command | Purpose |
| --- | --- |
| `./scripts/dev-setup.sh` | Create/verify local databases, roles, and the Python virtualenv |
| `./scripts/start.sh` | Run migrations and start the API/Vite processes on resolved free ports |
| `./scripts/status.sh` | Print process state and the exact resolved URLs |
| `./scripts/stop.sh` | Stop only Accord-owned local app processes; leave PostgreSQL running |
| `./scripts/verify.sh` | Run shell syntax, backend lint/tests, API drift, frontend lint/format/typecheck/tests/build |
| `./scripts/generate-api-types.sh` | Export OpenAPI and regenerate the TypeScript client schema |
| `./scripts/smoke-test.sh [base-url]` | Probe a running Compose deployment |
| `./scripts/backup-restore.sh` | Create a logical backup and rehearse a scratch restore |
| `./scripts/deploy.sh <full-git-sha>` | Pull and prove immutable production images for an exact revision |
| `./scripts/provision_organization.py` | Create the singleton organization through the privileged CLI |
| `./scripts/provision_member.py` | Add or change local organization access through the privileged CLI |
| `./scripts/reset_e2e_db.sh` | Destructively reset only allowlisted local test databases after explicit confirmation |

Fixture-specific seed and canonical-contract tools live alongside these
general scripts and document their options through `--help`.

## Verification and release automation

Pull requests into `main` run `.github/workflows/ci.yml`. Backend-related
changes run Ruff, pytest, fresh Alembic replay/check, and backend image build.
Frontend-related changes run Biome, TypeScript, Vitest, the production build,
and web image build. The API-type job is currently a visible placeholder;
the real drift gate runs in `./scripts/verify.sh`.

Tags matching `v*` run `.github/workflows/deploy.yml`. The backend-image,
web-image, and migration-replay jobs run independently; image publication can
therefore finish before a migration-replay failure is known. Only the summary
job waits for all three. Operators must require the complete workflow to
succeed before accepting or deploying the tag. Host deployment remains the
separate action described in [operations.md](operations.md).
