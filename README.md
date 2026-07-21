# Accord

Accord is an open-source payroll system of record. It is built for local
governments and public works teams. Teams keep employee and payroll facts in
one place. They record only dated changes and monthly exceptions. They
calculate and approve payroll with a maker/checker flow. They then create
export-ready Excel and PDF reports from posted, frozen data.

## Principles

- **System of record** — there is no spreadsheet import path. Accord holds
  the facts itself.
- **Exact money** — money uses PostgreSQL `NUMERIC` and Python `Decimal`.
  The API moves money as a plain decimal string. `float` is banned from
  payroll domain code.
- **Temporal truth** — master data changes are dated versions. A posted
  payroll keeps the exact version ids and snapshots it was built from.
- **Immutable posting** — posted results are never edited or deleted. To fix
  a mistake, withdraw before posting, or reverse after posting.
- **Single organization** — each deployment serves one organization
  ([ADR 0011](docs/adr/0011-single-organization.md)). Forced PostgreSQL
  row-level security stays in place as fail-closed kernel debt until Phase 2
  removes it.
- **Transactional evidence** — every business change commits together with an
  append-only audit event and an outbox event.

## Stack

The backend is FastAPI on Python with PostgreSQL. The frontend is React with
TypeScript. Sign-in uses WorkOS. Report files land in S3-compatible object
storage. Deployment is Docker Compose (self-hosted) or managed PostgreSQL
plus object storage.

## Repository layout

- `backend/` — FastAPI app, payroll engine, migrations, worker, tests
- `frontend/` — React app (design system carried over from Atlas)
- `deploy/` — Docker Compose, images, nginx, local MinIO profile
- `docs/` — architecture, ADRs, domain reference, report specs, security
- `fixtures/sanitized/` — synthetic test data only; real PII is never committed

## Quick start (local development)

You need four things installed first:

1. **pnpm 10.x** — see `packageManager` in the root `package.json`.
2. **Python 3.14** — the version CI uses.
3. **PostgreSQL 18** — running locally. (Or skip local setup and use Docker
   Compose; see the next section.)
4. **Node.js 22.22 or newer** — for the frontend.

Then run these three commands from the repository root:

```bash
# 1. Install frontend workspace dependencies.
pnpm install

# 2. One-time database and virtualenv setup. Creates the `accord` and
#    `accord_test` databases, the ADR-0001 roles, and backend/.venv.
./scripts/dev-setup.sh
# If Postgres is not running yet (macOS Homebrew):
# ./scripts/dev-setup.sh --start

# 3. Start the API and the Vite dev server. This also runs
#    `alembic upgrade head` for you.
./scripts/start.sh
```

The scripts pick free ports and remember them under `.accord-dev/`:

- Postgres: `5432`, then Homebrew's configured port, then `5433`
- Frontend: `5173`, then `5174`, and so on
- Backend: `8000`, then `8002`, and so on

Set `PGPORT`, `FRONTEND_PORT`, or `BACKEND_PORT` to force a port.

### First sign-in

Local dev runs with `DEV_AUTH_BYPASS=true`. Any email and password work on
the login form. The session identity comes from `DEV_AUTH_EMAIL` (default
`dev@accord.local`).

Before you can use the app, the deployment needs its one organization. This
is a CLI step by design ([ADR 0011](docs/adr/0011-single-organization.md)):

```bash
PGPORT="$(tr -d '[:space:]' < .accord-dev/pg.port)"
DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:${PGPORT}/accord" \
  backend/.venv/bin/python scripts/provision_organization.py \
  --name "My Org" --slug my-org --admin-email dev@accord.local
```

Run `./scripts/status.sh`, open the Frontend URL it prints, and sign in. You
land in the app as an organization administrator even when the default port
was busy.

### Optional: seed a full demo dataset

To explore with realistic data, load the synthetic June 2026 fixture
(32 employees, offices, pay components, recurring items):

```bash
BACKEND_PORT="$(tr -d '[:space:]' < .accord-dev/backend.port)"
backend/.venv/bin/python scripts/seed_june_fixture.py \
  --base-url "http://127.0.0.1:${BACKEND_PORT}"
```

Then create a payroll period and run in the UI, save the roster, and
calculate. The totals match the golden test fixture.

## Quick start (Docker Compose)

Compose brings its own PostgreSQL and MinIO, so nothing else is required:

```bash
cp deploy/.env.example deploy/.env   # fill required secrets (WorkOS, SESSION_SECRET_KEY, …)
docker compose -f deploy/docker-compose.yml up --build
```

Images: `ghcr.io/ornament-ai/accord/backend` and
`ghcr.io/ornament-ai/accord/web`. The local web port is `8085` (see the
Compose `web` service and `scripts/smoke-test.sh`).

## Verify your setup

```bash
./scripts/verify.sh          # lint, typecheck, unit tests (skips missing lanes)
./scripts/smoke-test.sh      # health checks against a running deploy (default http://127.0.0.1:8085)
```

## Current status

Release gates are defined in
[`docs/release-acceptance.md`](docs/release-acceptance.md) (letters A–F and
H–K; **there is no gate G**). Gate K (deploy/restore/E2E) is the active
release gate.

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
| [docs/operations.md](docs/operations.md) | Deploy, backup/restore, and day-two operations |
| [docs/release-acceptance.md](docs/release-acceptance.md) | Release gate matrix (A–K) and evidence requirements |
| [docs/security.md](docs/security.md) | Security controls, roles, and operational expectations |
| [docs/testing.md](docs/testing.md) | Test strategy and gate → suite mapping |
| [docs/threat-model.md](docs/threat-model.md) | Threat model for tenancy, workflow, and exports |
| [docs/atlas-upstream-manifest.md](docs/atlas-upstream-manifest.md) | Atlas upstream pin, inclusions, and exclusions |
| [docs/report-specs/report-catalog.md](docs/report-specs/report-catalog.md) | First-release report catalog and reconciliation rules |
| [docs/adr/](docs/adr/) | Architecture decision records 0001–0011 |

## Provenance

Accord transplants the design system and infrastructure conventions of the
Atlas application from a pinned upstream release tag. See
[`docs/atlas-upstream-manifest.md`](docs/atlas-upstream-manifest.md) for exact
provenance, exclusions, and licenses.

## License

Apache-2.0 — see [LICENSE](LICENSE).
