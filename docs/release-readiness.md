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
| **C — CI** | **met** | `./scripts/verify.sh`; `.github/workflows/ci.yml` backend, migration, frontend, and Docker jobs. | The hosted API-type job is still a placeholder; local `verify.sh` is the actual generated-type drift gate. |
| **D — Isolation** | **met** | `backend/tests/rls/`, `backend/tests/gate_d/`, `backend/tests/api/test_tenant_context.py`, and per-phase migration RLS assertions run under restricted roles. | Re-run the backend lane for the exact release commit. |
| **E — Effective dating** | **met** | `backend/tests/services/test_versioning.py`, master-data model/service/API tests, and `backend/tests/rls/test_master_data_rls.py`. | Re-run focused suites when effective-date ownership changes. |
| **F — Calculation correctness** | **met** | Money/property/engine suites, `test_engine_june_golden.py`, `test_june_golden_e2e.py`, and `test_no_float_guard.py`; sanitized fixture validator. | Re-run the golden and float-guard evidence for the release commit. |
| **H — Workflow integrity** | **partial** | Workflow/posting/idempotency service and API suites cover maker/checker, submit/approve/post/reverse, audit/outbox, and SQL immutability. | `calculate` appends a new immutable version without an idempotency-key path or audit event. ADR 0008 also records stronger status/DB-trigger targets than the implementation. |
| **I — Export durability** | **partial** | Storage protocol/S3 adapter tests and artifact service/API tests cover keys, checksums, state transitions, authorization, and audited streaming. | Attach an environment-level object persistence/restart rehearsal. Artifact reconciliation/expiry functions exist, but maintenance handlers and scheduling are not wired. |
| **J — Reports** | **met** | Report family/formatter suites, report service/API tests, canonical contract tests, and the independent validator under `scripts/validate_canonical_export.py`. | Re-run the canonical validator and relevant render checks for changes to report mappings/layout. |
| **K — Deploy / restore / E2E** | **partial** | Immutable tag workflow, production deploy contract test, `scripts/deploy.sh`, `scripts/smoke-test.sh`, `scripts/backup-restore.sh`, and Playwright critical/a11y specs. | No automated visual-parity spec or restore-under-runtime-role RLS suite exists. The report download browser journey remains skipped under the single local dev identity. |

There is no gate G.

## Security and operational acceptance gaps

These are current implementation/evidence gaps, not missing-path aliases:

1. **Synchronizer CSRF protection.** Session cookies are HTTP-only,
   SameSite=Lax, and Secure in production, and OAuth `state` is signed. General
   state-changing routes do not require a synchronizer token.
2. **PII reveal audit.** Sensitive employee fields are masked by default and
   `reveal=true` requires `reveal_sensitive_fields`, but the reveal itself does
   not write an access audit event.
3. **Fixture PII guard.** The committed June fixture is synthetic and has a
   validator, but CI has no dedicated real-source hash/name guard.
4. **Supply-chain evidence.** Dependency/container scanning and an SBOM are
   policy requirements in `security.md`, but `.github/workflows/ci.yml` does
   not produce them.
5. **Support break-glass.** No elevation path exists, so support access fails
   closed. A future path must be time-boxed, capability-checked, and audited.
6. **Backup/restore RLS proof.** The logical backup/scratch-restore helper
   checks restore integrity; release evidence must additionally prove the
   restored database still enforces forced RLS under `accord_app` and
   `accord_worker`.
7. **Visual parity.** Playwright covers functional and accessibility paths but
   has no current visual-baseline spec.
8. **Calculate idempotency and audit.** The calculate route is capability
   checked and row-locked, but it does not consume an `Idempotency-Key` or
   write an audit event. A distinct retry can append another immutable run
   version.

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
| Current Alembic head | `a7d3e5f9b102_canonical_export_metadata.py` |
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
