# Security

This is the security baseline for Accord. Accord is an open-source payroll
system of record. Each deployment serves one organization
([ADR 0011](adr/0011-single-organization.md)). The multi-tenant database
kernel under it stays in place as migration debt. The stack is FastAPI/Python
with PostgreSQL and a React/TS frontend. Login uses WorkOS AuthKit. The
database enforces forced row-level security (RLS). RLS means Postgres itself
filters every row by tenant. Files live in S3-compatible object storage.
Posted payroll data is immutable: it cannot be changed in place.

Each table below lists a control, what it must do, and what we expect at
release time. Cross-ref: [threat-model.md](threat-model.md),
[testing.md](testing.md), [release-acceptance.md](release-acceptance.md), and
ADRs 0001–0004, 0008–0011.

Suite paths in this page are current tree paths. Missing controls are stated as
gaps instead of being assigned hypothetical filenames. The dated
[security-review.md](security-review.md) is historical evidence; this page and
[release-readiness.md](release-readiness.md) describe the current baseline.

---

## Secret handling

| Control | Behavior | Expectation |
| --- | --- | --- |
| Env / secret manager | Runtime secrets load from environment or a secret manager (never from committed files). | `WORKOS_API_KEY`, WorkOS webhook secrets, `DATABASE_URL` / migrator DSN, S3 keys, session signing keys exist only in env/secret store. |
| No commit of secrets | `.env`, private keys, WorkOS secrets, DB/S3 credentials are gitignored and must stay out of history. | No dedicated secret-scanning CI job is currently wired. Review changes for secret-shaped values and rotate immediately if one leaks. |
| Rotation | Support rotation without downtime where possible (dual-key session accept window, staged DB password rotate). | Documented rotation runbook; post-incident rotation is mandatory. |
| Least privilege | Distinct credentials per role/purpose. | Migrator ≠ app ≠ worker ≠ backup reader (see DB role separation). |
| Production fail-closed settings | `backend/app/config.py` (`_validate_production_invariants`) refuses empty `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_REDIRECT_URI`, `WORKOS_WEBHOOK_SECRET`, `SESSION_SECRET_KEY`, and `MIGRATIONS_DATABASE_URL`; it rejects `DEV_AUTH_BYPASS` in production. The redirect has a localhost default, so omission is not detected and operators must override it with the registered production callback. | Secret/auth omissions fail at startup; deployment validation must separately prove the redirect URI is production-safe. |

---

## Cookie / session

Accord uses WorkOS AuthKit and one opaque **`accord_session`** cookie. The
cookie holds only a signed session row id. The real session lives in a
Postgres table (`DatabaseSessionStore` in `backend/app/auth/session.py`).
Browsers never receive bearer JWTs for ordinary sessions.

| Control | Behavior | Expectation |
| --- | --- | --- |
| HTTP-only | Cookie not readable from JavaScript (`httponly=True` in `backend/app/auth/session.py`). | XSS cannot exfiltrate `accord_session` via `document.cookie`. |
| Secure | Cookie is marked Secure when `ENVIRONMENT=production`. A staging deployment using another environment value does not receive that flag; the [security review](security-review.md) records this gap. | Run internet-facing staging with the production security mode, or close the environment-policy gap before relying on a separate staging value. |
| SameSite=Lax | Cookie sent on top-level navigations; withheld on most cross-site subrequests. | **Why Lax, not Strict:** the AuthKit login/callback flow needs top-level cross-site redirects that must carry the session cookie; `Strict` breaks that flow. Lax alone is **not** enough CSRF defense for APIs. |
| Synchronizer CSRF | State-changing routes must require a synchronizer CSRF token — a server-issued token the client echoes back in a header. | **Not yet implemented.** SameSite=Lax and signed OAuth `state` exist today, but general mutations do not have the required token proof. |
| Expiry / refresh | Absolute 12-hour TTL (`SESSION_MAX_AGE_SECONDS`) plus an idle timeout (`SESSION_IDLE_TIMEOUT_SECONDS`, default 2 h). A fresh session row is minted at login; logout revokes the row. | Covered by `backend/tests/auth/test_session.py` and `backend/tests/gate_d/test_session_adversarial.py`. |
| Login rate limits | Password and magic-code login routes are rate limited per client IP (`backend/app/middleware/rate_limit.py`; decorators in `backend/app/api/routes/auth.py`). | Credential stuffing and code guessing are throttled. |
| Logging | Session tokens never appear in structured logs. | Redaction rules below. |

