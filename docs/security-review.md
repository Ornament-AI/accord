# Security Review — Accord

**Date:** 2026-07-18  
**Scope:** Implementation vs [threat-model.md](threat-model.md) and [security.md](security.md)  
**Method:** Read-only code and migration review with file:line evidence. No code was changed.  
**Reviewer lane:** SECURITY REVIEW (Cursor agent)

This is a point-in-time review record. It describes the code as it stood on
the review date. Each threat-model item and each of the nine mandated scope
areas gets a verdict: **Implemented / Partial / Gap**. Each verdict cites
code evidence. Findings for a future remediation lane are ranked at the end.
File and line references are as of the review date. They may have moved
since. Do not use this dated verdict table as the current release decision;
use [security.md](security.md), [threat-model.md](threat-model.md), and
[release-readiness.md](release-readiness.md) for the maintained contract.

Three terms show up a lot. RLS is row-level security: Postgres itself
filters rows by tenant. A GUC is a Postgres setting; Accord binds tenant
context in transaction-local GUCs such as `app.organization_id`. A DSN is a
database connection string.

---

## Verdict summary (threat model)

| # | Threat | Verdict |
| --- | --- | --- |
| 1 | Session fixation / hijack | **Partial** |
| 2 | CSRF on state-changing routes | **Gap** |
| 3 | WorkOS webhook replay / forgery | **Implemented** |
| 4 | Organization confusion / cross-tenant IDOR | **Partial** |
| 5 | Privilege escalation between roles | **Partial** |
| 6 | Maker/checker bypass | **Partial** |
| 7 | Posted-data tampering | **Partial** |
| 8 | Sensitive-PII exposure | **Partial** |
| 9 | Object storage enumeration / leak | **Implemented** |
| 10 | Support-administrator abuse | **Gap** |
| 11 | Supply-chain / dependency risks | **Partial** |
| 12 | Backup / restore exposure | **Gap** |

---

## 1. Tenancy / RLS

### Verdict: Partial

**Forced RLS on tenant-owned tables — Implemented.**  
Migrations apply `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` via
`rls_policy_sql` for both `accord_app` and `accord_worker`:

| Phase | Migration | Tables with `_apply_forced_rls` |
| --- | --- | --- |
| 2 | `backend/migrations/versions/c8d4e2f1a9b7_phase2_identity_tenancy_tables.py` | `organization_memberships` (175), `organization_settings` (236), `idempotency_keys` (279); settings API is retired but the table remains for rolling compatibility |
| 3 | `backend/migrations/versions/2f397740f38a_phase3_master_data_tables.py` | All master-data tenant tables (e.g. `employees` 130, `employee_bank_account_versions` 499, …) |
| 4 | `backend/migrations/versions/021faa7dd776_phase4_payroll_run_tables.py` | `payroll_periods`–`payroll_result_lines` (144–407) |
| 5 | `backend/migrations/versions/a9f3c2e81b04_phase5_platform_tables.py` | `audit_events`, `outbox_events`, `payroll_approvals`, `jobs`, `export_artifacts` (138–359) |

Helper DDL (ENABLE + FORCE + policy):

```109:135:backend/app/models/base.py
def rls_policy_sql(
    table_name: str,
    *,
    role: str = "accord_app",
    policy_name: str = "tenant_isolation",
) -> str:
    ...
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;\n"
```

**Non-tenant by design (no RLS):** `users`, `organizations`, `sessions`
(phase 2 creates `sessions` without `_apply_forced_rls` — see
`c8d4e2f1a9b7…py:281–316`), and `webhook_events` (phase 5 docstring:
“global with no RLS”).

**Runtime roles NOSUPERUSER NOBYPASSRLS — Implemented.**

```36:60:backend/scripts/create_roles.sql
    CREATE ROLE accord_app WITH
      LOGIN
      PASSWORD 'REPLACE_WITH_SECRET'  -- REPLACE_WITH_SECRET
      NOSUPERUSER
      NOBYPASSRLS
      ...
    CREATE ROLE accord_worker WITH
      LOGIN
      PASSWORD 'REPLACE_WITH_SECRET'  -- REPLACE_WITH_SECRET
      NOSUPERUSER
      NOBYPASSRLS
```

