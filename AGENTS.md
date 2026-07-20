# AGENTS.md

## Cursor Cloud specific instructions

Environment notes for future cloud agents. System deps (Node 24.18.0, Python 3.14,
PostgreSQL 18) are already baked into the VM snapshot; the startup update script only
refreshes project dependencies (`pnpm install` + backend venv `pip install`). Standard
run/verify commands live in `README.md`, root `package.json` scripts, and `scripts/`.

### Services and how to run them

- **Start everything:** `./scripts/start.sh` (backend on `:8000`, frontend/Vite on
  `:5173`, `DEV_AUTH_BYPASS=true`; it also runs `alembic upgrade head`). Stop with
  `./scripts/stop.sh`. See `README.md` "Quick start" for flags and port overrides.
- **PostgreSQL is NOT auto-started on a fresh VM.** The cluster data dir (roles, DBs,
  `pg_hba.conf`) persists in the snapshot, but the server process does not. Start it
  each session before running the app or tests:
  `sudo pg_ctlcluster 18 main start`.

### Non-obvious gotchas

- **Node/pnpm PATH shadowing:** `/exec-daemon/node` is an older Node 22.14 that is
  earlier in `PATH`. It is overridden by symlinks in `/usr/local/cargo/bin` (first in
  `PATH`) pointing at Node 24.18.0, plus a corepack-managed `pnpm` 10.34.3. So `node`
  and `pnpm` already resolve to the correct versions — do not "fix" this with nvm.
- **Backend venv is Python 3.14** at `backend/.venv` (deadsnakes `python3.14`). The
  repo's `dev-setup.sh`/`start.sh` fall back to `python3 -m venv`, which would be the
  system 3.12 — the venv is intentionally created with `python3.14` instead.
- **Postgres auth:** `pg_hba.conf` is set to `trust` for `127.0.0.1`. An `ubuntu`
  superuser role exists for admin `psql`. App roles `accord` (password `accord`) plus
  ADR-0001 roles (`accord_app` / `accord_migrator` / `accord_worker`) and the `accord`
  and `accord_test` databases are already provisioned.
- **Organization bootstrap is CLI-only (ADR 0011).** Until an org row exists the app
  shows "Deployment Not Ready". An org (`Dev Org`, admin `dev@accord.local`, which
  matches `DEV_AUTH_EMAIL`) is already provisioned in the snapshot DB. If the DB is
  reset, re-run:
  ```bash
  DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord" \
  MIGRATIONS_DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord" \
  ENVIRONMENT=development DEV_AUTH_BYPASS=true \
  SESSION_SECRET_KEY=dev-only-local-session-secret ACCORD_ALLOW_WEAK_SECRETS=1 \
  backend/.venv/bin/python scripts/provision_organization.py \
    --name "Dev Org" --slug dev-org --admin-email dev@accord.local
  ```
- **Dev login:** on `/login`, any email/password works (auth bypass); the session
  identity is fixed from `DEV_AUTH_EMAIL` at backend startup.

### Verify / test

- **Frontend:** `pnpm --filter frontend lint` / `format:check` / `typecheck` /
  `test:run` / `build` (see `.github/workflows/ci.yml`). `./scripts/verify.sh` runs the
  combined lanes.
- **Backend:** from `backend/`, `.venv/bin/ruff check app tests`,
  `.venv/bin/ruff format --check app tests`, and pytest. pytest's `conftest.py` defaults
  `TEST_DATABASE_URL` to a stale developer DSN, so set it explicitly to a db whose name
  contains `test`:
  ```bash
  cd backend
  TEST_DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord_test" \
  PYTHONPATH=. .venv/bin/pytest tests -q
  ```
- **Playwright E2E** (`pnpm --filter frontend e2e`) additionally requires browser
  binaries (`pnpm --filter frontend exec playwright install`), which are not part of the
  standard update script.