---

## TLS / reverse-proxy

### (1) Docker Compose self-hosted

| Control | Behavior | Expectation |
| --- | --- | --- |
| Edge proxy | Caddy, Traefik, or nginx terminates TLS in front of the API/UI containers. | App containers speak HTTP on an internal network only. |
| ACME | Proxy obtains/renews certificates via ACME (Let’s Encrypt or equivalent). | Valid public certs; automated renewal; alert on failure. |
| Headers | Proxy or app sets HSTS (when HTTPS is confirmed) and standard security headers. The app already injects CSP, `X-Frame-Options: DENY`, nosniff, referrer and permissions policies via `backend/app/middleware/security_headers.py`. | No mixed-content session cookies. |

### (2) Managed / cloud load balancer

| Control | Behavior | Expectation |
| --- | --- | --- |
| LB TLS | Cloud LB / managed certificate terminates TLS. | TLS 1.2+ only; strong cipher policy. |
| HSTS | HSTS enabled at the edge for production hostnames. HSTS (HTTP Strict Transport Security) tells browsers to refuse plain HTTP. | Browsers refuse cleartext downgrade. |
| Origin trust | Backend trusts only the LB / private network for client IPs and HTTPS assumption. | Document `X-Forwarded-*` trust boundaries. |

---

## Database role separation

| Role | Privileges | Purpose |
| --- | --- | --- |
| `accord_migrator` | Schema owner; may `BYPASSRLS` for migrations/DDL | Alembic migrations and controlled data migrations only |
| `accord_app` | `NOSUPERUSER NOBYPASSRLS` runtime database role | API request transactions |
| `accord_worker` | `NOSUPERUSER NOBYPASSRLS` runtime database role | Background jobs; must `SET LOCAL` tenant context after claim |

Roles are bootstrapped by `backend/scripts/create_roles.sql` (never by
Alembic).

**Why different credentials**

1. Migrations need ownership and `BYPASSRLS` to apply DDL and backfills. The
   API must **never** hold those rights.
2. If the API credential can bypass RLS, forced RLS
   (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) is theater.
3. A leaked app password has a small blast radius. It cannot rewrite the
   schema or read all rows as a superuser.

**Runtime behavior**

- Every tenant request binds transaction-local context GUCs
  (`app.organization_id`, `app.user_id`, `app.request_id`) before queries. A
  GUC is a Postgres setting; RLS policies read it to pick the tenant.
  `require_tenant_context` in `backend/app/api/deps.py` calls
  `bind_tenant_context` in `backend/app/tenancy.py`. That helper uses
  `set_config(..., true)`, the `SET LOCAL` form that is safe with pooled
  connections.
- If the GUC is unset, the system fails closed: RLS matches no rows and
  rejects writes.
- Current coverage: `backend/tests/rls/` (identity, master-data, payroll-run,
  platform, helper, and immutable-grant suites) plus `backend/tests/gate_d/`,
  which connect as the restricted runtime roles and exercise empty/wrong GUCs.

---

## Backup / PITR

PITR means point-in-time recovery: restoring the database to a chosen moment.

| Topic | Baseline |
| --- | --- |
| Frequency | Continuous WAL archiving (or provider equivalent) + daily full base backups at minimum. |
| Encryption | At rest with managed KMS/CMEK or equivalent; in transit via TLS to backup store. |
| Retention | Meet customer/regulatory retention; default engineering floor documented in ops runbook (e.g. ≥ 30 days backups). |
| PITR window | Provider/configured PITR window documented per environment; production window ≥ 7 days unless waived. |
| Access | Backup credentials are not `accord_app`; restore uses controlled procedure. |
| Restore rehearsals | Periodic restore into an isolated environment; prove forced RLS and the `NOSUPERUSER NOBYPASSRLS` runtime roles still enforce isolation. `scripts/backup-restore.sh` rehearses logical restore integrity, but the post-restore RLS proof is not automated. Gate **K** in [release-acceptance.md](release-acceptance.md). |

