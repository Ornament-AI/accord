# Accord

Accord is an open-source payroll system of record for local governments and public
works departments. Organizations maintain employee and payroll facts once, record
only effective-dated changes and monthly exceptions, calculate and approve payroll
through a maker/checker workflow, and generate export-ready Excel/PDF reports from
immutable posted payroll data.

## Principles

- **System of record** — no spreadsheet import path or workbook operating mode.
- **Exact money** — PostgreSQL `NUMERIC` + Python `Decimal`; money over the API is
  a canonical string; `float` is banned from payroll domain code.
- **Temporal truth** — effective-dated master versions; posted payroll retains the
  exact source version IDs and snapshots it was computed from.
- **Immutable posting** — posted results are never edited or deleted; corrections
  use withdrawal before posting, or reversal/supplemental runs after.
- **Defense-in-depth tenancy** — multi-organization from day one, with forced
  PostgreSQL row-level security on every tenant-owned table.
- **Transactional evidence** — every business mutation commits atomically with an
  append-only audit event and an outbox event.

## Stack

FastAPI / Python / PostgreSQL backend, React / TypeScript frontend, WorkOS
authentication, S3-compatible object storage, Docker-based deployment (self-hosted
Compose or managed PostgreSQL + object storage).

## Repository layout

- `backend/` — FastAPI application, domain engine, migrations, tests
- `frontend/` — React application (Atlas-derived design system)
- `deploy/` — Docker Compose, images, nginx, local MinIO profile
- `docs/` — architecture, ADRs, domain reference, report specs, security
- `fixtures/sanitized/` — synthetic test fixtures only; real PII is never committed

## Provenance

Accord transplants the design system and infrastructure conventions of the Atlas
application from a pinned upstream release tag. See
`docs/atlas-upstream-manifest.md` for exact provenance, exclusions, and licenses.

## License

Apache-2.0 — see [LICENSE](LICENSE).

## Quick start

**Prerequisites:** Docker (for Compose), [pnpm](https://pnpm.io/) 10.x (see
root `package.json` `packageManager`), Python 3.14 (CI `PYTHON_VERSION`), and a
local PostgreSQL 18 (or use Compose, which includes Postgres).

### Local (scripts)

```bash
# Frontend workspace deps (repo root)
pnpm install

# One-time: Postgres role/DBs (accord + accord_test), ADR roles, backend venv
./scripts/dev-setup.sh
# If Postgres is not running yet (Homebrew):
# ./scripts/dev-setup.sh --start

# Start API + Vite (runs alembic upgrade head when migrations exist)
./scripts/start.sh
```

Local scripts auto-detect free listen ports and cache them under `.accord-dev/`:
- Postgres: `5432`, Homebrew `postgresql.conf`, then `5433` (`pg.port`)
- Frontend: `5173`, then `5174`… (`frontend.port`) — skips ports already taken (e.g. Atlas)
- Backend: `8000`, then `8002`… (`backend.port`)

Set `PGPORT`, `FRONTEND_PORT`, or `BACKEND_PORT` to force a specific port.

`./scripts/dev-setup.sh` creates the simple `ACCORD_DB_USER` / `ACCORD_DB_NAME`
role and databases that `start.sh` expects, and also applies
`backend/scripts/create_roles.sql` so ADR DSNs in `backend/.env.example`
(`accord_app` / `accord_migrator`) work against the same app database.

### Docker Compose

```bash
cp deploy/.env.example deploy/.env   # fill required secrets (WorkOS, SESSION_SECRET_KEY, …)
docker compose -f deploy/docker-compose.yml up --build
```

Images: `ghcr.io/ornament-ai/accord/backend` and
`ghcr.io/ornament-ai/accord/web`. Local default web port is `8082`
(see Compose `web` service / `scripts/smoke-test.sh`).

## Verification

