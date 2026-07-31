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
| **Checks / evidence** | Review the pinned source tag, inclusion/exclusion inventory, rename map, and license checklist in `docs/atlas-upstream-manifest.md`; compare the transplanted shell to the pin when the baseline changes. |
| **Evidence artifact** | Review link or comparison transcript attached to the release packet. There is no executable baseline verifier in the current tree. |

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
| **Named checks / suites** | `./scripts/verify.sh`; backend suites under `backend/tests/domain/`, `backend/tests/api/`, and `backend/tests/services/`; frontend `src/**/*.test.ts(x)`; migration and Docker jobs in `.github/workflows/ci.yml` |
| **Evidence artifact** | Green CI workflow URL plus the local verification transcript when required by the release packet |

### Gate D — Cross-tenant isolation

Tests must prove that no tenant can ever read another tenant's data.

| Field | Content |
| --- | --- |
| **Description** | Prove organization isolation under forced RLS with the restricted runtime role; no cross-tenant IDOR via API, services, storage, or workers. |
| **Named checks / suites** | `backend/tests/rls/`; `backend/tests/gate_d/`; tenant-context API coverage in `backend/tests/api/test_tenant_context.py`; per-phase forced-RLS assertions in `backend/tests/migrations/` |
| **Evidence artifact** | Green backend CI URL and a test transcript proving empty/wrong organization context fails closed under `accord_app` / `accord_worker` |

### Gate E — Effective-dated master data

Tests must prove that dated master data stays correct across period
boundaries.

| Field | Content |
| --- | --- |
| **Description** | Effective-dating semantics for master data (hire, pay components, org hierarchy) are correct across period boundaries. |
| **Named checks / suites** | `backend/tests/services/test_versioning.py`; `backend/tests/models/test_master_data_models.py`; `backend/tests/rls/test_master_data_rls.py`; master-data API/service suites |
| **Evidence artifact** | Green backend CI URL and focused pytest transcript when effective-dating code changes |

### Gate F — Calculation correctness

Tests must prove the payroll math is exact and uses no floats.

| Field | Content |
| --- | --- |
| **Description** | June 2026 synthetic totals and money/invariant unit proofs; Decimal-only payroll domain (no float). |
| **Named checks / suites** | `backend/tests/domain/test_engine_june_golden.py`; `backend/tests/e2e/test_june_golden_e2e.py`; `backend/tests/domain/test_money.py`; `backend/tests/domain/test_money_properties.py`; `backend/tests/domain/test_no_float_guard.py` |
| **Evidence artifact** | Green backend CI URL, golden fixture validation, and the relevant pytest transcript |

### Gate H — Workflow integrity (maker/checker, post, idempotency)

Tests must prove the run workflow is safe: maker/checker splits, posted data
stays frozen, and repeated commands stay safe.

| Field | Content |
| --- | --- |
| **Description** | Maker/checker segregation; immutable posted `payroll_run_version`; command idempotency; SQL-level immutability. Commands: `calculate`, `submit`, `withdraw`, `approve`, `reject`, `post`, `reverse`. |
| **Named checks / suites** | `backend/tests/services/test_run_workflow.py`; `backend/tests/services/test_run_posting.py`; `backend/tests/services/test_idempotency.py`; matching API suites; `backend/tests/rls/test_immutable_grants.py`; `backend/tests/rls/test_payroll_run_rls.py` |
| **Evidence artifact** | CI URL; workflow report; sample append-only `audit_events` excerpt (synthetic ids only) |

### Gate I — Export durability & object isolation

Tests must prove that export files endure and stay private to their tenant.

| Field | Content |
| --- | --- |
| **Description** | S3-compatible export artifacts endure and cannot be read across tenants. |
| **Named checks / suites** | `backend/tests/storage/`; `backend/tests/services/test_artifacts.py`; `backend/tests/api/test_artifacts.py`; Compose object persistence rehearsal in `docs/operations.md` |
| **Evidence artifact** | Green backend CI URL plus a persistence/restart rehearsal transcript for the release environment |

### Gate J — Reports & reconciliation

Tests must prove each report family reconciles to posted data and stays
consistent across Excel and PDF.

| Field | Content |
| --- | --- |
| **Description** | Every report type uses one DTO/source of truth for Excel+PDF; semantic goldens; reconciliation to posted source. |
| **Named checks / suites** | Report-family and formatter suites under `backend/tests/reports/`; report API/service suites; `backend/tests/scripts/test_validate_canonical_export.py`; `backend/tests/e2e/test_june_golden_e2e.py` |
| **Evidence artifact** | Green backend CI URL and canonical validator/report reconciliation transcript using sanitized fixtures only |