Threat mapping: [threat-model.md](threat-model.md) §12 (Backup / restore exposure).

---

## Dependency / container scanning + SBOM

An SBOM (software bill of materials) is a machine-readable list of every
package inside a release.

| Control | Behavior | Expectation |
| --- | --- | --- |
| Python | `pip-audit` (or equivalent) on lockfiles in CI | Critical/high policy below |
| JavaScript | `npm audit` (or equivalent) on frontend lockfile | Critical/high policy below |
| Container images | Image scan on build (Trivy/Grype or cloud scanner) | Base OS CVEs tracked |
| SBOM | syft and/or CycloneDX SBOM attached to release artifacts | SBOM stored with release evidence |
| Block vs advisory | **Block** merge/deploy on critical (and agreed high) findings in direct runtime deps without waiver; **advisory** for transitive/low with ticket SLA | Waivers time-bounded and signed |

Status: `.github/workflows/ci.yml` runs lint, tests, migrations, and Docker
builds, but does not yet wire these scanners or SBOM steps. The
[security review](security-review.md) tracks this as a Medium finding.

Threat mapping: [threat-model.md](threat-model.md) §11 (Supply-chain / dependency risks).
Evidence feeds gate C / security reviewer sign-off in
[release-acceptance.md](release-acceptance.md).

---

## Structured logs redaction

| Control | Behavior | Expectation |
| --- | --- | --- |
| Format | JSON structured logs (structlog) with `request_id`; wired in `backend/app/logging_config.py`. | Machine-parseable; correlatable. |
| Never log | PAN, bank account numbers, PRAN, GPF numbers, full legal names where avoidable, session tokens, passwords, API keys, WorkOS secrets, raw webhook signatures. | CI/log review finds zero hits. The `redact_sensitive` processor in `backend/app/logging_config.py` redacts `pan`, `pran`, `account_number`, `password`, `secret`, `token`, `authorization`, and `cookie` keys recursively. |
| Prefer | Stable opaque ids (`employee_id`, `organization_id`, `payroll_run_id`). | Support can debug without PII. |
| PII reveal | The API shows masked fields by default; `reveal=true` is gated on `reveal_sensitive_fields` (`backend/app/api/routes/employees.py`). The reveal is **not yet audited**. | Masking/capability coverage exists in the employee API/service suites; an append-only reveal access event remains required. |
| Fixtures | Real June 2026 workbook PII never enters git/CI/logs; only synthetic data in `fixtures/sanitized/june-2026/`. | The fixture validator exists; a dedicated CI hash/name guard remains missing. See [testing.md](testing.md). |

---

## Support access policy

Platform support administrator access is **not** ordinary tenancy.

| Control | Behavior | Expectation |
| --- | --- | --- |
| Break-glass | Explicit break-glass grant required; no standing production data access. | Default deny. |
| Time-boxing | Access expires automatically (short TTL). | No indefinite impersonation. |
| Mandatory audit | Every support read/write emits append-only audit events with the support actor and target `organization_id`. | Auditable after the fact. |
| Distinct from normal RLS | The support path is a controlled elevation, not "RLS off" for `accord_app`. Prefer a dedicated procedure/role with logging; never ship `BYPASSRLS` on the default API role. | Normal tenant users remain under forced RLS + `SET LOCAL` per-request tenant context. |
| Capability checks | Capability/permission checks at the API layer for platform support actions. | No support elevation path or suite exists today; default deny is the current behavior. |

Status: the break-glass path is not built yet. Today `is_platform_admin` is
display-only with **no** capability bypass
(`backend/app/auth/capabilities.py`), so support access fails closed.

Threat mapping: [threat-model.md](threat-model.md) §10 (Support-administrator abuse).
Gate checklist item in [release-acceptance.md](release-acceptance.md).

---

## Posted payroll immutability (security lens)

