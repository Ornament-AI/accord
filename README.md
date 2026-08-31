# Accord

Open-source payroll for local governments and public works teams.

Keep one official pay record per employee. Enter dated changes once. Each month,
handle only the exceptions. One person prepares the bill, another approves it,
then the run posts and locks. From that locked run, Accord builds the Excel and
PDF files the office already files.

<p align="center">
  <img src="docs/images/login.jpg" alt="Accord login screen" width="820" />
</p>

Latest release: [`v0.4.5`](https://github.com/Ornament-AI/accord/releases/tag/v0.4.5) ·
License: [Apache-2.0](LICENSE)

---

## Who it is for

Payroll clerks, finance officers, and IT staff in municipal bodies and public
works departments. If salaries still live in spreadsheets, and an auditor asking
"what was paid and who approved it?" means opening a folder of workbooks, this
is the replacement.

A government pay run is more than gross minus tax. Depending on the state and
the employee's start date, one month can involve GPF, NPS/DCPS, income tax,
professional tax, HBA recoveries, and accommodation licence fees. Each has its
own rules, effective dates, and remittance report.

## What you do in Accord

```mermaid
flowchart LR
  A[Keep master data<br/>dated versions] --> B[Open monthly pay run]
  B --> C[Enter exceptions only]
  C --> D[Calculate]
  D --> E[Maker submits]
  E --> F[Checker approves]
  F --> G[Post and lock]
  G --> H[Export 18-sheet workbook]
```

1. **Master data.** Employees, offices, posts, pay components, and report
   defaults live in Accord. Raises and postings are dated versions, not silent
   overwrites.
2. **Monthly run.** Create the period, confirm the roster, add one-time
   exceptions, calculate.
3. **Maker / checker.** Submit and approve are separate roles. The same person
   cannot finish both steps.
4. **Post.** The run freezes. Mistakes are fixed by withdrawing before post, or
   reversing after. You do not edit last month in place.
5. **Reports.** From a posted run, export one canonical Excel workbook (18
   sheets): pay bill, bank advice, GPF/NPS schedules, recoveries, and the rest.

<p align="center">
  <img src="docs/images/employees.png" alt="Employees list with seeded roster" width="820" />
</p>

<p align="center">
  <img src="docs/images/pay-run-detail.png" alt="Calculated June 2026 pay run" width="820" />
</p>

<p align="center">
  <img src="docs/images/employee-detail.png" alt="Employee profile with as-of dating" width="820" />
</p>

<p align="center">
  <img src="docs/images/reports.png" alt="Reports workspace for pay-bill export" width="820" />
</p>

## Hard rules

These are product constraints, not style preferences.

| Rule | In practice |
| --- | --- |
| System of record | Accord holds the facts. There is no spreadsheet import that becomes the real source of truth. |
| Exact money | PostgreSQL `NUMERIC` and Python `Decimal` end to end. The API sends money as decimal strings. `float` is banned from payroll domain code. |
| Temporal truth | Master data changes are dated versions. A posted run stores the version ids and snapshots it used. |
| Immutable posting | Posted results are never edited or deleted. Withdraw before post, or reverse after. |
| Single organization | Each deployment serves one organization ([ADR 0011](docs/adr/0011-single-organization.md)). |
| Transactional evidence | Every business change commits with an append-only audit event and an outbox event. |

## Pay-run statuses

```mermaid
stateDiagram-v2
  [*] --> draft: create run
  draft --> calculating: calculate
  calculating --> calculated: done
  calculated --> calculating: calculate again
  calculated --> submitted: submit
  submitted --> calculated: withdraw
  submitted --> approved: approve
  submitted --> rejected: reject
  approved --> posted: post
  posted --> reversed: reverse
```

Validate is read-only and does not change status. Reject is a dead end in the
current code. Reverse creates a linked draft counter-record. Details and ADR
mismatches live in [`docs/architecture.md`](docs/architecture.md).

## Stack and runtime shape

| Piece | Role |
| --- | --- |
| React + TypeScript (Vite) | Browser UI |
| FastAPI (Python 3.14) | API, calculate, workflow, posting |
| PostgreSQL 18 | System of record, jobs, audit, outbox (forced RLS) |
| Worker process | Report generation jobs |
| MinIO / S3 | Export artifact storage |
| WorkOS | Production sign-in (local uses `DEV_AUTH_BYPASS`) |
| Docker Compose | Self-hosted full stack |

```mermaid
flowchart LR
  Browser[Browser SPA] -->|Vite proxy or nginx /api| API[FastAPI]
  API --> PG[(PostgreSQL)]
  API -->|WorkOS or DEV_AUTH_BYPASS| Auth[Identity]
  API -->|enqueue report job| Jobs[(jobs)]
  Worker[worker.py] -->|claim job| Jobs
  Worker --> PG
  Worker -->|put bytes| S3[(MinIO / S3)]
  Browser -->|download artifact| API
  API --> S3
```

Local `./scripts/start.sh` runs the API and the Vite app only. It does **not**
start the worker or MinIO. Use Docker Compose when you need report export end to
end.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI app, payroll engine, Alembic migrations, worker, tests |
| `frontend/` | React SPA (Vite, Biome, Vitest, Playwright) |
| `deploy/` | Docker Compose, images, nginx, local MinIO |
| `docs/` | Architecture, ADRs, domain, ops, security, report specs |
| `docs/images/` | README screenshots |
| `scripts/` | Bootstrap, start/stop, verify, provision, seed, screenshot capture |
| `fixtures/sanitized/` | Synthetic golden data only (no real PII) |

## Quick start (local development)

You need:

1. **pnpm 12.1.0.** Version pinned in root `package.json` (`packageManager`)
2. **Node.js 24** (CI); the frontend also supports Node 22.22.2+ and 26+
3. **Python 3.14.** Same as CI
4. **PostgreSQL 18** running locally

Then from the repository root:

```bash
# 1. Frontend workspace deps
pnpm install

# 2. Databases, ADR-0001 roles, and backend/.venv
./scripts/dev-setup.sh
# If Postgres is not running yet on macOS Homebrew:
# ./scripts/dev-setup.sh --start

# 3. API + Vite (also runs alembic upgrade head)
./scripts/start.sh
```

Ports are chosen automatically and stored under `.accord-dev/`:

| Service | Default, then next free |
| --- | --- |
| Postgres | `5432` → Homebrew port → `5433` |
| Frontend | `5173` → `5174` … |
| Backend | `8000` → `8002` … |

Override with `PGPORT`, `FRONTEND_PORT`, or `BACKEND_PORT`.

Stop the app with `./scripts/stop.sh` (Postgres is left running). Check URLs with
`./scripts/status.sh`.

### First sign-in

Local dev sets `DEV_AUTH_BYPASS=true`. Any password works on the login form. The
session identity comes from `DEV_AUTH_EMAIL` (default `dev@accord.local`).

The deployment still needs its one organization. That is a CLI step by design
([ADR 0011](docs/adr/0011-single-organization.md)):

```bash
PGPORT="$(tr -d '[:space:]' < .accord-dev/pg.port)"
DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:${PGPORT}/accord" \
  ENVIRONMENT=development DEV_AUTH_BYPASS=true \
  SESSION_SECRET_KEY=dev-only-local-session-secret ACCORD_ALLOW_WEAK_SECRETS=1 \
  backend/.venv/bin/python scripts/provision_organization.py \
  --name "My Org" --slug my-org --admin-email dev@accord.local
```

Use the same email as `DEV_AUTH_EMAIL`. Until this runs, the UI shows
"Deployment Not Ready".

Then open the Frontend URL from `./scripts/status.sh` and sign in. You land as
an organization administrator.

### Optional: seed the June 2026 demo

Loads 32 synthetic employees, offices, pay components, and recurring items
(from `fixtures/sanitized/june-2026`). The org must already exist and must have
**no employees** yet:

```bash
BACKEND_PORT="$(tr -d '[:space:]' < .accord-dev/backend.port)"
backend/.venv/bin/python scripts/seed_june_fixture.py \
  --base-url "http://127.0.0.1:${BACKEND_PORT}"
```

In the UI: create a June 2026 pay run, select and save the roster, calculate.
Totals match the golden fixture used in tests.

To regenerate the README screenshots after seeding:

```bash
node scripts/capture-readme-screenshots.mjs
```

### Prepare a canonical payroll export

New exports use the normalized v3 workbook contract. Before you calculate for
export, complete **Report readiness**:

1. **Pay Components → Report defaults.** Organization identity, office address,
   DDO/treasury details, account heads, bank-advice recipient, GPF remittance
   destinations, fund/plan labels, signatories.
2. **Organization → Posts.** Sanctioned strength, vacancies, pay scale, and
   export order for every post in the run.
3. Map every amount-bearing pay component to its **Pay Bill column**.
4. Complete each employee's applicable PAN, retirement account, salary bank,
   export remark, advance, and accommodation fields. Leave unknown optional
   identity values blank; do not invent them.
5. On the pay run, enter amounts for exceptions and one-time items (or a
   replacement rate for an override), with reason and service period when
   needed. Complete bill, advice, approval, token, and voucher metadata.

Calculate again after changing any of these facts so the immutable snapshot
includes them. Post the run, open **Reports**, clear every readiness issue, then
**Export**. You get one 18-sheet `.xlsx` workbook. See the
[canonical export contract](docs/report-specs/canonical-export-contract.md).
The v2 ZIP remains only for legacy clients that request `template_version=v2`.

Full report export also needs the worker and object storage (Compose below).

## Quick start (Docker Compose)

Compose brings PostgreSQL, MinIO, API, worker, and the web image:

```bash
cp deploy/.env.example deploy/.env   # fill WorkOS, SESSION_SECRET_KEY, DB password, …
docker compose -f deploy/docker-compose.yml up --build
```

Images: `ghcr.io/ornament-ai/accord/backend` and
`ghcr.io/ornament-ai/accord/web`. Local web port is `8085` (see Compose `web`
and `scripts/smoke-test.sh`).

## Verify your setup

```bash
./scripts/verify.sh          # shell, backend, API drift, frontend, build gates
./scripts/smoke-test.sh      # health against a running Compose deploy (default :8085)
```

Backend pytest expects a database whose name contains `test`. From `backend/`:

```bash
TEST_DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord_test" \
  PYTHONPATH=. .venv/bin/pytest tests -q
```

`smoke-test.sh` targets the Compose web port, not the Vite dev server. Use
`./scripts/status.sh` for local URLs.

## Current status

Release gates are defined in
[`docs/release-acceptance.md`](docs/release-acceptance.md) (letters B–F and H–K;
there is no gate G). Evidence for the current tree is in
[`docs/release-readiness.md`](docs/release-readiness.md).

| Gate | Status | One-line description |
| --- | --- | --- |
| B. Contracts | Partial | Maintained documents exist; release sign-off is external evidence |
| C. CI | Met | Backend, migration, frontend, and Docker lanes are wired |
| D. Isolation | Met | Forced-RLS and adversarial fail-closed suites are present |
| E. Effective dating | Met | Model, service, migration, and RLS coverage is present |
| F. Calculations | Met | Synthetic golden totals, property tests, and the AST float guard are present |
| H. Workflow | Partial | Maker/checker, posting, reversal, and immutability are covered; calculate is not idempotent or audited |
| I. Export durability | Partial | Storage/artifact tests exist; no automated restore/object-persistence rehearsal |
| J. Reports | Met | Family, formatter, canonical-contract, and reconciliation suites are present |
| K. Deploy / restore / E2E | Partial | Release/deploy scripts and Playwright exist; visual regression and automated restore-RLS proof do not |

## Documentation

### New contributors

| Doc | Description |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Runtime components, workflow, tenancy, report pipeline |
| [docs/developer-reference.md](docs/developer-reference.md) | API, frontend routes, config, scripts, CI map |
| [docs/testing.md](docs/testing.md) | Test strategy and gate → suite mapping |
| [AGENTS.md](AGENTS.md) | Local/VM gotchas (Postgres, pytest DSN, org bootstrap) |

### Operators

| Doc | Description |
| --- | --- |
| [docs/operations.md](docs/operations.md) | Deploy, backup/restore, day-two ops |
| [docs/release-acceptance.md](docs/release-acceptance.md) | Release gate matrix and evidence requirements |
| [docs/release-readiness.md](docs/release-readiness.md) | Current-tree evidence and open gaps |

### Domain and reports

| Doc | Description |
| --- | --- |
| [docs/payroll-domain.md](docs/payroll-domain.md) | Glossary and gross-to-net model |
| [docs/report-specs/report-catalog.md](docs/report-specs/report-catalog.md) | First-release report catalog |
| [docs/report-specs/canonical-export-contract.md](docs/report-specs/canonical-export-contract.md) | Sheet and formula rules for the v3 workbook |

### Security

| Doc | Description |
| --- | --- |
| [docs/security.md](docs/security.md) | Controls, roles, operational expectations |
| [docs/threat-model.md](docs/threat-model.md) | Tenancy, workflow, and export threats |
| [docs/adr/](docs/adr/) | Architecture decision records 0001–0011 |

## License

Apache-2.0. See [LICENSE](LICENSE).
