# Testing

This page explains how Accord is tested and how to run the tests yourself.
It defines the test pyramid, the conventions, the sanitized fixture policy,
and the gate → suite mapping for release acceptance. Cross-ref:
[release-acceptance.md](release-acceptance.md),
[threat-model.md](threat-model.md), [security.md](security.md).

Every path below is checked against the current tree. Missing controls are
described as gaps instead of being represented by paths that do not exist.

## How to run everything

The canonical local check is one script, run from the repo root:

```bash
./scripts/verify.sh
```

It runs these steps in order: shell syntax checks (`bash -n` over `scripts/`
and `deploy/`); backend lint (`ruff check` and `ruff format --check`); the
full backend pytest suite; the generated API type drift check
(`scripts/generate-api-types.sh` plus a `git diff` on
`frontend/src/types/api.generated.ts`); then frontend lint, format check,
typecheck, Vitest tests, and the production build. Any failing step fails
the whole script. A step whose inputs are missing prints a `skip:` line.

You can also run the pieces directly:

```bash
# Backend tests (needs a local PostgreSQL; see below)
backend/.venv/bin/python -m pytest backend/tests -q

# Frontend checks (pnpm workspace, from repo root)
pnpm --filter frontend lint
pnpm --filter frontend typecheck
pnpm --filter frontend test:run

# Browser end-to-end tests (start the stack yourself first;
# see frontend/e2e/README.md for full setup)
pnpm --filter frontend e2e
```

Backend tests need a real PostgreSQL database. `backend/tests/conftest.py`
reads `TEST_DATABASE_URL` (default: the `accord` dev role on a local
`accord_test` database at port 5432) and refuses any database whose name does
not contain `test`. `scripts/dev-setup.sh` creates the databases and ADR-0001
roles. If setup selected another PostgreSQL port, run the backend command as:

```bash
PGPORT="$(tr -d '[:space:]' < .accord-dev/pg.port)"
TEST_DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:${PGPORT}/accord_test" \
  backend/.venv/bin/python -m pytest backend/tests -q
```

CI (`.github/workflows/ci.yml`) runs backend/frontend equivalents plus
migration and image-build jobs. The `backend`
job runs ruff and pytest against a Postgres 18 service container. The
`migrations` job runs `alembic upgrade head` plus `alembic check` on a fresh
database. The `frontend` job runs lint, format, typecheck, test, and build.
Two more jobs build the backend and web Docker images. On pull requests,
jobs are skipped when their lane did not change. Shell-syntax validation and
generated API-type drift remain local `verify.sh` checks; the hosted
`api-type-drift` job is a visible placeholder and does not enforce drift.

## Test pyramid

### Backend domain (unit)

Pure payroll logic lives under `backend/tests/domain/`. These tests need no
database.

- Money is `Decimal` (or integer minor units) — never float. Suites:
  `backend/tests/domain/test_money.py`, `test_rounding.py`, `test_rates.py`.
- Calculation invariants use Hypothesis property tests (Hypothesis generates
  many random inputs and checks that a rule always holds):
  `backend/tests/domain/test_money_properties.py`.
- Engine behavior: `test_calculators.py`, `test_engine.py`, and the June 2026
  golden engine suite `test_engine_june_golden.py`.
- Float ban: `backend/tests/domain/test_no_float_guard.py` runs an AST
  scanner (`_float_guard.py`) over `backend/app/domain` and fails on any
  float literal, `float(...)` call, or `float` annotation (ADR 0006). This
  replaces the `scripts/ci/no_float_payroll_domain.sh` script named in the
  original contract; that script was never added.

### Service tests (real PostgreSQL)

- Service-layer tests live under `backend/tests/services/` (workflow,
  calculation, posting, pay setup, versioning, idempotency, identity,
  outbox, artifacts, report generation, and more).
- They run against **real PostgreSQL** via `TEST_DATABASE_URL`.
- **Forbidden:** SQLite, in-memory substitutes, or mocked DB engines for any
  test that exercises persistence, RLS, constraints, triggers, JSONB, or
  `numeric` precision.
- **Why real Postgres:** forced RLS (`ALTER TABLE ... FORCE ROW LEVEL
  SECURITY`), real CHECK/UNIQUE/FK constraints, JSONB operators, and
  `numeric`/`Decimal` precision do not match SQLite or mocks.

### API tests

- httpx clients against the real FastAPI app wired to real PostgreSQL.
- Suites: `backend/tests/api/`; session and capability internals under
  `backend/tests/auth/`.
