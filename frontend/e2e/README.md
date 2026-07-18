# Frontend Playwright E2E

Critical-path browser suite against the **real local stack** (Vite + FastAPI + Postgres). Playwright does **not** start `webServer`; you start and stop the stack yourself.

## Prerequisites

- Node ≥ 22, pnpm workspace install from repo root
- PostgreSQL 18 on `127.0.0.1:5432`
- ADR database roles from `backend/scripts/create_roles.sql` (`accord_app`, `accord_migrator`, `accord_worker`) with local password `accord` (see `backend/.env.example`)

> `scripts/start.sh` defaults to user/db `accord`/`accord`. This machine uses the ADR roles instead; the commands below set `ACCORD_DB_*` and explicit DSNs accordingly.

## One-time / reset: `accord_e2e` database

```bash
# From repo root
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

## Stop

```bash
./scripts/stop.sh
```

## Suite layout

| Spec | Role |
| --- | --- |
| `auth-and-org.spec.ts` | **Setup project**: dev-bypass login, create unique org, save `e2e/.auth/user.json` + run context |
| `master-data.spec.ts` | Office, pay component, employee (+ regime), schedule pay change, masked PAN |
| `payroll-flow.spec.ts` | Period → run → input → Calculate → Validate → Submit → self-approve blocked |
| `reports.spec.ts` | Empty posted-run state; generate-report journey `test.skip` (see below) |
| `axe-a11y.spec.ts` | axe-core smoke on login, dashboard, employees list |

Specs share one org per run via `storageState` and `e2e/.auth/run-context.json` (unique slug each process).

## Known app bugs found by this lane

### Payroll run input upsert 500 (`PayrollRunInput` refresh)

- **Repro:** Add a draft run input via Pay Run detail → Add input (or `PUT /api/payroll-runs/{id}/inputs/...`).
- **Expected:** Input saved; dialog closes; row appears in the inputs table.
- **Actual:** UI alert “An unexpected error occurred.” Backend:
  `sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<PayrollRunInput …>'`
  after `commit` in `backend/app/services/payroll_runs.py` (`upsert_run_input`, `db.refresh(row)`).
- **E2E handling:** `payroll-flow.spec.ts` marks the add-input step `test.fixme` and continues Calculate using the employee’s basic-pay version from master-data.

### Submit/approve with Idempotency-Key → 404 “Payroll run not found.”

- **Repro:** Calculate + Validate a run (200). Click Submit (UI sends `Idempotency-Key`).
- **Expected:** Status → Submitted.
- **Actual:** Confirm dialog shows “Payroll run not found.” (`POST …/submit` 404).
- **Suspect:** `idempotent_command` commits the in-progress lease before the executor (`backend/app/services/idempotency.py`), which clears request-scoped RLS `SET LOCAL` GUCs; `_lock_run` (`FOR UPDATE`) then finds no row.
- **E2E handling:** Main payroll flow strips `Idempotency-Key` via `page.route` (header is optional). A `test.fixme` keeps the failing case documented.

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

## Live-run status (2026-07-18)

The suite runs green on a fresh `accord_e2e` DB: **9 passed, 1 skipped**
(setup, axe a11y ×3, master-data, payroll-flow ×3, reports empty-state; the
reports *generate* journey stays skipped under the single dev-auth identity).

Three real defects were driven out and fixed:

- **Fixed (harness)** — dev-login interception now stops at the backend 302 before
  rewriting its host. Following the redirect inside `route.fetch()` left the browser
  URL on `/api/auth/login` while serving SPA HTML, which correctly rendered the
  catch-all page.
- **Fixed** — `PUT /api/payroll-runs/{id}/inputs/...` 500: response is now built
  before commit (a post-commit `db.refresh` ran under cleared RLS GUCs).
- **Fixed** — submit/approve with `Idempotency-Key` 404: `idempotent_command`
  now snapshots and rebinds tenant GUCs across its mid-command commit.
- **Fixed (harness)** — setup flakiness was a race in `ensureUniqueOrganization`:
  a non-waiting `isVisible()` during `/me` settling took the wrong branch. The
  helper now waits for the no-org title *or* the dashboard before branching and
  opens dialogs via `clickUntilDialog` (Base UI portal retry). payroll-flow is
  serial and retry-safe (shared regular draft; supplemental for the
  Idempotency-Key case).
