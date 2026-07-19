# Release readiness — Accord 0.1.0 (unreleased)

Assessment date: **2026-07-18**.

This document walks the gate matrix in [release-acceptance.md](release-acceptance.md)
(gates **A, B, C, D, E, F, H, I, J, K** — there is intentionally **no Gate G**)
against evidence that exists **in this repository today**.

**Honesty rule:** many suite paths named in `docs/release-acceptance.md` /
`docs/testing.md` were never created under those exact filenames. Where
equivalent coverage exists under different paths, that is cited and the gate
may still be **met**. Where named evidence is missing and no equivalent was
found, status is **partial**. `docs/security-review.md` does **not** exist;
security evidence is cited from [security.md](security.md) and
[threat-model.md](threat-model.md) only.

**Test totals:** do not treat this doc as a live count. Canonical local
verification is `scripts/verify.sh` (see §Test totals below). No in-repo
verify transcript/log with Accord suite totals was found on 2026-07-18.

---

## Gate matrix (A–F, H–K)

### Gate A — Atlas baseline — **partial**

| Field | Finding |
| --- | --- |
| **Acceptance named check** | `scripts/verify_atlas_baseline.sh` |
| **On disk** | **Missing.** `scripts/` contains `verify.sh`, `start.sh`, `stop.sh`, `status.sh`, `smoke-test.sh`, `generate-api-types.sh` only. |
| **Evidence present** | [atlas-upstream-manifest.md](atlas-upstream-manifest.md) pins Atlas tag **v1.1.0** at commit `4d5d1f980f3b17144cc6f6173974ff9205fb573a` and records Gate A verification upstream. Accord commit `d73414e` (*docs: record Atlas v1.1.0 baseline tag in upstream manifest (Gate A passed)*). Transplant commits: `52589ea` (backend skeleton), `c5970b0` (frontend shell). |
| **Why partial** | Baseline is documented and transplanted, but the acceptance-named Gate A script is not in-tree, so a reproducible Gate A CI transcript cannot be attached from this repo alone. |

### Gate B — Phase 0 contracts review — **partial**

| Field | Finding |
| --- | --- |
| **Contracts on disk** | Present and cross-linked: `docs/testing.md`, `docs/threat-model.md`, `docs/release-acceptance.md`, `docs/security.md`, `docs/payroll-domain.md`, plus ADRs `docs/adr/0001`–`0010` (10 files). Introduced in commit `b162e40` (*docs: testing strategy, threat model, release acceptance matrix, security baseline*) and `eef1d15` / `598c843` (Phase 0 / platform contracts). |
| **Signed checklist** | **Not found** in-repo (no release-packet PDF/markdown sign-off with names/dates filled in the acceptance sign-off block). |
| **Why partial** | Document set is complete enough for review; human release-manager / security sign-off artifacts are not present. |

### Gate C — Transplant shell CI — **met**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `backend/tests/unit/test_money_decimal.py`, `backend/tests/unit/test_calculation_invariants.py` — **missing** (`backend/tests/unit/` does not exist). |
| **Equivalents on disk** | Money / invariants under `backend/tests/domain/` (`test_money.py`, `test_money_properties.py`, `test_rounding.py`, `test_engine.py`, `test_calculators.py`, `test_no_float_guard.py`). API smoke: `backend/tests/api/` (20 test modules). Services: `backend/tests/services/` (14 modules). Frontend Vitest: `frontend/src/**/*.test.tsx` / `*.test.ts` (30 files; e2e README cites 142 component tests as of 2026-07-18). |
| **CI / verify** | `scripts/verify.sh` runs ruff, backend pytest, API type drift, frontend lint/format/typecheck/test/build. Workflow: `.github/workflows/ci.yml`. Commits: `52589ea`, `c5970b0`, `77fbbad`, `ea8098c`. |