- They cover auth session binding, capability checks at the API layer
  (`test_deps_capabilities.py`), and org context (`SET LOCAL` per-request
  tenant context, `test_tenant_context.py`). They also cover the command
  surfaces (`calculate`, `submit`, `withdraw`, `approve`, `reject`, `post`,
  `reverse`) in `test_run_commands.py`, `test_run_workflow.py`, and
  `test_run_posting.py`.

### Migration tests

- Fresh-DB Alembic replay to head:
  `backend/tests/migrations/test_fresh_upgrade.py`, plus per-phase schema
  suites (`test_phase2_identity_tenancy.py` … `test_phase5_platform.py`)
  and `test_singleton_organization.py`.
- Migration drift is checked in CI: the `migrations` job runs
  `alembic check` after `alembic upgrade head`. The originally named files
  `test_alembic_chain.py` and `test_migration_drift.py` do not exist; this
  is where that coverage actually lives.
- The migrator role is `accord_migrator` (schema/migrations; may
  `BYPASSRLS`). Runtime proof uses `accord_app` / `accord_worker`
  (`NOSUPERUSER NOBYPASSRLS` runtime roles). Tests bootstrap these roles
  via `ensure_accord_roles` in `backend/tests/migrations/conftest.py`.

### RLS / fail-closed isolation

Single-organization product ([ADR 0011](adr/0011-single-organization.md)):
suites seed **one** org and prove that an empty or wrong GUC returns zero
rows. A second `organizations` insert must fail the singleton unique index
(`backend/tests/migrations/test_singleton_organization.py`).

- Dedicated RLS suites under `backend/tests/rls/`:
  `test_identity_tenancy_rls.py`, `test_master_data_rls.py`,
  `test_payroll_run_rls.py`, `test_platform_rls.py`,
  `test_rls_helper_sql.py`, and `test_immutable_grants.py`.
- Gate D adversarial suites live under `backend/tests/gate_d/`:
  `test_sql_isolation.py`, `test_http_isolation.py`,
  `test_capability_matrix.py`, `test_session_adversarial.py`, and
  `test_unauthenticated_sweep.py`.
- Tests connect as the restricted runtime role (`accord_app`), **not**
  superuser and **not** a `BYPASSRLS` role. Tenant context is applied with
  `SET LOCAL` (`app.organization_id` and related transaction-local GUCs).

### Master data and calculations

- Effective-dated versioning: `backend/tests/services/test_versioning.py`,
  `backend/tests/models/test_master_data_models.py`, and
  `backend/tests/rls/test_master_data_rls.py`.
- June 2026 synthetic totals (sanitized fixtures only, from
  `fixtures/sanitized/june-2026/`): engine-level in
  `backend/tests/domain/test_engine_june_golden.py`, and full-stack in
  `backend/tests/e2e/test_june_golden_e2e.py` (create → calculate → submit
  → approve → post against `expected_totals.json`).

### Workflow (maker/checker, post, idempotency)

- Maker/checker and transitions:
  `backend/tests/services/test_run_workflow.py`,
  `backend/tests/api/test_run_workflow.py`.
- Posting, reversal, and posted immutability:
  `backend/tests/services/test_run_posting.py`,
  `backend/tests/api/test_run_posting.py`.
- Idempotency keys: `backend/tests/services/test_idempotency.py`.
- SQL-level immutability (DML revoked on immutable tables):
  `backend/tests/rls/test_immutable_grants.py`.

### Reports

- Per-family suites under `backend/tests/reports/`:
  `test_payroll_register.py`, `test_payments_reports.py`,
  `test_retirement_reports.py`, `test_statutory_reports.py`,
  `test_recovery_reports.py`, `test_approval_note.py`.
- Formatter and shared plumbing: `test_excel.py`, `test_pdf.py`,
  `test_pdf_fonts.py`, `test_formatting.py`, `test_amount_in_words.py`,
  `test_report_base.py`, `test_product_sheets.py`.
- Excel checks are semantic (openpyxl cell values and aggregates), not byte
  diffs. Reconciliation against posted source data is asserted inside the
  family suites and the June e2e golden test. The originally named files
  (`test_excel_golden.py`, `test_pdf_golden.py`, `test_excel_pdf_parity.py`,
  `test_reconciliation.py`) do not exist under those names.

### Jobs and object storage

- Durable job queue: `backend/tests/jobs/test_postgres_queue.py`,
  `test_job_queue_state_machine.py`, `test_worker.py`.
- Object storage contract (round trips, checksums, missing keys, fault
  injection, key validation):
  `backend/tests/storage/test_object_storage_protocol.py` and
  `backend/tests/storage/test_s3_adapter.py`.