### Gate K — Deploy / restore / E2E

Tests must prove that deploy, restore, and browser flows work end to end.

| Field | Content |
| --- | --- |
| **Description** | Clean-environment deploy; backup/restore and runtime-role rehearsal; Playwright critical paths and accessibility; visual parity evidence when the shell changes. |
| **Named checks / suites** | `backend/tests/ops/test_msidc_deploy_contract.py`; `scripts/backup-restore.sh`; `scripts/smoke-test.sh`; `frontend/e2e/auth-and-org.spec.ts`, `master-data.spec.ts`, `payroll-flow.spec.ts`, `reports.spec.ts`, and `axe-a11y.spec.ts` |
| **Evidence artifact** | Deploy/release workflow URL, exact-image runtime proof, restore/RLS rehearsal report, and Playwright report. The current tree has no automated visual-parity spec. |

---

## Summary table

Each gate at a glance.

| Gate | Short name | Primary suite paths | Evidence |
| --- | --- | --- | --- |
| A | Atlas baseline | `docs/atlas-upstream-manifest.md` comparison | Review link + transcript |
| B | Phase 0 contracts | docs checklist (`testing.md`, `threat-model.md`, `release-acceptance.md`, `security.md`) | Signed checklist |
| C | CI | `./scripts/verify.sh` + `.github/workflows/ci.yml` | CI URL + transcript |
| D | Isolation | `backend/tests/rls/`, `backend/tests/gate_d/`, tenant-context tests | CI URL + RLS transcript |
| E | Effective dating | versioning/model/RLS master-data suites | CI URL |
| F | Calculations | domain golden, HTTP golden, money/property, and float-guard suites | CI URL + golden transcript |
| H | Workflow | workflow/posting/idempotency API, service, and immutable-grant suites | CI URL |
| I | Storage | storage/artifact suites + persistence rehearsal | CI URL + rehearsal |
| J | Reports | `backend/tests/reports/`, report services/API, canonical validator | CI URL + validator |
| K | Deploy/restore/E2E | deploy contract, backup/smoke scripts, current Playwright specs | Deploy + restore + Playwright reports |

---

## Final quality gates checklist

The release manager confirms each item before tagging.

| # | Requirement | Pointer |
| --- | --- | --- |
| 1 | **No real PII** in repo, CI logs, screenshots, or golden artifacts | [testing.md](testing.md) sanitized fixture policy. A dedicated fixture-PII CI guard is still an acceptance gap. |
| 2 | **No float** in payroll calculation domain — `Decimal` / minor-units only | `backend/tests/domain/test_no_float_guard.py`; money/property suites |
| 3 | **Every tenant-scoped table** has forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) + isolation tests | `backend/tests/rls/`; `backend/tests/gate_d/`; per-phase migration assertions; gate D |
| 4 | **Every state-changing command** is authorized (capability/permission checks at the API layer), idempotent (idempotency keys), lock-protected where needed, and audited (append-only audit log tables) | gates H + C; [threat-model.md](threat-model.md) §5–6 |
| 5 | **Posted results** are traceable to source data versions, approval who/when, and content hash | run posting/workflow suites plus immutable-grant/RLS tests |
| 6 | **Every report type** has one DTO/source of truth for Excel+PDF, parity tested, reconciliation to source | gate J suites and canonical contract validator |
| 7 | **Atlas visual parity** evidence exists when shell code changes | gate K; no automated visual spec exists today |
| 8 | **Session/CSRF baseline** matches [security.md](security.md) | session/auth tests cover cookie/session behavior; synchronizer CSRF remains an implementation and acceptance gap |
| 9 | **WorkOS webhook signature verification** enabled in all deployed environments | `backend/tests/api/test_webhooks_workos.py`; [threat-model.md](threat-model.md) §3 |
| 10 | **Support break-glass** is time-boxed and audited; distinct from normal RLS | no elevation path exists today (fails closed); implementing it requires dedicated evidence |
| 11 | **Backup/restore** rehearsed with RLS still enforced under NOSUPERUSER NOBYPASSRLS runtime database role | `scripts/backup-restore.sh` plus a release-environment RLS transcript; not automated today |
| 12 | **Migration chain + drift** clean | fresh-upgrade/per-migration suites plus the CI `alembic upgrade head` and `alembic check` job |

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
