# Frontend Playwright E2E

Critical-path browser suite against the **real local stack** (Vite + FastAPI + Postgres). Playwright does **not** start `webServer`; you start and stop the stack yourself.

## Prerequisites

- Node ≥ 22, pnpm workspace install from repo root
- PostgreSQL 18 on `127.0.0.1:5432`
- ADR database roles from `backend/scripts/create_roles.sql` (`accord_app`, `accord_migrator`, `accord_worker`) with local password `accord` (see `backend/.env.example`)

> `scripts/start.sh` defaults to user/db `accord`/`accord`. This machine uses the ADR roles instead; the commands below set `ACCORD_DB_*` and explicit DSNs accordingly.

## One-time / reset: `accord_e2e` database

Prefer the opt-in helper (refuses non-allowlisted DB names; never runs automatically):

```bash
# From repo root — REQUIRED flag; prints host/db before destroying data
./scripts/reset_e2e_db.sh --i-understand-this-deletes-data --db accord_e2e
# then re-apply grants/roles as needed (see script output) and start the stack
```

Manual equivalent:

```bash
dropdb -h 127.0.0.1 --if-exists accord_e2e
createdb -h 127.0.0.1 accord_e2e
psql -h 127.0.0.1 -d postgres -v ON_ERROR_STOP=1 \
  -c "ALTER DATABASE accord_e2e OWNER TO accord_migrator;" \
  -c "GRANT CONNECT ON DATABASE accord_e2e TO accord_app, accord_migrator, accord_worker;"
psql -h 127.0.0.1 -d accord_e2e -v ON_ERROR_STOP=1 \
  -f backend/scripts/create_roles.sql \
  -c "GRANT ALL ON SCHEMA public TO accord_migrator;" \
  -c "GRANT USAGE ON SCHEMA public TO accord_app, accord_worker;"
```

Migrations run automatically when you start the stack (`alembic upgrade head`).

After migrate, bootstrap the **singleton** organization (no UI create):

```bash
MIGRATIONS_DATABASE_URL=postgresql+asyncpg://accord_migrator:accord@127.0.0.1:5432/accord_e2e \
backend/.venv/bin/python scripts/provision_organization.py \
  --name "E2E Org" --slug e2e-org --admin-email "${DEV_AUTH_EMAIL:-dev@accord.local}"
```

Normal e2e runs **reuse** that singleton. Do not create additional orgs. If `COUNT(organizations) > 1`, reset with the opt-in script above.

## Install browsers (once per machine / after Playwright bump)

```bash
pnpm install
pnpm --filter frontend exec playwright install chromium
```

## Start the stack

```bash
cd /path/to/accord

ACCORD_DB_USER=accord_app \
ACCORD_DB_PASSWORD=accord \
ACCORD_DB_NAME=accord_e2e \
DATABASE_URL=postgresql+asyncpg://accord_app:accord@127.0.0.1:5432/accord_e2e \
MIGRATIONS_DATABASE_URL=postgresql+asyncpg://accord_migrator:accord@127.0.0.1:5432/accord_e2e \
DEV_AUTH_BYPASS=true \
./scripts/start.sh
```

- Frontend: http://127.0.0.1:5173 (proxies `/api` → backend)
- Backend: http://127.0.0.1:8000
- Logs: `.accord-dev/logs/`

## Run E2E

```bash
pnpm --filter frontend e2e
# or interactive UI
pnpm --filter frontend e2e:ui
```

Config: `frontend/playwright.config.ts` — `baseURL` `http://127.0.0.1:5173`, `retries: 1`, `trace: on-first-retry`, Chromium only.

## Coverage and tooling policy

Hosted CI lints and format-checks only tracked E2E TypeScript, then runs `playwright test --list` to prove test discovery. It does not start the application stack or a browser. The full Chromium suite is local release-acceptance evidence against a freshly prepared real stack.

The tracked-file selection excludes `.auth`, `playwright-report`, `test-results`, `blob-report`, and other generated or ignored artifacts. Never inspect, format, or commit authentication state. Report generation/download remains outside browser acceptance until the harness has a documented multi-identity and posted-run data strategy; API, service, and frontend integration tests remain the proof for that path.

## Stop

```bash
./scripts/stop.sh
```

## Suite layout

| Spec | Role |
| --- | --- |
| `auth-and-org.spec.ts` | **Setup project**: dev-bypass login, reuse singleton org, save `e2e/.auth/user.json` + run context |
| `master-data.spec.ts` | Office, pay component, employee (+ regime), schedule pay change, masked PAN |
| `payroll-flow.spec.ts` | Period → run → input → Calculate → Validate → Submit → self-approve blocked |
| `reports.spec.ts` | Empty posted-run state; generate-report journey `test.skip` (see below) |
| `axe-a11y.spec.ts` | axe-core smoke on login, authenticated landing, employees list |

Specs share one org per run via `storageState` and `e2e/.auth/run-context.json` (unique slug each process).

## Resolved defects retained as regression coverage

`payroll-flow.spec.ts` now exercises draft input creation and normal
idempotency headers without a workaround. It retains regression context for
two fixed defects: a post-commit refresh that lost the RLS GUC, and an
idempotency lease commit that failed to rebind tenant context.

## Dev auth limitation (maker/checker & reports)

`DevAuthAdapter` (`backend/app/auth/adapters.py`) returns a single identity from `DEV_AUTH_EMAIL` / `DEV_AUTH_NAME` configured at **process startup**. With `DEV_AUTH_BYPASS=true`, `GET /api/auth/login` mints that session immediately (no WorkOS callback).

Consequences for this lane:

1. **No second UI identity** without restarting the backend with a different `DEV_AUTH_EMAIL`.
2. Org creator is `organization_administrator` (all capabilities). After **Submit**, the same user **Approve** is rejected with maker/checker (`urn:accord:workflow:maker_checker`) — covered in `payroll-flow.spec.ts`.
3. **Posted runs** require a different approver, so the full report generate → poll → download path is `test.skip` in `reports.spec.ts`.

## Login redirect note

`start.sh` defaults `PUBLIC_APP_URL` / `BASE_URL` to `http://127.0.0.1:5173`, matching Playwright’s `baseURL`, and forwards `DEV_AUTH_EMAIL` / `DEV_AUTH_NAME` to the backend. Override those values before startup when testing a second local identity.

## Axe policy

- Fail the suite on **serious** / **critical** violations.
- **Moderate** violations are logged to the console and documented in the run output; they do not fail the test.

## Verification expectation

Run the suite against a freshly prepared `accord_e2e` database for release
evidence. The report generation/download test is intentionally skipped for
the single-identity reason above; do not describe the browser lane as complete
report-export proof. Backend report API/service tests provide that coverage.