### Gate D — Cross-tenant isolation — **met**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `backend/tests/rls/test_cross_tenant_isolation.py`, `backend/tests/rls/test_forced_rls_coverage.py`, `backend/tests/storage/test_tenant_object_isolation.py` — **missing**. |
| **Evidence on disk** | Forced-RLS behavioral suites: `backend/tests/rls/test_identity_tenancy_rls.py`, `test_master_data_rls.py`, `test_payroll_run_rls.py`, `test_platform_rls.py`, `test_rls_helper_sql.py` (asserts `ALTER TABLE … FORCE ROW LEVEL SECURITY` helper SQL). Adversarial Gate D matrix: `backend/tests/gate_d/` (`test_http_isolation.py`, `test_sql_isolation.py`, `test_session_adversarial.py`, `test_capability_matrix.py`, `test_unauthenticated_sweep.py`) — commit `33bb895` (*test(gate-d): adversarial cross-tenant isolation matrix (96 tests)*). Migration-level `relforcerowsecurity` assertions: `backend/tests/migrations/test_phase2_identity_tenancy.py`, `test_phase3_master_data.py`, `test_phase4_payroll_runs.py`, `test_phase5_platform.py`. Schema: migration `c8d4e2f1a9b7` (commit `813e8ae`). Artifact cross-org download blocked: `backend/tests/api/test_artifacts.py` (`test_download_404_other_org`). |

### Gate E — Effective-dated master data — **met**

| Field | Finding |
| --- | --- |
| **Acceptance named path** | `backend/tests/master_data/test_effective_dating.py` — **missing** (`backend/tests/master_data/` does not exist). |
| **Evidence on disk** | Schema migration `2f397740f38a` (commit `c63b7b8`). Service coverage: `backend/tests/services/test_versioning.py` (effective_from conflicts / open-range rules), `backend/tests/services/test_employees.py` (`test_get_detail_as_of_and_masking`, hire/version edges), `backend/tests/services/test_pay_setup.py`, `backend/tests/api/test_employees.py`, `backend/tests/api/test_org_structure.py`, `backend/tests/api/test_pay_setup.py`. Models: `backend/tests/models/test_master_data_models.py`. ADR: `docs/adr/0005-effective-dated-master-data.md`. |

### Gate F — Calculation correctness — **met**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `backend/tests/calculations/test_june_2026_totals.py`, `backend/tests/unit/…`, `scripts/ci/no_float_payroll_domain.sh` — **missing** (`scripts/ci/` does not exist). |
| **Evidence on disk** | June golden: `backend/tests/domain/test_engine_june_golden.py` (commit `c2e3c7f`); fixture `fixtures/sanitized/june-2026/` (commit `96ee1f5`); full-stack golden: `backend/tests/e2e/test_june_golden_e2e.py` (commit `c9bcbb1`). Decimal money: `backend/tests/domain/test_money.py`, `test_money_properties.py`, `test_rounding.py`, `test_rates.py` (commit `884e92d`). **No-float guard (verified on disk):** `backend/tests/domain/test_no_float_guard.py` (+ helper `backend/tests/domain/_float_guard.py`). |

### Gate H — Workflow integrity — **met**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `backend/tests/workflow/test_maker_checker.py`, `test_posted_immutability.py`, `test_idempotency.py`, `backend/tests/security/test_posted_sql_immutability.py` — **missing** (`backend/tests/workflow/` and `backend/tests/security/` do not exist). |
| **Evidence on disk** | Maker/checker: `backend/tests/services/test_run_workflow.py` (`test_self_approval_blocked`), `backend/tests/api/test_run_workflow.py` — commit `aae10fe`. Post/reverse + SQL immutability trigger: `backend/tests/services/test_run_posting.py` (`test_posted_immutable_rows_reject_update` matches `accord: UPDATE/DELETE forbidden`), `backend/tests/api/test_run_posting.py` — commit `299aff7`. Idempotency: `backend/tests/services/test_idempotency.py` — commits `577690d`, `fec03ad`. Immutable calculate versions: `backend/tests/services/test_run_calculation.py` (`test_immutable_version_row_rejects_update`). |

