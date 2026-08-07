# Changelog

Notable released changes are summarized here. Git tags and their commits are
the authoritative release boundaries.

## Unreleased

- Upgrade the frontend compiler to TypeScript 7.0.2 while isolating the OpenAPI
  generator on its compatible TypeScript runtime.

## 0.4.3 — 2026-07-22

- Add the normalized canonical payroll export and its fixed 18-sheet workbook.
- Enforce report-readiness requirements before canonical generation.
- Reject incomplete accommodation breakdowns and refresh readiness after
  calculation.

## 0.4.2 — 2026-07-20

- Reconcile architecture, ADR, security, testing, operations, payroll-domain,
  and report documentation with the refactored service layout.
- Split calculation and pay-setup services along their ownership boundaries,
  batch effective-dated lookups, and simplify frontend API modules.
- Close onboarding, local URL, report, and review-boundary gaps.

## 0.4.1 — 2026-07-20

- Add Accord-owned WorkOS password and magic-code login flows.
- Return Problem Detail responses for provider misconfiguration and login
  failures.
- Scope CI work by changed backend/frontend lanes.

## 0.4.0 — 2026-07-20

- Add catalog-driven report exports with immutable identity, bank, and
  presentation snapshots.
- Reconcile gross adjustments and protect report snapshots from runtime DML.
- Add the report preview/export user experience.

## 0.3.1 — 2026-07-20

- Make the production deploy path safe for a clean first install.

## 0.3.0 — 2026-07-20

- Add the immutable-SHA MSIDC deployment workflow and provisioning helpers.
- Add singleton-organization provisioning, invitations, payroll-run rosters,
  report previews, and audited report access.
- Harden roster integrity, legacy schema removal, and deployment validation.

## 0.2.1 — 2026-07-19

- Bootstrap restricted database roles during release migration replay.

## 0.2.0 — 2026-07-19

- Separate off-bill employer remittance from treasury net payable and employee
  disbursement.
- Extend structured audit history and harden pay-setup and payroll UI behavior.

## 0.1.0 — 2026-07-18

First product cut of Accord: application shell plus Phase 0–5 payroll
platform (tenancy through reports and operations).

### Stack

- Initial backend infrastructure (`52589ea`) and frontend design system / app
  shell (`c5970b0`).
- Stack pins (read from repo files on 2026-07-18):
  - **Python** 3.14.6 (`backend/Dockerfile`); Ruff target py313 (`pyproject.toml`)
  - **FastAPI** 0.139.0, **SQLModel** 0.0.39, **SQLAlchemy** 2.0.51,
    **Alembic** 1.18.5, **uvicorn** 0.50.0, **structlog** 26.1.0,
    **WorkOS** 9.1.0, **boto3** 1.43.51, **openpyxl** 3.1.5, **fpdf2** 2.8.7,
    **prometheus-client** 0.25.0 (`backend/requirements.txt`)
  - **pytest** 9.1.1, **pytest-asyncio** 1.4.0, **ruff** 0.15.20,
    **httpx** 0.28.1 (`backend/requirements-dev.txt`)
  - **Node** ≥22.22.0 (engines); CI/Docker Node **24.18.0**; **pnpm** 10.34.3
    (root `package.json` `packageManager`)
  - **React** / **react-dom** 19.2.7, **Vite** 8.1.0, **Vitest** 4.1.9,
    **Tailwind** 4.3.1, **TanStack Query** 5.101.2, **Playwright** 1.61.1,
    TypeScript via `typescript-7` 7.0.1-rc (`frontend/package.json`)
  - **Postgres** 18.4-alpine, **nginx** 1.30-alpine (`deploy/docker-compose.yml`,
    `deploy/Dockerfile.web`)

### Tenancy / auth

- Identity & tenancy tables with forced RLS — migration `c8d4e2f1a9b7`
  (`813e8ae`); async Alembic bootstrap, tenant mixins, DB roles (`a6e0006`).
- WorkOS auth skeleton, signed sessions, auth routes (`c5136ab`); durable DB
  sessions, memberships, capabilities, tenant context (`0fd5b2f`); durable
  WorkOS webhook dedup on `webhook_events` (`216b6be`).
