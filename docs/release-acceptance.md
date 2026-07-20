# Release Acceptance

This matrix defines the gates a release must pass. It covers Accord Phase 0
and every later release. The gates are lettered **A, B, C, D, E, F, H, I, J,
K** — the same letters as [testing.md](testing.md). **There is no Gate G.**

Cross-references: [testing.md](testing.md), [threat-model.md](threat-model.md),
[security.md](security.md).

We accept a release only when every gate below is a **Pass** with linked
evidence. A partial pass does not ship.

---

## Gate matrix

### Gate A — Atlas baseline

This gate confirms the declared Atlas upstream baseline before any product
gate runs.

| Field | Content |
| --- | --- |
| **Description** | Verify Accord’s declared Atlas upstream baseline (shell/transplant expectations) before product gates. |
| **Named checks / suites** | `scripts/verify_atlas_baseline.sh` |
| **Evidence artifact** | CI job log URL for gate A; script stdout transcript attached to release packet |

### Gate B — Phase 0 contracts review

Humans review the Phase 0 contract documents and sign off on them.

| Field | Content |
| --- | --- |
| **Description** | Human review that Phase 0 contracts are complete, mutually consistent, and approved: testing, threat model, release acceptance, security, ADRs, payroll domain. |
| **Named checks / suites** | Phase 0 contracts review checklist against `docs/testing.md`, `docs/threat-model.md`, `docs/release-acceptance.md`, `docs/security.md` (and linked ADRs / payroll-domain contracts) |
| **Evidence artifact** | Signed checklist (PR review + release manager sign-off); checklist PDF/markdown in release packet |

### Gate C — Transplant shell CI

CI must pass lint, typecheck, unit tests, and API smoke tests on the
transplanted shell.

| Field | Content |
| --- | --- |
| **Description** | Lint, typecheck, unit, and API smoke on the transplanted FastAPI + React shell. |
| **Named checks / suites** | `backend/tests/unit/test_money_decimal.py`; `backend/tests/unit/test_calculation_invariants.py`; `backend/tests/api/`; `backend/tests/services/`; `frontend/src/**/*.test.tsx`; plus lint/typecheck CI jobs |
| **Evidence artifact** | CI workflow URL (green); junit/coverage reports stored as CI artifacts |

### Gate D — Cross-tenant isolation

Tests must prove that no tenant can ever read another tenant's data.

| Field | Content |
| --- | --- |
| **Description** | Prove organization isolation under forced RLS with the restricted runtime role; no cross-tenant IDOR via API, services, storage, or workers. |
| **Named checks / suites** | `backend/tests/rls/test_cross_tenant_isolation.py`; `backend/tests/rls/test_forced_rls_coverage.py`; API/services/storage/worker isolation paths under `backend/tests/api/`, `backend/tests/services/`, `backend/tests/storage/test_tenant_object_isolation.py` |
| **Evidence artifact** | CI URL for RLS job; RLS coverage report listing tenant tables with forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) |

### Gate E — Effective-dated master data

Tests must prove that dated master data stays correct across period
boundaries.

| Field | Content |
| --- | --- |
| **Description** | Effective-dating semantics for master data (hire, pay components, org hierarchy) are correct across period boundaries. |
| **Named checks / suites** | `backend/tests/master_data/test_effective_dating.py` |
| **Evidence artifact** | CI URL; pytest report for master_data suite |

### Gate F — Calculation correctness

Tests must prove the payroll math is exact and uses no floats.

| Field | Content |
| --- | --- |
| **Description** | June 2026 synthetic totals and money/invariant unit proofs; Decimal-only payroll domain (no float). |
| **Named checks / suites** | `backend/tests/calculations/test_june_2026_totals.py`; `backend/tests/unit/test_calculation_invariants.py`; `backend/tests/unit/test_money_decimal.py`; `scripts/ci/no_float_payroll_domain.sh` |
| **Evidence artifact** | CI URL; calculation golden diff report; float-ban script transcript |

### Gate H — Workflow integrity (maker/checker, post, idempotency)

Tests must prove the run workflow is safe: maker/checker splits, posted data
stays frozen, and repeated commands stay safe.

| Field | Content |
| --- | --- |
| **Description** | Maker/checker segregation; immutable posted `payroll_run_version`; command idempotency; SQL-level immutability. Commands: `calculate`, `submit`, `withdraw`, `approve`, `reject`, `post`, `reverse`. |
| **Named checks / suites** | `backend/tests/workflow/test_maker_checker.py`; `backend/tests/workflow/test_posted_immutability.py`; `backend/tests/workflow/test_idempotency.py`; `backend/tests/security/test_posted_sql_immutability.py` |
| **Evidence artifact** | CI URL; workflow report; sample append-only `audit_events` excerpt (synthetic ids only) |

### Gate I — Export durability & object isolation

Tests must prove that export files endure and stay private to their tenant.

| Field | Content |
| --- | --- |
| **Description** | S3-compatible export artifacts endure and cannot be read across tenants. |
| **Named checks / suites** | `backend/tests/storage/test_export_durability.py`; `backend/tests/storage/test_tenant_object_isolation.py` |
| **Evidence artifact** | CI URL; storage isolation report |

### Gate J — Reports & reconciliation

Tests must prove each report family reconciles to posted data and stays
consistent across Excel and PDF.