### Gate I — Export durability & object isolation — **partial**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `backend/tests/storage/test_export_durability.py`, `test_tenant_object_isolation.py` — **missing**. |
| **Evidence on disk** | Protocol + S3/MinIO: `backend/tests/storage/test_object_storage_protocol.py`, `backend/tests/storage/test_s3_adapter.py` (commit `689cbbc`). Artifact lifecycle / retention / orphan reconcile: `backend/tests/services/test_artifacts.py`, `backend/tests/api/test_artifacts.py` (`test_download_404_other_org`, expiry/finalize) — commit `c364164`. Jobs/worker: `backend/tests/jobs/`. |
| **Why partial** | Cross-tenant object-key isolation and export durability are exercised indirectly via artifacts + key builder tests, but the acceptance-named dedicated storage isolation suites are absent. |

### Gate J — Reports & reconciliation — **met**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `test_reconciliation.py`, `test_excel_golden.py`, `test_pdf_golden.py`, `test_excel_pdf_parity.py` — **missing** under those names. |
| **Evidence on disk** | Shared `ReportDTO` registry + writers: `backend/tests/reports/test_report_base.py`, `test_excel.py`, `test_pdf.py`, `test_pdf_fonts.py` (commit `06c0b77`). Family goldens + Excel/PDF from same DTO: `test_payroll_register.py` (`test_pay_bill_excel_and_pdf_formatters`, `test_treasury_face_excel_and_pdf_formatters`), `test_retirement_reports.py`, `test_recovery_reports.py` (posted-line reconciliation helpers), `test_statutory_reports.py`, `test_payments_reports.py`, `test_approval_note.py`. Pipeline: `backend/tests/services/test_report_generation.py`, `backend/tests/api/test_reports_api.py`. Integration commit `d95528f`. |

### Gate K — Deploy / restore / E2E — **partial**

| Field | Finding |
| --- | --- |
| **Acceptance named paths** | `backend/tests/security/test_backup_restore_rls.py` — **missing**. `frontend/e2e/critical-paths.spec.ts`, `a11y.spec.ts`, `visual-shell.spec.ts` — **missing** under those names. |
| **Evidence on disk** | Deploy: `deploy/docker-compose.yml`, `deploy/Dockerfile.web`, `.github/workflows/deploy.yml`, `docs/architecture.md`, `scripts/smoke-test.sh` — commits `ea8098c`, `d228281`. Playwright (alternate names): `frontend/e2e/auth-and-org.spec.ts`, `master-data.spec.ts`, `payroll-flow.spec.ts`, `reports.spec.ts`, `axe-a11y.spec.ts` — commit `84c075d`. Backend HTTP golden E2E: `backend/tests/e2e/test_june_golden_e2e.py`. Fresh migration replay: `backend/tests/migrations/test_fresh_upgrade.py` (head `a9f3c2e81b04`). |
| **Why partial** | No backup/restore RLS rehearsal suite; no Atlas visual-parity Playwright spec; headless create-org dialog setup still under debugging (see residuals). |

---

## Final quality-gates checklist

Copied from [release-acceptance.md](release-acceptance.md); verdicts as of 2026-07-18.