**Org context from session, not request body — Implemented for ordinary
resources.** `require_tenant_context` binds the GUCs from
`principal.organization_id`. That value comes from the session, never from
the path or body (`backend/app/api/deps.py:101–141`). `bind_tenant_context`
uses transaction-local `set_config(..., true)`
(`backend/app/tenancy.py:47–62`). The org-switch route accepts
`organization_id` in the body by design, but it re-checks membership before
rotating (`backend/app/api/routes/auth.py:256–278`).

**Gate D cross-tenant SQL — Partial.**  
`backend/tests/gate_d/test_sql_isolation.py` proves UPDATE/DELETE/INSERT/JOIN/
COUNT/fail-closed/worker parity for **identity** tenant tables only
(`organization_memberships`, `organization_settings`, `idempotency_keys` —
lines 26–30, 138–362). It does **not** run hostile SQL against master-data or
payroll tables. Wider coverage sits outside Gate D in
`backend/tests/rls/test_master_data_rls.py`,
`backend/tests/rls/test_payroll_run_rls.py`, and
`backend/tests/rls/test_platform_rls.py`.  
The threat-model suite `backend/tests/rls/test_forced_rls_coverage.py` is
**missing**. HTTP Gate D covers switch-org isolation. It also records an
org-create finding (`backend/tests/gate_d/test_http_isolation.py:1–17`).

---

## 2. AuthN / session

### Verdict: Partial (threat #1 Partial; webhook threat #3 Implemented)

| Control | Evidence | Status |
| --- | --- | --- |
| WorkOS callback + server-side DB sessions | `backend/app/api/routes/auth.py` login/callback; `DatabaseSessionStore` in `backend/app/auth/session.py:135–237` | Implemented |
| HttpOnly / Secure / SameSite=Lax | `session.py:76–85` (`httponly=True`, `secure=settings.is_production`, `samesite="lax"`) | Partial — Secure only when `ENVIRONMENT=production`, not staging |
| Session rotation on org create / switch | `organizations.py` service rotate; `auth.py:281–286`; `session.py:218–231` | Implemented |
| Revocation | `revoke_session` + logout `auth.py:186–204`; read path rejects `revoked_at` `session.py:191–192` | Implemented |
| Production fail-closed WorkOS | `config.py:106–122` requires WorkOS + `SESSION_SECRET_KEY` (+ migrations DSN); blocks `DEV_AUTH_BYPASS` | Implemented |
| Idle + absolute TTL | Absolute 12h `SESSION_MAX_AGE_SECONDS` (`session.py:25`); idle via `session_idle_timeout_seconds` (`session.py:203–204`) | Implemented |
| Webhook signature + durable dedup | `verify_workos_webhook` (`webhooks.py:36–57`); INSERT claim + ON CONFLICT (`webhooks.py:86–106`); route `auth.py:305–328` | Implemented |

**Gap vs threat-model proven-by:** `backend/tests/security/test_session_hardening.py`
and `backend/tests/security/test_workos_webhooks.py` do not exist (there is no
`backend/tests/security/` tree). Coverage lives elsewhere
(`backend/tests/auth/`, `backend/tests/gate_d/test_session_adversarial.py`).

---

## 3. AuthZ / capabilities / maker-checker

### Capability matrix vs ADR 0002 §8 — Partial

Source of truth: `backend/app/auth/capabilities.py:26–83`.

| ADR column | Implementation | Notes |
| --- | --- | --- |
| Master data CRUD | `manage_master_data` / `view_master_data` | Matches admin/preparer/reviewer scoping comments (`capabilities.py:4–8`) |
| Sensitive reveal | `reveal_sensitive_fields` (admin only among org roles) | Matches |
| Create/calculate / submit / approve / post | `create_run`, `submit_run`, `approve_run`, `post_run` | Matches; post → `report_releaser` not approver (`capabilities.py:8–10`, 69–75) |
| Run reverse | No distinct capability; reverse route uses `post_run` (`run_posting.py:69–76`) | Documented as “unimplemented 13th capability” (`capabilities.py:15–16`); ADR “scoped” reverse for releaser is approximated by `post_run` |
| Reports | `generate_reports` (+ interpretive `release_reports`) | Matches comments |
| Organization-level configuration | `manage_organization` | Protects report configuration; member access changes are CLI-only (`provision_member.py`, ADR 0011) |
| Platform support | Explicitly out of scope / display-only (`capabilities.py:17–18`) | Gap vs ADR support row |

### `require_capability` on mutating routes — Partial