| Field | Content |
| --- | --- |
| **Description** | Every report type uses one DTO/source of truth for Excel+PDF; semantic goldens; reconciliation to posted source. |
| **Named checks / suites** | `backend/tests/reports/test_reconciliation.py`; `backend/tests/reports/test_excel_golden.py`; `backend/tests/reports/test_pdf_golden.py`; `backend/tests/reports/test_excel_pdf_parity.py` |
| **Evidence artifact** | CI URL; golden comparison report (sanitized fixtures only — no real PII) |

### Gate K — Deploy / restore / E2E

Tests must prove that deploy, restore, and browser flows work end to end.

| Field | Content |
| --- | --- |
| **Description** | Clean-environment deploy; backup/restore RLS rehearsal; Playwright critical paths, a11y, and Atlas visual parity. |
| **Named checks / suites** | Clean-env deploy runbook; `backend/tests/security/test_backup_restore_rls.py`; `frontend/e2e/critical-paths.spec.ts`; `frontend/e2e/a11y.spec.ts`; `frontend/e2e/visual-shell.spec.ts` |
| **Evidence artifact** | Deploy CI/CD URL; restore rehearsal report; Playwright HTML report + visual baseline hashes |

---

## Summary table

Each gate at a glance.

| Gate | Short name | Primary suite paths | Evidence |
| --- | --- | --- | --- |
| A | Atlas baseline | `scripts/verify_atlas_baseline.sh` | CI URL + transcript |
| B | Phase 0 contracts | docs checklist (`testing.md`, `threat-model.md`, `release-acceptance.md`, `security.md`) | Signed checklist |
| C | Transplant shell CI | unit + `backend/tests/api/` + `backend/tests/services/` + `frontend/src/**/*.test.tsx` | CI URL |
| D | Cross-tenant isolation | `backend/tests/rls/test_cross_tenant_isolation.py` (+ forced RLS, API/services/storage) | CI URL + RLS report |
| E | Effective dating | `backend/tests/master_data/test_effective_dating.py` | CI URL |
| F | Calculations | `backend/tests/calculations/test_june_2026_totals.py` + unit invariants + float ban | CI URL + golden report |
| H | Workflow | maker_checker + posted_immutability + idempotency + posted_sql_immutability | CI URL |
| I | Storage | `backend/tests/storage/test_export_durability.py`; `backend/tests/storage/test_tenant_object_isolation.py` | CI URL |
| J | Reports | reconciliation + excel/pdf golden + parity | CI URL + golden report |
| K | Deploy/restore/E2E | `backend/tests/security/test_backup_restore_rls.py`; Playwright critical/a11y/visual | Deploy + Playwright reports |

---

## Final quality gates checklist

The release manager confirms each item before tagging.

| # | Requirement | Pointer |
| --- | --- | --- |
| 1 | **No real PII** in repo, CI logs, screenshots, or golden artifacts | [testing.md](testing.md) sanitized fixture policy; `scripts/ci/pii_fixture_guard.sh` |
| 2 | **No float** in payroll calculation domain — `Decimal` / minor-units only | `scripts/ci/no_float_payroll_domain.sh`; `backend/tests/unit/test_money_decimal.py` |
| 3 | **Every tenant-scoped table** has forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) + isolation tests | `backend/tests/rls/test_forced_rls_coverage.py`; `backend/tests/rls/test_cross_tenant_isolation.py`; gate D |
| 4 | **Every state-changing command** is authorized (capability/permission checks at the API layer), idempotent (idempotency keys), lock-protected where needed, and audited (append-only audit log tables) | gates H + C; [threat-model.md](threat-model.md) §5–6 |
| 5 | **Posted results** are traceable to source data versions, approval who/when, and content hash | `backend/tests/workflow/test_posted_immutability.py`; immutability triggers |
| 6 | **Every report type** has one DTO/source of truth for Excel+PDF, parity tested, reconciliation to source | gate J suites |
| 7 | **Atlas visual parity** snapshots at `frontend/e2e/visual-shell.spec.ts` / Playwright baselines | gate K |
| 8 | **Session/CSRF baseline** matches [security.md](security.md): HTTP-only + Secure + SameSite=Lax cookies (justify Lax for WorkOS redirect auth) **plus** synchronizer CSRF token on state-changing routes | `backend/tests/security/test_csrf.py`; `backend/tests/security/test_session_hardening.py` |
| 9 | **WorkOS webhook signature verification** enabled in all deployed environments | `backend/tests/security/test_workos_webhooks.py`; [threat-model.md](threat-model.md) §3 |
| 10 | **Support break-glass** is time-boxed and audited; distinct from normal RLS | `backend/tests/security/test_support_break_glass.py`; [security.md](security.md); [threat-model.md](threat-model.md) §10 |
| 11 | **Backup/restore** rehearsed with RLS still enforced under NOSUPERUSER NOBYPASSRLS runtime database role | `backend/tests/security/test_backup_restore_rls.py`; gate K |
| 12 | **Migration chain + drift** clean | `backend/tests/migrations/test_alembic_chain.py`; `backend/tests/migrations/test_migration_drift.py` |

---

## Sign-off block

| Role | Name | Date | Gates reviewed | Signature |
| --- | --- | --- | --- | --- |
| Engineering lead | | | A–F, H–K | |
| Security reviewer | | | D, H, K + threat-model | |
| Release manager | | | All + final checklist | |

**Ship rule:** Do not promote if any gate fails or its evidence is missing.
Exceptions need a signed, time-bounded waiver. Each waiver must name the
specific threat and its compensating control from
[threat-model.md](threat-model.md).