| # | Requirement | Verdict | Evidence / gap |
| --- | --- | --- | --- |
| 1 | **No real PII** in repo, CI logs, screenshots, or golden artifacts | **partial** | Sanitized June fixture at `fixtures/sanitized/june-2026/` + policy in `docs/testing.md`. Acceptance pointer `scripts/ci/pii_fixture_guard.sh` **does not exist**. |
| 2 | **No float** in payroll calculation domain | **met** | `backend/tests/domain/test_no_float_guard.py` (verified on disk). Domain money suites under `backend/tests/domain/`. Acceptance shell `scripts/ci/no_float_payroll_domain.sh` **missing**. |
| 3 | **Every tenant-scoped table** has forced RLS + isolation tests | **met** | `backend/tests/rls/` (identity/master/payroll/platform + helper SQL); `backend/tests/gate_d/`; migration `relforcerowsecurity` checks in `backend/tests/migrations/test_phase{2,3,4,5}_*.py`. Named `test_forced_rls_coverage.py` / `test_cross_tenant_isolation.py` **absent** (coverage relocated). |
| 4 | **State-changing commands** authorized, idempotent, lock-protected, audited | **met** | Workflow/posting/idempotency/audit: `backend/tests/services/test_run_workflow.py`, `test_run_posting.py`, `test_idempotency.py`, `test_outbox.py`, `backend/tests/api/test_run_*.py`, `test_audit_read.py`; threat-model §§5–6 in `docs/threat-model.md`. |
| 5 | **Posted results** traceable (versions, approval who/when, content hash) | **met** | `backend/tests/services/test_run_posting.py` (`test_posted_immutable_rows_reject_update`); approval-note evidence in `backend/tests/reports/test_approval_note.py`; calculate immutability in `test_run_calculation.py`. Named `test_posted_immutability.py` **absent**. |
| 6 | **Every report type** one DTO for Excel+PDF, parity, reconciliation | **met** | Shared `ReportDTO` + per-family excel/pdf formatters/goldens under `backend/tests/reports/` (see Gate J). Dedicated `test_excel_pdf_parity.py` / `test_reconciliation.py` **absent**. |
| 7 | **Atlas visual parity** Playwright baselines | **partial** | `frontend/e2e/visual-shell.spec.ts` **missing**. Shell transplant exists (`c5970b0`); no visual baseline suite in-tree. |
| 8 | **Session/CSRF baseline** per `docs/security.md` | **partial** | Cookie flags implemented in `backend/app/auth/session.py` (`httponly=True`, `samesite="lax"`, `secure=settings.is_production`). Session tests: `backend/tests/auth/test_session.py`, `backend/tests/api/test_auth_routes.py`. OAuth state anti-CSRF helper only — **no** synchronizer CSRF token suite; `backend/tests/security/test_csrf.py` and `test_session_hardening.py` **missing**. |
| 9 | **WorkOS webhook signature verification** | **met** | `backend/tests/api/test_webhooks_workos.py` (valid/invalid signature + durable dedup); commit `216b6be`. Named `backend/tests/security/test_workos_webhooks.py` **absent**. |
| 10 | **Support break-glass** time-boxed and audited | **partial** | Policy described in `docs/security.md` / `docs/threat-model.md` §10. Suite `backend/tests/security/test_support_break_glass.py` **missing**; no implementation evidence found under `backend/tests/`. |
| 11 | **Backup/restore** with RLS under NOSUPERUSER NOBYPASSRLS role | **partial** | Runtime role + FORCE RLS proven in RLS/migration/gate_d tests. Dedicated `backend/tests/security/test_backup_restore_rls.py` **missing**. |
| 12 | **Migration chain + drift** clean | **partial** | Fresh upgrade to head `a9f3c2e81b04`: `backend/tests/migrations/test_fresh_upgrade.py` + phase upgrade/downgrade modules. Named `test_alembic_chain.py` / `test_migration_drift.py` **missing** (no empty-autogenerate drift suite found). |

---

## Known residual items (do not ship as “all green”)

1. **Playwright headless create-org dialog** — still under debugging. Documented in `frontend/e2e/README.md` (Live-run status 2026-07-18): headless Chromium setup-spec dialog-open / portal timing is flaky; create-org → authenticated app covered by `backend/tests/e2e/test_june_golden_e2e.py`, API reproduction, and frontend component tests (including `frontend/src/components/create-organization-dialog.test.tsx`).
2. **`docs/security-review.md` does not exist** — do not cite it. Use `docs/security.md` and `docs/threat-model.md`.
3. **Acceptance-matrix path drift** — many `docs/testing.md` / `docs/release-acceptance.md` suite paths were never created; coverage lives under `domain/`, `services/`, `gate_d/`, `reports/`, `api/`, and `frontend/e2e/*.spec.ts` alternate names. Update contracts or add shims before treating named paths as CI entrypoints.
4. **Missing security suites** — CSRF synchronizer tests, support break-glass tests, backup/restore RLS rehearsal, PII fixture CI guard script.
5. **No in-repo Accord `verify.sh` transcript** with authoritative pass/fail totals as of 2026-07-18 (see below).
6. **Gate A script** `scripts/verify_atlas_baseline.sh` absent; baseline is documentation + transplant commits only.
7. **Human sign-off block** in `docs/release-acceptance.md` is blank — release manager / security reviewer signatures not recorded.