Audit of `@router.post|put|patch|delete` under `backend/app/api/routes/`:

- **Gated:** employees, org_structure, pay_setup, payroll_runs, run_*, and
  reports generate — all use `require_capability(...)`.
- **Auth-only (no capability):** none for org create — `POST /api/organizations`
  removed (ADR 0011); bootstrap is CLI-only via
  `scripts/provision_organization.py`.
- **Expected exceptions:** auth logout / WorkOS webhook.

### Maker/checker (approver ≠ submitter) — Partial

Maker/checker means the person who submits a run cannot approve it.

- **Service:** enforced on approve and reject
  (`run_workflow.py:649–653`, `731–735`) with URN
  `urn:accord:workflow:maker_checker`.
- **DB:** **not** enforced. The model states this explicitly:

```140:145:backend/app/models/platform.py
class PayrollApproval(...):
    """...
    Maker/checker (approver ≠ submitter) is a cross-row rule enforced in the
    service layer, not as a database CHECK on this table.
    """
```

The review scope asked for the rule in the service **and** the database. The
DB side is a Gap against that bar. A cross-row rule would need a trigger or
function, not a simple CHECK.

---

## 4. Immutability

### Verdict: Partial

**Triggers — Implemented.** Phase 4 creates `accord_forbid_update_delete`
with the escape-hatch GUC `accord.allow_immutable_ddl`, attached to
`payroll_run_versions`, `payroll_employee_results`, and `payroll_result_lines`
(`021faa7dd776…py:55–94`, `417`). Phase 5 reuses the same function for
append-only `audit_events` / `payroll_approvals` (`a9f3c2e81b04…py:67–77`).

**Runtime-role grants — Partial.**  
`REVOKE UPDATE, DELETE` is applied for `audit_events` (and DELETE for
`outbox_events`) in `a9f3c2e81b04…py:54–64`. There is **no** matching
`REVOKE UPDATE/DELETE` on the three payroll snapshot tables. They rely on
triggers alone, while default grants still give DML to `accord_app` /
`accord_worker` (`create_roles.sql:76–77`).

**Escape-hatch scoping — Partial / weak.**  
Any session that can run `SET LOCAL accord.allow_immutable_ddl = 'on'` gets
past the trigger (`021faa7dd776…py:72–76`; proven in
`test_payroll_run_rls.py:354–368`). Snapshot tables also keep their UPDATE
grants. So a compromised API SQL path could change posted rows. The right
defense in depth is to REVOKE UPDATE/DELETE on those tables from the runtime
roles. Then only the migrator or a SECURITY DEFINER path could use the escape
hatch.

---

## 5. Idempotency / RLS GUC across mid-command commit

### Verdict: Partial

Background: `SET LOCAL` GUCs die when a transaction ends. A command that
commits mid-flight must bind the tenant context again. If it does not, every
later tenant-scoped statement runs blind under forced RLS.

**Claim-path rebind — Implemented (no pre-executor window).**  
The mid-command commit publishes the `in_progress` lease. The GUCs are saved
before that commit and rebound right after it:

```124:128:backend/app/services/idempotency.py
    if claimed_id is not None:
        gucs = await _snapshot_tenant_gucs(db)
        await db.commit()
        await _rebind_tenant_gucs(db, gucs)
        return await _execute_claimed(db, row_id=claimed_id, executor=executor)
```

(`_snapshot_tenant_gucs` / `_rebind_tenant_gucs` at lines 47–65.)

**Post-executor / failure path — Gap (High).**  
`_execute_claimed` rolls back or relies on executor-internal commits, then
reads and updates `idempotency_keys` **without** rebinding the tenant GUCs:

```255:277:backend/app/services/idempotency.py
async def _execute_claimed(...):
    try:
        snapshot = await executor()
    except Exception:
        await db.rollback()
        row = await db.get(IdempotencyKey, row_id)  # no GUC rebind
        ...
    row = await db.get(IdempotencyKey, row_id)  # no GUC rebind after executor commit
```

Workflow/posting executors call `await db.commit()` (e.g.
`run_workflow.py:689`), which clears `SET LOCAL`. Under production
`accord_app` + forced RLS, the follow-up `get` can see **zero rows**. The key
then sticks in `in_progress`. A command that in fact succeeded then surfaces
`ConflictError("Idempotency key disappeared...")`.