- The originally named `test_export_durability.py` and
  `test_tenant_object_isolation.py` do not exist; durability behaviors live
  in the protocol/adapter suites, and org-scoped artifact access is covered
  by `backend/tests/api/test_artifacts.py`.

### Security-relevant suites

There is no `backend/tests/security/` directory. Current coverage:

- Session hardening and cookies: `backend/tests/auth/test_session.py`,
  `backend/tests/gate_d/test_session_adversarial.py`.
- WorkOS webhook signature verification:
  `backend/tests/api/test_webhooks_workos.py`.
- Privilege escalation / capability matrix:
  `backend/tests/gate_d/test_capability_matrix.py`,
  `backend/tests/api/test_deps_capabilities.py`.
- PII masking and capability-gated reveal (`reveal_sensitive_fields`):
  `backend/tests/api/test_employees.py`,
  `backend/tests/services/test_employees.py`. The reveal read is not yet
  audit-logged.
- Log redaction: `backend/tests/test_log_redaction.py`.
- Posted SQL immutability: `backend/tests/rls/test_immutable_grants.py`.
- Deploy hardening contract: `backend/tests/ops/test_msidc_deploy_contract.py`.
- Not yet landed (named in the original contract): a dedicated CSRF
  synchronizer-token suite, a support break-glass suite, and a
  backup/restore RLS rehearsal suite.

### Frontend

- Vitest component and unit tests: `frontend/src/**/*.test.ts(x)`, run with
  `pnpm --filter frontend test:run`. API mocking uses MSW handlers under
  `frontend/src/test/msw/` (server in `frontend/src/test/msw-server.ts`).
- Playwright critical paths against the real local stack (see
  `frontend/e2e/README.md` for setup and the `accord_e2e` database):
  `frontend/e2e/auth-and-org.spec.ts`, `frontend/e2e/master-data.spec.ts`,
  `frontend/e2e/payroll-flow.spec.ts` (run creation and maker/checker
  denial), `frontend/e2e/reports.spec.ts` (empty state; generation/download
  is explicitly skipped because one dev identity cannot produce a posted run).
- Accessibility (axe-core): `frontend/e2e/axe-a11y.spec.ts`.
## Conventions

1. **No skip-to-green.** Do not use skip / xfail / conditional disable just
   to make a gate pass. Skips require justification and a tracked issue.
2. **Deterministic seeds.** Hypothesis profiles, faker seeds, and factories
   must be reproducible across local and CI runs.
3. **Real PostgreSQL wherever the DB matters.** SQLite is forbidden for
   backend persistence, RLS, migration, workflow, storage metadata, and
   security DB tests.
4. **Sanitized fixtures only** for the June 2026 reference payroll (see
   below).
5. **Append-only audit.** Workflow and security tests assert append-only
   audit log tables (`audit_events`) and reject silent mutation.

## Gate → suite mapping

Gates are **B, C, D, E, F, H, I, J, K**. There is no gate G. The lettering
matches [release-acceptance.md](release-acceptance.md); the suite paths below
are the current tree.

| Gate | Name | Named suites / checks (current tree) |
| --- | --- | --- |
| **B** | Phase 0 contracts | Review checklist against `docs/testing.md`, `docs/threat-model.md`, `docs/release-acceptance.md`, `docs/security.md`, ADRs, and payroll-domain contracts |
| **C** | CI | Lint, typecheck, unit, and API smoke: `backend/tests/domain/`, `backend/tests/api/`, `backend/tests/services/`, `frontend/src/**/*.test.ts(x)` (`.github/workflows/ci.yml`) |
| **D** | Fail-closed RLS isolation | `backend/tests/gate_d/`, `backend/tests/rls/`, plus API/services/storage/worker paths that prove empty/wrong GUC returns zero rows under `accord_app` (singleton org; ADR 0011) |
| **E** | Effective-dated master data | `backend/tests/services/test_versioning.py`, `backend/tests/models/test_master_data_models.py`, `backend/tests/rls/test_master_data_rls.py` |
| **F** | Calculation correctness | `backend/tests/domain/test_engine_june_golden.py`, `backend/tests/e2e/test_june_golden_e2e.py`, `backend/tests/domain/test_money_properties.py`, `backend/tests/domain/test_money.py`, `backend/tests/domain/test_no_float_guard.py` |
| **H** | Workflow integrity | `backend/tests/services/test_run_workflow.py`, `backend/tests/services/test_run_posting.py`, `backend/tests/services/test_idempotency.py`, `backend/tests/rls/test_immutable_grants.py` |
| **I** | Export durability & object isolation | `backend/tests/storage/`, `backend/tests/services/test_artifacts.py`, `backend/tests/api/test_artifacts.py` |
| **J** | Reports & reconciliation | `backend/tests/reports/` family suites + `backend/tests/e2e/test_june_golden_e2e.py` reconciliation assertions |
| **K** | Deploy / restore / E2E | `backend/tests/ops/test_msidc_deploy_contract.py`; clean-env deploy per [operations.md](operations.md); `scripts/backup-restore.sh`; `scripts/smoke-test.sh`; Playwright specs under `frontend/e2e/` |