---

## Migration IDs (verified under `backend/migrations/versions/`)

| Revision | File |
| --- | --- |
| `b7e3c1a90f24` | `b7e3c1a90f24_enable_required_extensions.py` |
| `c8d4e2f1a9b7` | `c8d4e2f1a9b7_phase2_identity_tenancy_tables.py` |
| `2f397740f38a` | `2f397740f38a_phase3_master_data_tables.py` |
| `021faa7dd776` | `021faa7dd776_phase4_payroll_run_tables.py` |
| `a9f3c2e81b04` | `a9f3c2e81b04_phase5_platform_tables.py` (current head per `test_fresh_upgrade.py`) |

---

## Commit anchors cited (from `git log --oneline`)

| Hash | Subject |
| --- | --- |
| `d73414e` | docs: record Atlas v1.1.0 baseline tag in upstream manifest (Gate A passed) |
| `b162e40` | docs: testing strategy, threat model, release acceptance matrix, security baseline |
| `52589ea` | feat(backend): transplant Atlas v1.1.0 backend infrastructure skeleton |
| `c5970b0` | feat(frontend): transplant Atlas v1.1.0 design system and app shell |
| `813e8ae` | feat(db): identity and tenancy tables with forced RLS (migration c8d4e2f1a9b7) |
| `33bb895` | test(gate-d): adversarial cross-tenant isolation matrix (96 tests) |
| `c63b7b8` | feat(db): Phase 3 effective-dated master-data schema (migration 2f397740f38a) |
| `884e92d` | feat(domain): exact-decimal Money/Rate primitives, rounding registry, no-float guard |
| `c2e3c7f` | feat(engine): deterministic payroll calculation engine with June golden proof |
| `96ee1f5` | feat(fixtures): sanitized June 2026 golden fixture with exact aggregate invariants |
| `aae10fe` | feat(workflow): validate/submit/withdraw/approve/reject commands |
| `299aff7` | feat(workflow): post and reverse commands with single-transaction evidence |
| `689cbbc` | feat(storage): S3-compatible ObjectStorage adapter (boto3 + MinIO integration tests) |
| `06c0b77` | feat(reports): shared report DTO registry, safe Excel writer, PDF renderer |
| `d95528f` | feat(integration): assemble report platform — registry, app/worker wiring, reports UI routes |
| `c9bcbb1` | test(e2e): June golden end-to-end through the full HTTP stack |
| `84c075d` | test(e2e): Playwright critical-path suite with axe accessibility checks |
| `282e2ef` | feat(ops): Prometheus metrics, readiness depth, structured-log redaction |
| `fec03ad` | fix(workflow): payroll input upsert 500 and idempotent-command RLS 404; auth-race guard |
| `d228281` | feat(deploy): release workflow, architecture doc, README quick start |

---

## Test totals

**Source of truth:** `scripts/verify.sh` (also `pnpm verify` / `npm`-workspace script `verify` in root `package.json`).

How to obtain totals (do not invent numbers here):

```bash
./scripts/verify.sh
```

That script runs, when prerequisites exist: shell `bash -n`, backend ruff check/format, `pytest backend/tests -q`, OpenAPI type drift check, frontend lint / format:check / typecheck / `test:run` / build. Steps skip with a clear notice if a lane dependency is missing; a failed step fails the script.

**In-repo verify log:** none found on 2026-07-18 (no `*verify*.log` / junit artifact checked into the repo). Do not cite Atlas upstream counts from `docs/atlas-upstream-manifest.md` as Accord suite totals — those numbers are for the Atlas v1.1.0 baseline tag, not this tree.

Secondary note only (not a substitute for `verify.sh`): `frontend/e2e/README.md` (2026-07-18) mentions **142** frontend component tests in the context of create-org coverage; that is a lane note, not the canonical verify summary.