Unit/API tests usually connect with a superuser/table-owner DSN
(`backend/tests/conftest.py:15–16`; CI uses `postgres:postgres` in
`.github/workflows/ci.yml:86–88`). Those connections **bypass RLS**. That
masks this bug.

---

## 6. Secrets / logging

### Verdict: Partial (controls largely Implemented; proven-by suites incomplete)

| Control | Evidence | Status |
| --- | --- | --- |
| Log redaction keys | `logging_config.py:16–25` — `pan`, `pran`, `account_number`, `password`, `secret`, `token`, `authorization`, `cookie`; processor wired at line 89 | Implemented |
| `.env.example` placeholders | `backend/.env.example` empty WorkOS/session/S3 secrets; local DB password `accord` is a documented local default | Implemented (no production secrets) |
| `.gitignore` blocks `.env` + workbooks | `.gitignore:30–32`, `40–44` (`*.xlsx` with sanitized exception) | Implemented |
| No obvious committed cloud secrets | Grep for common secret shapes returned no live keys in tree | Implemented (spot-check) |
| Threat-model security test / CI PII guard paths | `backend/tests/security/*`, `scripts/ci/pii_fixture_guard.sh` | **Missing** |

---

## 7. PII

### Verdict: Partial

**Fixtures — Implemented (synthetic).**  
`fixtures/sanitized/june-2026/` uses documented fake namespaces
(`README.md:32–44`: `ZZZPZ####Z` PAN, `9000…` PRAN, `SYNTH` sevarth, etc.).
No sign of real workbook PII in `fixtures/`. A full scan of git history for
leaked real PAN/account data was **not** run in this lane. That part stays
unverified beyond the current tree and its naming rules.

**API masking + capability-gated reveal — Partial.**  
`mask_value` / `profile_from_row(..., reveal=)` /
`bank_from_row(..., reveal=)` in `schemas/employees.py:37–45`, `259–283`,
`319–323`. Routes gate `reveal=true` on `reveal_sensitive_fields`
(`employees.py:43–49`, `78–126`). Create/detail default to `reveal=False`
(`services/employees.py:240`, `463–468`).

**Audited reveal — Gap.**  
The threat model and security.md require a separate audited reveal action.
No `AuditEvent` (or equivalent) is written when `reveal=true` is used. A grep
of `backend/app` shows a capability check only, and no reveal audit event.

**Reports are unmasked for statutory/payment output, by design.** This is
noted in `reports/families/statutory.py` and `payments.py` (full PAN /
account for authority/payment files). Access goes through the artifact
download controls (see §8).

---

## 8. Object storage

### Verdict: Implemented

- Opaque keys `{organization_id}/{object_uuid}`:
  `storage/protocol.py:53–105`, `build_object_key` at 99–105;
  used in `artifacts.py:116`.
- Downloads are authorized per request with tenant context plus the
  `generate_reports` capability: `artifacts.py` routes `97–114`; service
  `stream_download` `243–285`.
- Each download is audited as `artifact.download` before streaming
  (`artifacts.py:264–280`).
- Enumeration resistance: UUID object segment; metadata under forced RLS
  (`export_artifacts` RLS at phase 5:359).

---

## 9. Dependency / supply chain

### Verdict: Partial (informational)

| Observation | Location | Severity |
| --- | --- | --- |
| Direct deps are mostly exact pins | `backend/requirements.txt`, `frontend/package.json` | Info — good |
| Frontend `msw` uses caret `^2.4.9` | `frontend/package.json:53` | Info — floating transitive surface |
| TypeScript compiler is exactly pinned to stable 7.0.2; the OpenAPI generator's TypeScript 6 API runtime is isolated from the frontend | `frontend/package.json`, `tools/openapi-typescript-runtime/package.json` | Info — stable compiler with a tooling-only compatibility boundary |
| CI has **no** `pip-audit` / `npm audit` / image scan / SBOM steps | `.github/workflows/ci.yml` (full file) | Medium vs security.md §Dependency scanning |
| Threat-model proven-by suites for supply chain are CI artifacts only | Not present in workflow | Partial |

No clearly stale or dead pins stood out in a static read of current version
numbers (FastAPI 0.139, React 19.2, Vite 8.1, etc.). This lane did **not**
query live advisory databases.

---

## Threat-model item detail

### 1. Session fixation / hijack — Partial