```bash
./scripts/verify.sh          # lint, typecheck, unit tests (skips missing lanes)
./scripts/smoke-test.sh      # health checks against a running deploy (default http://127.0.0.1:8082)
```

## Current status

Gates are defined in [`docs/release-acceptance.md`](docs/release-acceptance.md)
(letters A–F, H–K; **there is no gate G**). Status below reflects Phase 0 / product
lanes landed in-tree; Gate K (deploy/restore/E2E) is the active release gate.

| Gate | Status | One-line description |
| --- | --- | --- |
| A — Atlas baseline | Complete | Upstream Atlas shell/transplant baseline verified |
| B — Phase 0 contracts | Complete | Testing, threat model, release acceptance, security, ADRs, domain contracts |
| C — Transplant shell CI | Complete | Lint, typecheck, unit, and API smoke on FastAPI + React shell |
| D — Cross-tenant isolation | Complete | Forced RLS + no cross-tenant IDOR via API/services/storage/workers |
| E — Effective-dated master data | Complete | Hire/pay/org effective-dating across period boundaries |
| F — Calculation correctness | Complete | Synthetic totals + Decimal-only payroll domain (no float) |
| H — Workflow integrity | Complete | Maker/checker, post, idempotency, posted SQL immutability |
| I — Export durability | Complete | S3-compatible artifacts endure; tenant object isolation |
| J — Reports & reconciliation | Complete | Shared DTO for Excel/PDF; reconciliation to posted source |
| K — Deploy / restore / E2E | In progress | Tag deploy workflow, clean-env deploy, backup/restore RLS, Playwright |

## Docs

| Doc | Description |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Runtime components, workflow state machine, tenancy, report pipeline |
| [docs/payroll-domain.md](docs/payroll-domain.md) | Payroll domain glossary and gross-to-net model |
| [docs/release-acceptance.md](docs/release-acceptance.md) | Release gate matrix (A–K) and evidence requirements |
| [docs/security.md](docs/security.md) | Security controls, roles, and operational expectations |
| [docs/testing.md](docs/testing.md) | Test strategy and gate → suite mapping |
| [docs/threat-model.md](docs/threat-model.md) | Threat model for tenancy, workflow, and exports |
| [docs/atlas-upstream-manifest.md](docs/atlas-upstream-manifest.md) | Atlas upstream pin, inclusions, and exclusions |
| [docs/report-specs/report-catalog.md](docs/report-specs/report-catalog.md) | First-release report catalog and reconciliation rules |
| [docs/adr/0001-tenancy-rls-database-roles.md](docs/adr/0001-tenancy-rls-database-roles.md) | Tenancy, RLS, database roles |
| [docs/adr/0002-workos-authentication-sessions.md](docs/adr/0002-workos-authentication-sessions.md) | WorkOS authentication and sessions |
| [docs/adr/0003-backend-bootstrap-environment.md](docs/adr/0003-backend-bootstrap-environment.md) | Backend bootstrap and environment |
| [docs/adr/0004-organization-url-session-context.md](docs/adr/0004-organization-url-session-context.md) | Organization URL and session context |
| [docs/adr/0005-effective-dated-master-data.md](docs/adr/0005-effective-dated-master-data.md) | Effective-dated master data |
| [docs/adr/0006-money-decimal-rounding.md](docs/adr/0006-money-decimal-rounding.md) | Money, decimal, and rounding policy |
| [docs/adr/0007-payroll-run-calculation-model.md](docs/adr/0007-payroll-run-calculation-model.md) | Payroll run calculation model |
| [docs/adr/0008-command-workflow-idempotency.md](docs/adr/0008-command-workflow-idempotency.md) | Command workflow and idempotency |
| [docs/adr/0009-audit-outbox.md](docs/adr/0009-audit-outbox.md) | Append-only audit log and transactional outbox |
| [docs/adr/0010-jobs-object-storage.md](docs/adr/0010-jobs-object-storage.md) | Durable jobs queue and object storage |
