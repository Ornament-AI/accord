# Release readiness

This is a current-tree evidence map, not a production deployment attestation.
It was reconciled on 2026-07-30 against `main` at
`f0eae6c97169d7c3db2f1c591964f5092500f4a0`. The latest release tag reachable
from that commit is `v0.4.3`; `main` also contains the later TypeScript 7.0.2
toolchain upgrade.

Release acceptance policy lives in
[release-acceptance.md](release-acceptance.md). A gate is:

- **met** when the required implementation and repeatable repository evidence
  are present;
- **partial** when implementation or external release evidence is still
  missing;
- **not assessed** when the evidence was not rerun for a specific release.

Historical release tags or healthy endpoints do not prove a current release
candidate. A release packet must link the exact commit, hosted checks, artifacts,
and any required runtime/restore evidence.

## Gate status

| Gate | Status | Current evidence | Remaining requirement |
| --- | --- | --- | --- |
| **B — Contracts** | **partial** | Architecture, ADRs, payroll domain, testing, threat model, security, operations, report specs, acceptance, and this readiness map are maintained in-tree. | Engineering, security, and release-manager sign-off is external evidence and is not stored in this repository. |
| **C — CI** | **met** | `./scripts/verify.sh`; `.github/workflows/ci.yml` backend, migration, generated API-type drift, frontend, and Docker jobs. | Re-run the complete hosted workflow for the exact release commit. |
| **D — Isolation** | **met** | `backend/tests/rls/`, `backend/tests/gate_d/`, `backend/tests/api/test_tenant_context.py`, and per-phase migration RLS assertions run under restricted roles. | Re-run the backend lane for the exact release commit. |
| **E — Effective dating** | **met** | `backend/tests/services/test_versioning.py`, master-data model/service/API tests, and `backend/tests/rls/test_master_data_rls.py`. | Re-run focused suites when effective-date ownership changes. |
| **F — Calculation correctness** | **met** | Money/property/engine suites, `test_engine_june_golden.py`, `test_june_golden_e2e.py`, and `test_no_float_guard.py`; sanitized fixture validator. | Re-run the golden and float-guard evidence for the release commit. |
| **H — Workflow integrity** | **met** | Workflow/posting/idempotency service and API suites cover maker/checker, submit/approve/post/reverse/reopen, audit/outbox, and SQL immutability. `calculate` accepts `Idempotency-Key` like the other commands. | ADR 0008 records a stronger DB-trigger/GUC enforcement target than the service-layer guards implemented; treat as a documented design decision or ADR amendment, not a code gap. |
| **I — Export durability** | **met** | Storage protocol/S3 adapter tests and artifact service/API tests cover keys, checksums, state transitions, authorization, and audited streaming. The hourly `artifacts.maintenance` job reconciles orphans and expires retained artifacts. | Attach an environment-level object persistence/restart rehearsal as release evidence. |
| **J — Reports** | **met** | Report family/formatter suites, report service/API tests, canonical contract tests, and the independent validator under `scripts/validate_canonical_export.py`. | Re-run the canonical validator and relevant render checks for changes to report mappings/layout. |
| **K — Deploy / restore / E2E** | **met** | Immutable tag workflow, production deploy contract test (asserts the real tarball), `scripts/deploy.sh`, `scripts/smoke-test.sh`, `scripts/backup-restore.sh` with runtime-role RLS proof, `deploy/backup.sh` routine backups, and Playwright critical/a11y/visual specs incl. the multi-identity report-download journey. | — |

There is no gate G.

## Security and operational acceptance gaps

The following were gaps at the 2026-07-30 reconciliation and are now
implemented and verified:

- **Synchronizer CSRF protection** — `backend/app/middleware/csrf.py` enforces
  the session-bound synchronizer token on all state-changing routes
  (`accord_csrf` cookie ↔ `X-CSRF-Token` header).
- **PII reveal audit** — `reveal=true` on the employee detail/version
  endpoints writes an `employee.pii.reveal` access audit event.
- **Supply-chain evidence** — CI runs `pip-audit`, `pnpm audit`, and emits a
  CycloneDX SBOM (`.github/workflows/ci.yml`, `supply-chain` job).
- **Backup/restore RLS proof** — `scripts/backup-restore.sh restore-scratch`
  re-asserts the grant posture (`deploy/post-restore-grants.sql`) and verifies
  forced RLS + immutability denies under `accord_app`.
- **Visual parity** — `frontend/e2e/visual.spec.ts` holds committed
  screenshot baselines for the key surfaces.
- **Calculate idempotency** — `POST /payroll-runs/{id}/calculate` consumes an
  optional `Idempotency-Key` through the shared claim table, matching the
  other state-changing commands.
- **Provisioning in the release bundle** — `deploy/provision/` ships the
  organization/member CLIs the ADR-0011 bootstrap needs (previously staged but
  absent from the tarball).
- **Routine backups** — `deploy/backup.sh` produces paired Postgres + MinIO
  snapshots with retention pruning.

These are current implementation/evidence gaps, not missing-path aliases:

1. **Fixture PII real-source guard.** The committed June fixture is synthetic
   and its validator now runs in CI (`fixture-validation` job), but no
   dedicated hash/name guard against real-source data exists.
2. **Support break-glass.** No elevation path exists, so support access fails
   closed. A future path must be time-boxed, capability-checked, and audited.
3. **Non-Maharashtra portability.** GPF jurisdiction (`mumbai`/`nagpur`) and
   government-quarters (`mumbai`/`worli`/`other`) enums are
   Maharashtra-specific; a different state's deployment needs a schema/config
   decision before go-live.

These gaps require implementation or explicit, time-bounded release waivers;
documentation changes cannot make them pass.

## Current implementation anchors

| Concern | Authoritative source |
| --- | --- |
| Settings and production invariants | `backend/app/config.py` |
| API router assembly | `backend/app/main.py` and `backend/app/api/routes/` |
| Frontend routes/navigation | `frontend/src/router.tsx`, `frontend/src/lib/nav-registry.ts` |
| Capability matrix | `backend/app/auth/capabilities.py` |
| Workflow behavior | `backend/app/services/run_calculation/`, `run_workflow.py`, `run_posting.py` |
| Database schema | SQLModel definitions plus `backend/migrations/versions/` |
| Current Alembic head | `g3h4i5j6k7l8_posture_and_outbox.py` |
| Report catalog | `backend/app/reports/registry_setup.py` |
| Canonical export | `backend/app/reports/canonical_*.py`, `backend/app/services/report_readiness.py` |
| Local verification | `scripts/verify.sh` |
| Hosted CI/release | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |
| Host deployment | `scripts/deploy.sh`, `deploy/`, `docs/operations.md` |

## Evidence commands

Run from the repository root:

```bash
# Full local contract
TEST_DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord_test" \
  ./scripts/verify.sh

# Explicit migration proof (roles must already exist)
cd backend
DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord" \
MIGRATIONS_DATABASE_URL="postgresql+asyncpg://accord:accord@127.0.0.1:5432/accord" \
  .venv/bin/alembic upgrade head
cd ..

# Sanitized fixture structure/totals
backend/.venv/bin/python fixtures/sanitized/june-2026/validate.py

# Exact generated API contract
./scripts/generate-api-types.sh
git diff --exit-code -- frontend/src/types/api.generated.ts

# Browser suite inventory; run the suite against a prepared accord_e2e stack
pnpm --filter frontend exec playwright test --list
```

For a release, add the hosted CI URL, release workflow URL, exact immutable
image revision proof, smoke output, restore/RLS transcript, and Playwright
report. Do not copy old test totals into this document; command output and
hosted checks are the evidence.