## Sanitized fixture policy

### Real reference workbook — never in git

The real June 2026 reference payroll workbook contains **real PII**.
**Never** commit it to git in any form: fixtures, test data, git history,
CI logs, screenshots, or golden artifacts.

### Synthetic set: `fixtures/sanitized/june-2026/`

The committed fixture (`organization.json`, `employees.json`,
`components.json`, `pay.json`, `expected_totals.json`, checked by
`validate.py`) is fully synthetic. The rules:

| Rule | Requirement |
| --- | --- |
| Names | Deterministic synthetic names (seeded faker or fixed fake lookup). Never derived from or reversible to real names. |
| PAN / PRAN / GPF / bank | Syntactically valid but obviously fake (documented fake namespace / test ranges). |
| Structure | Preserve employee count, pay components, org hierarchy, and pay periods. |
| Totals | Keep numeric amounts per row identical; swap only identity/PII so aggregates stay exact for correctness tests without PII. |
| Format | Synthetic JSON input + golden JSON/Excel/PDF expected outputs only. |

### Pre-commit (fast)

The contract calls for fast local guards (no pre-commit config is committed
yet; these remain the policy for when it lands):

- Regex for PAN: `[A-Z]{5}[0-9]{4}[A-Z]`.
- Indian bank account / IFSC-style patterns where applicable.
- Denylist of known real names/orgs from the real reference file.
- Scan `fixtures/` and test data paths.
- Block known real-source filenames and content hashes.

### CI (expensive)

- A hash/name denylist guard for newly added fixtures is still missing from
  CI. Until it lands, reviewers must inspect fixture changes and run the
  synthetic validator; this is an acceptance gap, not an existing command.
- When implemented, the CI guard should complement the proposed fast local
  guard above; neither exists in the current tree.

## CSRF and session proof points

Documented decision (see [security.md](security.md),
[threat-model.md](threat-model.md)):

- HTTP-only + Secure + SameSite=Lax cookies (Lax is justified by the WorkOS
  redirect auth flow). The code sets these flags in
  `backend/app/auth/session.py` (`secure` only in production).
- SameSite=Lax session cookie **plus** a synchronizer CSRF token on
  state-changing routes (the header must match a server-issued token). The
  synchronizer-token half is still contract text. Today the code signs an
  anti-CSRF OAuth `state` value in `session.py`. No dedicated
  synchronizer-token middleware or test suite has landed.
- Lax covers the cross-site cookie sends on top-level navigations that the
  WorkOS AuthKit redirects need. Synchronizer tokens defend state-changing
  POSTs/PUTs/PATCHes/DELETEs against CSRF, including same-site adjacent
  risks.
- Current proof: `backend/tests/auth/test_session.py` and
  `backend/tests/gate_d/test_session_adversarial.py`. The originally named
  `test_csrf.py` / `test_session_hardening.py` files do not exist.

## Related controls under test

| Control | Primary suites |
| --- | --- |
| forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) | `backend/tests/rls/` per-domain suites; `backend/tests/rls/test_rls_helper_sql.py` |
| NOSUPERUSER NOBYPASSRLS runtime database role | `backend/tests/gate_d/test_sql_isolation.py`; role bootstrap in `backend/tests/migrations/conftest.py` |
| SET LOCAL per-request tenant context | `backend/tests/api/test_tenant_context.py`; RLS suites |
| WorkOS webhook signature verification | `backend/tests/api/test_webhooks_workos.py` |
| idempotency keys | `backend/tests/services/test_idempotency.py` |
| append-only audit log tables | workflow suites; `backend/tests/api/test_audit_read.py` |
| SQL immutability of posted data | `backend/tests/rls/test_immutable_grants.py` |
| capability/permission checks at the API layer | `backend/tests/gate_d/test_capability_matrix.py`, `backend/tests/api/test_deps_capabilities.py` |
| masked fields with capability-gated reveal | `backend/tests/api/test_employees.py`, `backend/tests/services/test_employees.py` (reveal audit remains a gap) |
| log redaction of sensitive fields | `backend/tests/test_log_redaction.py` |