In place: opaque DB sessions, HttpOnly + SameSite=Lax, rotation at privilege
boundaries, revocation, idle/absolute TTL, and production secret checks.
Gaps: the Secure cookie flag is tied only to `is_production`
(`session.py:83`); there is no synchronizer CSRF token, which makes session
abuse worse (see #2); the named security suite from the threat model is
missing.

### 2. CSRF — Gap

The threat model mandates SameSite=Lax **plus** a synchronizer CSRF token on
state-changing routes (`threat-model.md:37–42`, `57–64`).  
The code has OAuth `state` signing only (`session.py:267–285`). There is no
CSRF middleware, no CSRF header check, and no
`backend/tests/security/test_csrf.py`. CORS allows credentials
(`main.py:297–303`) without a CSRF token header.

### 3. WorkOS webhooks — Implemented

The signature check, timestamp skew check, and durable `webhook_events`
dedup are all in place, with rollback-safe claims (`webhooks.py`,
`auth.py:305+`).

### 4. Cross-tenant IDOR — Partial

Strong forced RLS + `SET LOCAL` + Gate D SQL/HTTP for identity tables and
org switch. Gaps: Gate D SQL does not reach all tenant tables; unlimited org
create; missing `test_forced_rls_coverage.py`.

### 5. Privilege escalation — Partial

The capability matrix mostly matches the ADR. Mutating payroll/master routes
are gated. Gaps: org create with no capability check; platform support is
display-only with no break-glass; reverse is folded into `post_run`.

### 6. Maker/checker — Partial

Service + tests enforce submitter ≠ approver/rejector. The database does not
enforce it. Poster ≠ submitter is not required, by design
(`run_posting.py:31–33`).

### 7. Posted-data tampering — Partial

Triggers and the API reverse-new-version path exist. Missing: runtime REVOKE
on snapshot tables. The escape hatch works wherever `SET LOCAL` is possible.

### 8. Sensitive-PII — Partial

Masking + capability reveal + synthetic fixtures exist. Missing: a reveal
audit event and the named `test_pii_masking.py` / `pii_fixture_guard.sh`.

### 9. Object storage — Implemented

See §8 above.

### 10. Support-administrator abuse — Gap

`is_platform_admin` / `platform_support_administrator` are display-only with
**no** capability bypass and **no** break-glass session/TTL/audit path
(`capabilities.py:17–18`, `principal.py:70–74`).  
`backend/tests/security/test_support_break_glass.py` is missing. Against the
threat model and the security.md support policy, this control is not built.
Failing closed is safer than a silent bypass. Still, the mandated controlled
break-glass path is absent.

### 11. Supply chain — Partial

Pins are present. The CI scan/SBOM steps that security.md requires are not
wired in `.github/workflows/ci.yml`.

### 12. Backup / restore — Gap

The ops expectations exist in security.md. There is no
`backend/tests/security/test_backup_restore_rls.py`. No in-repo restore
rehearsal evidence was reviewed in this lane.

---

## Prioritized findings

| Sev | Location | Finding | Recommendation |
| --- | --- | --- | --- |
| **High** | `backend/app/services/idempotency.py:255–277` | After executor commit/rollback, idempotency row updates run without tenant GUC rebind; under `accord_app` + forced RLS keys can stick in `in_progress` and successful commands error | Rebind snapshotted GUCs (or pass `organization_id` into a privileged claim update path) before every post-commit idempotency read/write; add RLS-role regression test |
| **High** | CSRF absent (expected near `backend/app/main.py` middleware / mutating routes) | Threat model requires synchronizer CSRF on POST/PUT/PATCH/DELETE; only OAuth state exists | Issue CSRF cookie/token; require header match on mutations; add `test_csrf.py` |
| **High** | `backend/app/api/routes/organizations.py:31–38` | Any authenticated user (incl. zero memberships) can create orgs and become `organization_administrator` | Gate behind platform/admin capability or invitation flow; preserve Gate D adversarial test as regression |
| **High** | `021faa7dd776…py` immutable tables + `create_roles.sql:76–77` | Snapshot tables keep UPDATE/DELETE grants; escape GUC is settable via `SET LOCAL` | `REVOKE UPDATE, DELETE, TRUNCATE` on immutable snapshot tables from `accord_app`/`accord_worker`; limit escape hatch to migrator/SECURITY DEFINER |
| **Medium** | `backend/app/api/routes/employees.py:43–126` | `reveal=true` is capability-gated but not append-only audited | Emit `AuditEvent` (or equivalent) on reveal; prefer dedicated reveal endpoint |
| **Medium** | `backend/app/auth/session.py:83` | `Secure` cookie flag only when `environment==production` | Treat staging as Secure; or key off HTTPS/`base_url` scheme |
| **Medium** | `.github/workflows/ci.yml` | No pip-audit / npm audit / image scan / SBOM despite security.md | Add gate-C scanners; fail on critical direct deps |
| **Medium** | Maker/checker DB | SoD only in service layer (`platform.py:143–145`) | Add trigger/function preventing approve/reject actor = latest submit actor |
| **Medium** | Support break-glass | Not implemented; tests missing | Implement time-boxed audited support sessions per security.md |
| **Low** | `capabilities.py:15–16`, `run_posting.py:76` | No distinct `reverse_run` capability | Add capability + matrix cell if SoD for reverse must differ from post |
| **Low** | Gate D SQL table set (`test_sql_isolation.py:26–30`) | Cross-tenant SQL Gate D omits payroll/master tables | Extend Gate D or formally rely on `tests/rls/*` in release gate |
| **Info** | Missing threat-model suites | `backend/tests/security/*`, `test_forced_rls_coverage.py`, `scripts/ci/pii_fixture_guard.sh` | Restore or retarget proven-by paths in docs |
| **Info** | `frontend/package.json:53,57` | `msw` caret; TypeScript 7 RC | Pin msw; track RC → stable |
| **Info** | CI/API tests use BYPASSRLS-capable DB users | Masks RLS regressions (incl. idempotency bug) | Run a job with `DATABASE_URL` as `accord_app` |

(SoD = segregation of duties.)

---

## Verified controls (summary)

These controls were confirmed in code and migrations, with file:line
evidence:

1. **Forced RLS** ENABLE+FORCE via `rls_policy_sql` on all tenant-owned tables
   across phases 2–5; policies for both `accord_app` and `accord_worker`.
2. **Role bootstrap** `accord_app` / `accord_worker` are `NOSUPERUSER NOBYPASSRLS`
   in `create_roles.sql`.
3. **Tenant GUC binding** uses transaction-local `set_config(..., true)` from
   session `active_organization_id`, not from ordinary resource bodies.
4. **WorkOS AuthKit path** with opaque HttpOnly Lax session cookies, a DB
   session store, rotation, revocation, idle/absolute expiry, and fail-closed
   production settings checks.
5. **Webhook** signature verification + durable event-id dedup.
6. **Capability matrix** largely aligned with ADR 0002; payroll/master mutating
   routes use `require_capability`.
7. **Maker/checker** submitter ≠ approver/rejector in the workflow service.
8. **Immutability triggers** on posted snapshot tables + append-only audit
   tables; audit table DML is revoked.
9. **Idempotency claim path** saves and rebinds GUCs across the mid-command
   commit, **before** the executor runs. The post-executor gap is called out
   above.
10. **Structured log redaction** for pan/pran/account_number/token/secret/cookie
    (and related keys).
11. **Employee PII masking** by default with a capability-gated reveal flag.
12. **Synthetic sanitized fixtures**; gitignore blocks `.env` and real workbooks.
13. **Object storage** opaque tenant-prefixed keys; authorized, audited downloads.

---

## Scope checklist (nine areas)

| # | Area | Verdict |
| --- | --- | --- |
| 1 | Tenancy/RLS | Partial |
| 2 | AuthN/session (+ webhooks) | Partial / webhooks Implemented |
| 3 | AuthZ + maker/checker | Partial |
| 4 | Immutability | Partial |
| 5 | Idempotency GUC | Partial |
| 6 | Secrets/logging | Partial (core Implemented) |
| 7 | PII | Partial |
| 8 | Object storage | Implemented |
| 9 | Dependencies | Partial (Info/Medium CI gap) |

---

## Unverified in this lane

- Full `git log -p` / secret-scanning of the whole history for real
  PAN/account leaks (current tree fixtures look synthetic).
- Live `pip-audit` / `npm audit` results.
- Production deploy TLS/HSTS/backup encryption. These are ops controls
  outside the app code.
- Runtime proof of the idempotency RLS bug against a true `accord_app` DSN.
  This lane has static analysis and test DSN evidence only.

---

*End of security review. Remediation belongs in a future lane — this document
is evidence-only.*