| Control | Behavior | Expectation |
| --- | --- | --- |
| API | A posted `payroll_run_version` cannot be mutated in place; corrections use `reverse` + a new version (`backend/app/api/routes/run_posting.py`, `backend/app/services/run_posting.py`). | Covered by `backend/tests/api/test_run_posting.py` and `backend/tests/services/test_run_posting.py`. |
| SQL | Immutability triggers (`accord_forbid_update_delete`) block UPDATE/DELETE even if the API is bypassed. Migration `b33a3a7b5f84_revoke_immutable_table_dml.py` also revokes UPDATE/DELETE/TRUNCATE on the snapshot tables from `accord_app` / `accord_worker`, so the trigger escape hatch is useless to runtime roles. | Covered by `backend/tests/rls/test_immutable_grants.py` and `backend/tests/rls/test_payroll_run_rls.py`. |
| Audit | Append-only `audit_events` (UPDATE/DELETE revoked in migrations) record post/reverse with actor and content hash. | Traceability for gate H / final checklist. |

---

## AuthN / AuthZ quick reference

| Topic | Baseline |
| --- | --- |
| Identity | WorkOS AuthKit; memberships/roles in Accord Postgres. Login paths: hosted redirect, password, and magic-code — all server-side (`backend/app/api/routes/auth.py`, `backend/app/auth/adapters.py`). |
| Roles | Membership roles (`backend/app/auth/capabilities.py`): `organization_administrator`, `payroll_preparer`, `payroll_reviewer`, `payroll_approver`, `report_releaser` (payment/report releaser), `auditor`. Platform support administrator is display-only this phase — it is not a membership role and grants no capabilities. |
| Commands | `calculate`, `submit`, `withdraw`, `approve`, `reject`, `post`, `reverse` are capability-checked. Workflow/posting commands use the idempotency/audit services; `calculate` currently does neither and can append another version on a distinct retry. `reverse` reuses `post_run`; there is no separate reverse capability. |
| Tenancy | `organization_id` on tenant rows; forced RLS; `SET LOCAL` per-request tenant context via `backend/app/api/deps.py` + `backend/app/tenancy.py`. |
| Webhooks | WorkOS webhook signature verification in `backend/app/auth/webhooks.py`; covered by `backend/tests/api/test_webhooks_workos.py`. |
| Money | Decimal / minor-units only (`backend/app/schemas/money.py`); enforced by `backend/tests/domain/test_no_float_guard.py` and money/property suites. |

---

## Verification map

| Area | Current coverage | Remaining gap |
| --- | --- | --- |
| Session hardening | `backend/tests/auth/test_session.py`, `backend/tests/gate_d/test_session_adversarial.py` | Secure-cookie behavior treats staging as non-production |
| CSRF | Signed OAuth-state coverage in session/auth tests | No synchronizer token on general mutations |
| WorkOS webhooks | `backend/tests/api/test_webhooks_workos.py` | None identified in current contract |
| Privilege escalation | `backend/tests/gate_d/test_capability_matrix.py`, `backend/tests/api/test_deps_capabilities.py` | Support elevation is intentionally absent |
| PII masking / reveal | Employee API/service suites | Reveal read is not audit-logged |
| Support break-glass | Default deny; no capability bypass | No time-boxed audited support path |
| Posted SQL immutability | `backend/tests/rls/test_immutable_grants.py`, `backend/tests/rls/test_payroll_run_rls.py` | None identified in current contract |
| Backup/restore RLS | Runtime-role and RLS suites; `scripts/backup-restore.sh` integrity rehearsal | No automated combined restore-under-runtime-role proof |
| Fail-closed RLS | `backend/tests/rls/`, `backend/tests/gate_d/`, tenant-context API tests | Re-run against the release commit |
| PII fixture guard | Synthetic validator and review policy | No dedicated CI hash/name guard |
| Float ban | `backend/tests/domain/test_no_float_guard.py` | None identified in current contract |

This baseline is mandatory for production promotion. Deviations require a
signed, time-bounded waiver referencing [threat-model.md](threat-model.md)
and [release-acceptance.md](release-acceptance.md).