- Frontend real auth flow, organization switcher, capability-aware navigation
  (`645a0b3`); OpenAPI type generation wired (`33a108a`).
- Adversarial cross-tenant isolation matrix (`33bb895`).
- **Single-organization product (ADR 0011):** singular `/me` (`access_state` /
  organization / membership); CLI-only bootstrap and member provisioning
  (`scripts/provision_organization.py`, `scripts/provision_member.py`);
  invitations claimed on login; singleton unique index on `organizations`;
  removed switch/create-org HTTP surface.

### Master data

- Phase 3 effective-dated schema — migration `2f397740f38a` (`c63b7b8`).
- Employee master-data API with shared effective-dating helpers (`bf15079`);
  offices/units/posts/groups API (`f6528ec`); pay-component catalog,
  recurring instructions, advances, accommodation, report config (`e3a0381`).
- Frontend: org-setup, employees, pay-components, employee payroll-setup tabs
  (`d328fa1`, `263fea3`, `3b7f9d2`, `58c12dc`, `fbcf761`).

### Calculation engine

- Exact-decimal `Money`/`Rate`, rounding registry, no-float guard (`884e92d`).
- Deterministic payroll calculation engine with June 2026 golden proof
  (`c2e3c7f`); sanitized June 2026 fixture with exact aggregates (`96ee1f5`).
- Calculate command: master-data resolution → immutable run version (`ae2296d`);
  payroll validation severity model (`e0b6300`); Indian amount-in-words / INR
  grouping formatters (`62bc4a8`).
- Payroll run persistence — migration `021faa7dd776` (`3726b5f`); periods/runs/
  draft-input API (`591f00f`).

### Workflow / posting

- Organization-scoped command idempotency (`577690d`, ADR 0008).
- Validate / submit / withdraw / approve / reject (`aae10fe`); post / reverse
  with single-transaction evidence (`299aff7`).
- Transactional outbox (`ef458c6`); audit-event read API (`da943ea`).
- Frontend pay-run list/detail/calculate + workflow action bar (`45cafd8`,
  `97ec8bc`); results-read API (`831b116`).
- Fixes: payroll input upsert 500 and idempotent-command RLS 404; auth-race
  guard (`fec03ad`).

### Jobs / storage

- Object-storage and durable-job protocols + in-memory impls (`78c586c`);
  S3-compatible adapter with MinIO integration tests (`689cbbc`).
- PostgreSQL job queue (`FOR UPDATE SKIP LOCKED`) (`6fd8db0`); worker process
  with per-org claim loop (`4932fd8`).
- Phase 5 platform tables — migration `a9f3c2e81b04` (`2156b93`).
- Export-artifact lifecycle + audited download (`c364164`); artifacts router
  registered (`789d8ea`).

### Reports

- Shared report DTO registry, safe Excel writer, PDF renderer (`06c0b77`).
- Families: payroll register (`42b6634`), payments (`7db8ef3`), statutory
  (`68dbc87`), approval-note (`147481c`), retirement (`704d63e`), recovery
  (`ae7aed7`).
- Durable report-generation pipeline (request API, job handler, artifact reuse)
  (`7399b4c`); platform assembly + UI routes (`d95528f`).
- PDF totals-row fix; Noto fonts + OFL (`aa2bb1f`).
- June golden end-to-end through the full HTTP stack (`c9bcbb1`).

### Dashboard / ops

- Removed the pre-release payroll dashboard API and frontend in favor of
  capability-aware workflow landing pages.
- Prometheus metrics, readiness depth, structured-log redaction (`282e2ef`).
- Compose/nginx/MinIO/dev scripts/CI (`ea8098c`); release workflow, architecture
  doc, README quick start (`d228281`).
- Playwright critical-path suite with axe accessibility checks (`84c075d`).

### Verification

- Canonical local gate: `./scripts/verify.sh` (see `docs/release-readiness.md`
  §Test totals). Do not treat this changelog as a live test-count source.
