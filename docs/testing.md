# Testing

Accord Phase 0 testing contracts. Imperative, present-tense, path-concrete.
This document defines the pyramid, conventions, sanitized fixture policy, and
gate → suite mapping for release acceptance. Cross-ref:
[release-acceptance.md](release-acceptance.md), [threat-model.md](threat-model.md),
[security.md](security.md).

## Test pyramid

### Backend unit

- Pure domain logic lives under `backend/tests/unit/`.
- Money is `Decimal` (or integer minor units) — never float. Suite:
  `backend/tests/unit/test_money_decimal.py`.
- Calculation invariants use Hypothesis property tests: rounding modes,
  additivity of components, rejection of invalid negative pay components.
  Suite: `backend/tests/unit/test_calculation_invariants.py`.
- CI float ban: `scripts/ci/no_float_payroll_domain.sh`.

### Service tests (real PostgreSQL)

- Service-layer tests live under `backend/tests/services/`.
- They run against **real PostgreSQL** via `TEST_DATABASE_URL`.
- **Forbidden:** SQLite, in-memory substitutes, or mocked DB engines for any
  test that exercises persistence, RLS, constraints, triggers, JSONB, or
  `numeric` precision.
- **Why real Postgres:** forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`),
  real CHECK/UNIQUE/FK constraints and immutability triggers, JSONB operators,
  and `numeric`/`Decimal` precision do not match SQLite or mocks.

### API tests

- FastAPI `TestClient` / httpx against the real app wired to real PostgreSQL.
- Suites: `backend/tests/api/`.
- Cover auth session binding, capability/permission checks at the API layer,
  organization context (`SET LOCAL` per-request tenant context), and command
  surfaces (`calculate`, `submit`, `withdraw`, `approve`, `reject`, `post`,
  `reverse`).

### Migration tests

- Fresh-DB Alembic chain replay:
  `backend/tests/migrations/test_alembic_chain.py`.
- Migration drift (alembic check / empty autogenerate diff):
  `backend/tests/migrations/test_migration_drift.py`.
- Migrator role is `accord_migrator` (schema/migrations; may `BYPASSRLS`).
  Runtime proof uses `accord_app` / `accord_worker`
  (`NOSUPERUSER NOBYPASSRLS` runtime database role).

### RLS / fail-closed isolation

Single-organization product ([ADR 0011](adr/0011-single-organization.md)):
suites seed **one** org and prove empty/wrong GUC returns zero rows. A second
`organizations` insert must fail the singleton unique index. Gate D lives under
`backend/tests/gate_d/`.

- Dedicated suite under `backend/tests/rls/`.
- Forced RLS coverage (every tenant-scoped table has
  `ALTER TABLE ... FORCE ROW LEVEL SECURITY`):
  `backend/tests/rls/test_forced_rls_coverage.py`.
- Tests connect as the restricted runtime role (`accord_app`), **not**
  superuser and **not** a `BYPASSRLS` role. Tenant context is applied with
  `SET LOCAL` per-request tenant context (`app.organization_id` and related
  transaction-local GUCs).

### Master data and calculations

- Effective-dated master data:
  `backend/tests/master_data/test_effective_dating.py`.
- June 2026 synthetic totals (sanitized fixtures only):
  `backend/tests/calculations/test_june_2026_totals.py`.

### Workflow (maker/checker, post, idempotency)

- Maker/checker:
  `backend/tests/workflow/test_maker_checker.py`.
- Immutable posted `payroll_run_version`:
  `backend/tests/workflow/test_posted_immutability.py`.
- Idempotency keys:
  `backend/tests/workflow/test_idempotency.py`.
- Posted SQL immutability (triggers + direct SQL attempts):
  `backend/tests/security/test_posted_sql_immutability.py`.

### Reports

- Semantic Excel golden (openpyxl cell values, formulas, aggregates — **not**
  byte diffs): `backend/tests/reports/test_excel_golden.py`.
- PDF text extraction against expected values:
  `backend/tests/reports/test_pdf_golden.py`.
- Excel/PDF parity (one DTO / source of truth):
  `backend/tests/reports/test_excel_pdf_parity.py`.
- Reconciliation to source posted data:
  `backend/tests/reports/test_reconciliation.py`.

### Object storage

- Export durability:
  `backend/tests/storage/test_export_durability.py`.
- Tenant object key isolation:
  `backend/tests/storage/test_tenant_object_isolation.py`.

### Security suites

- `backend/tests/security/test_session_hardening.py`
- `backend/tests/security/test_csrf.py`
- `backend/tests/security/test_workos_webhooks.py`
- `backend/tests/security/test_privilege_escalation.py`
- `backend/tests/security/test_pii_masking.py`
- `backend/tests/security/test_support_break_glass.py`
- `backend/tests/security/test_posted_sql_immutability.py`
- `backend/tests/security/test_backup_restore_rls.py`

### Frontend

- Vitest component tests: `frontend/src/**/*.test.tsx`.
- Playwright critical paths:
  `frontend/e2e/critical-paths.spec.ts`
  (login, payroll run creation, approval/maker-checker, posting, report
  generation/download).
- Accessibility (axe-core): `frontend/e2e/a11y.spec.ts`.
- Atlas visual parity snapshots: `frontend/e2e/visual-shell.spec.ts`.

## Conventions

1. **No skip-to-green.** Do not use skip / xfail / conditional disable merely
   to make a gate pass. Skips require justification and a tracked issue.
2. **Deterministic seeds.** Hypothesis profiles, faker seeds, and factories
   must be reproducible across local and CI runs.
3. **Real PostgreSQL wherever the DB matters.** SQLite is forbidden for
   backend persistence, RLS, migration, workflow, storage metadata, and
   security DB tests.
4. **Sanitized fixtures only** for June 2026 reference payroll (see below).
5. **Append-only audit.** Workflow and security tests assert
   append-only audit log tables (`audit_events`) and reject silent mutation.

## Gate → suite mapping

Gates are **A, B, C, D, E, F, H, I, J, K**. There is no gate G.
Identical lettering in [release-acceptance.md](release-acceptance.md).

| Gate | Name | Named suites / checks |
| --- | --- | --- |
| **A** | Atlas baseline | `scripts/verify_atlas_baseline.sh` |
| **B** | Phase 0 contracts | Review checklist against `docs/testing.md`, `docs/threat-model.md`, `docs/release-acceptance.md`, `docs/security.md`, ADRs, and payroll-domain contracts |
| **C** | Transplant shell CI | Lint, typecheck, unit, and API smoke: `backend/tests/unit/test_money_decimal.py`, `backend/tests/unit/test_calculation_invariants.py`, `backend/tests/api/`, `backend/tests/services/`, `frontend/src/**/*.test.tsx` |
| **D** | Fail-closed RLS isolation | `backend/tests/gate_d/`, `backend/tests/rls/`, plus API/services/storage/worker paths that prove empty/wrong GUC returns zero rows under `accord_app` (singleton org; ADR 0011) |
| **E** | Effective-dated master data | `backend/tests/master_data/test_effective_dating.py` |
| **F** | Calculation correctness | `backend/tests/calculations/test_june_2026_totals.py`, `backend/tests/unit/test_calculation_invariants.py`, `backend/tests/unit/test_money_decimal.py`, `scripts/ci/no_float_payroll_domain.sh` |
| **H** | Workflow integrity | `backend/tests/workflow/test_maker_checker.py`, `backend/tests/workflow/test_posted_immutability.py`, `backend/tests/workflow/test_idempotency.py`, `backend/tests/security/test_posted_sql_immutability.py` |
| **I** | Export durability & object isolation | `backend/tests/storage/test_export_durability.py`, `backend/tests/storage/test_tenant_object_isolation.py` |
| **J** | Reports & reconciliation | `backend/tests/reports/test_reconciliation.py`, `backend/tests/reports/test_excel_golden.py`, `backend/tests/reports/test_pdf_golden.py`, `backend/tests/reports/test_excel_pdf_parity.py` |
| **K** | Deploy / restore / E2E | Clean-env deploy, restore rehearsal via `backend/tests/security/test_backup_restore_rls.py`, `frontend/e2e/critical-paths.spec.ts`, `frontend/e2e/a11y.spec.ts`, `frontend/e2e/visual-shell.spec.ts` |

## Sanitized fixture policy

### Real reference workbook — never in git

The real June 2026 reference payroll workbook contains **real PII**.
**Never** commit it to git in any form: fixtures, test data, git history,
CI logs, screenshots, or golden artifacts.

### Synthetic set: `fixtures/sanitized/june-2026/`

| Rule | Requirement |
| --- | --- |
| Names | Deterministic synthetic names (seeded faker or fixed fake lookup). Never derived from or reversible to real names. |
| PAN / PRAN / GPF / bank | Syntactically valid but obviously fake (documented fake namespace / test ranges). |
| Structure | Preserve employee count, pay components, org hierarchy, and pay periods. |
| Totals | Keep numeric amounts per row identical; swap only identity/PII so aggregates remain exact for correctness tests without PII. |
| Format | Synthetic JSON input + golden JSON/Excel/PDF expected outputs only. |

### Pre-commit (fast)

- Regex for PAN: `[A-Z]{5}[0-9]{4}[A-Z]`.
- Indian bank account / IFSC-style patterns where applicable.
- Denylist of known real names/orgs from the real reference file.
- Scan `fixtures/` and test data paths.
- Block known real-source filenames and content hashes.

### CI (expensive)

- `scripts/ci/pii_fixture_guard.sh` — hash-denylist of real file content
  hashes; diff newly added fixtures; fail the build on match.
- Complements pre-commit; does not replace it.

## CSRF and session proof points

Documented decision (see [security.md](security.md), [threat-model.md](threat-model.md)):

- HTTP-only + Secure + SameSite=Lax cookies (justify Lax for WorkOS redirect auth).
- SameSite=Lax session cookie **plus** synchronizer CSRF token on state-changing
  routes (header must match server-issued token).
- Lax covers cross-site cookie sends on top-level navigations needed for WorkOS
  AuthKit redirects; synchronizer tokens defend state-changing
  POSTs/PUTs/PATCHes/DELETEs against CSRF including same-site adjacent risks.
- Proven by: `backend/tests/security/test_csrf.py`,
  `backend/tests/security/test_session_hardening.py`.

## Related controls under test

| Control | Primary suites |
| --- | --- |
| forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) | `backend/tests/rls/test_forced_rls_coverage.py` |
| NOSUPERUSER NOBYPASSRLS runtime database role | `backend/tests/rls/test_cross_tenant_isolation.py` |
| SET LOCAL per-request tenant context | RLS + API suites |
| WorkOS webhook signature verification | `backend/tests/security/test_workos_webhooks.py` |
| idempotency keys | `backend/tests/workflow/test_idempotency.py` |
| append-only audit log tables | workflow + security suites |
| immutability triggers | `backend/tests/security/test_posted_sql_immutability.py` |
| capability/permission checks at the API layer | `backend/tests/security/test_privilege_escalation.py`, `backend/tests/api/` |
| masked fields with a separate audited "reveal" action/endpoint | `backend/tests/security/test_pii_masking.py` |
