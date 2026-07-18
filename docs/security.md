# Security

Operational security baseline for Accord (multi-tenant payroll SaaS:
FastAPI/Python + PostgreSQL + React/TS, WorkOS AuthKit, forced RLS,
S3-compatible storage, immutable posted payroll).

Tone: control → behavior → expectation. Cross-ref:
[threat-model.md](threat-model.md), [testing.md](testing.md),
[release-acceptance.md](release-acceptance.md), ADRs 0001–0004 / 0008–0010.

---

## Secret handling

| Control | Behavior | Expectation |
| --- | --- | --- |
| Env / secret manager | Runtime secrets load from environment or a secret manager (never from committed files). | `WORKOS_API_KEY`, WorkOS webhook secrets, `DATABASE_URL` / migrator DSN, S3 keys, session signing keys exist only in env/secret store. |
| No commit of secrets | `.env`, private keys, WorkOS secrets, DB/S3 credentials are gitignored and absent from history. | Pre-commit / CI reject accidental secret-shaped commits. Rotate immediately if leaked. |
| Rotation | Support rotation without downtime where possible (dual-key session accept window, staged DB password rotate). | Documented rotation runbook; post-incident rotation is mandatory. |
| Least privilege | Distinct credentials per role/purpose. | Migrator ≠ app ≠ worker ≠ backup reader (see DB role separation). |

---

## Cookie / session

Accord uses WorkOS AuthKit and an opaque **`accord_session`** cookie
(server-side session store). Clients do not receive bearer JWTs for ordinary
browser sessions.

| Control | Behavior | Expectation |
| --- | --- | --- |
| HTTP-only | Cookie not readable from JavaScript. | XSS cannot exfiltrate `accord_session` via `document.cookie`. |
| Secure | Cookie sent only over HTTPS in non-local environments. | No cleartext session on the wire in staging/production. |
| SameSite=Lax | Cookie sent on top-level navigations; withheld on most cross-site subrequests. | **Justify Lax for WorkOS redirect auth:** AuthKit login/callback requires top-level cross-site redirects that must carry the session cookie; `Strict` breaks that flow. Lax alone is **not** sufficient CSRF defense for APIs. |
| Synchronizer CSRF | State-changing routes require a synchronizer CSRF token; request header must match server-issued token. | SameSite=Lax session cookie **plus** synchronizer CSRF token on POSTs/PUTs/PATCHes/DELETEs. Lax covers WorkOS redirect navigations; synchronizer tokens defend mutations including same-site adjacent risks. Proven by `backend/tests/security/test_csrf.py`. |
| Expiry / refresh | Idle and absolute session TTLs; rotate session id on login and organization switch. | Stolen cookies have bounded lifetime; fixation resisted. Proven by `backend/tests/security/test_session_hardening.py`. |
| Logging | Session tokens never appear in structured logs. | Redaction rules below. |

---

## TLS / reverse-proxy

### (1) Docker Compose self-hosted

| Control | Behavior | Expectation |
| --- | --- | --- |
| Edge proxy | Caddy, Traefik, or nginx terminates TLS in front of the API/UI containers. | App containers speak HTTP on an internal network only. |
| ACME | Proxy obtains/renews certificates via ACME (Let’s Encrypt or equivalent). | Valid public certs; automated renewal; alert on failure. |
| Headers | Proxy or app sets HSTS (when HTTPS is confirmed), and standard security headers. | No mixed-content session cookies. |

### (2) Managed / cloud load balancer

| Control | Behavior | Expectation |
| --- | --- | --- |
| LB TLS | Cloud LB / managed certificate terminates TLS. | TLS 1.2+ only; strong cipher policy. |
| HSTS | HSTS enabled at the edge for production hostnames. | Browsers refuse cleartext downgrade. |
| Origin trust | Backend trusts only the LB / private network for client IPs and HTTPS assumption. | Document `X-Forwarded-*` trust boundaries. |

---

## Database role separation

| Role | Privileges | Purpose |
| --- | --- | --- |
| `accord_migrator` | Schema owner; may `BYPASSRLS` for migrations/DDL | Alembic migrations and controlled data migrations only |
| `accord_app` | `NOSUPERUSER NOBYPASSRLS` runtime database role | API request transactions |
| `accord_worker` | `NOSUPERUSER NOBYPASSRLS` runtime database role | Background jobs; must `SET LOCAL` tenant context after claim |

**Why different credentials**

1. Migrations need ownership/`BYPASSRLS` to apply DDL and backfills; the API must
   **never** hold those privileges.
2. If the API credential can bypass RLS, forced RLS
   (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) is theater.
3. Credential leak blast radius: a leaked app password cannot rewrite schema or
   read all tenants as superuser.

**Runtime behavior**

- Every tenant request: SET LOCAL per-request tenant context
  (`app.organization_id`, `app.user_id`, `app.request_id`) before queries.
- Fail closed when GUC unset (RLS predicates match no rows / reject writes).
- Proven by: `backend/tests/rls/test_cross_tenant_isolation.py`,
  `backend/tests/rls/test_forced_rls_coverage.py`.

---

## Backup / PITR

| Topic | Baseline |
| --- | --- |
| Frequency | Continuous WAL archiving (or provider equivalent) + daily full base backups at minimum. |
| Encryption | At rest with managed KMS/CMEK or equivalent; in transit via TLS to backup store. |
| Retention | Meet customer/regulatory retention; default engineering floor documented in ops runbook (e.g. ≥ 30 days backups). |
| PITR window | Provider/configured PITR window documented per environment; production window ≥ 7 days unless waived. |
| Access | Backup credentials are not `accord_app`; restore uses controlled procedure. |
| Restore rehearsals | Periodic restore into isolated environment; prove forced RLS and NOSUPERUSER NOBYPASSRLS runtime database role still enforce isolation. Suite: `backend/tests/security/test_backup_restore_rls.py`. Gate **K** in [release-acceptance.md](release-acceptance.md). |

Threat mapping: [threat-model.md](threat-model.md) §12 (Backup / restore exposure).

---

## Dependency / container scanning + SBOM

| Control | Behavior | Expectation |
| --- | --- | --- |
| Python | `pip-audit` (or equivalent) on lockfiles in CI | Critical/high policy below |
| JavaScript | `npm audit` (or equivalent) on frontend lockfile | Critical/high policy below |
| Container images | Image scan on build (Trivy/Grype or cloud scanner) | Base OS CVEs tracked |
| SBOM | syft and/or CycloneDX SBOM attached to release artifacts | SBOM stored with release evidence |
| Block vs advisory | **Block** merge/deploy on critical (and agreed high) findings in direct runtime deps without waiver; **advisory** for transitive/low with ticket SLA | Waivers time-bounded and signed |

Threat mapping: [threat-model.md](threat-model.md) §11 (Supply-chain / dependency risks).
Evidence feeds gate C / security reviewer sign-off in
[release-acceptance.md](release-acceptance.md).

---

## Structured logs redaction

| Control | Behavior | Expectation |
| --- | --- | --- |
| Format | JSON structured logs (structlog or equivalent) with `request_id`. | Machine-parseable; correlatable. |
| Never log | PAN, bank account numbers, PRAN, GPF numbers, full legal names where avoidable, session tokens, passwords, API keys, WorkOS secrets, raw webhook signatures. | CI/log review finds zero hits; redaction middleware/processors enforced. |
| Prefer | Stable opaque ids (`employee_id`, `organization_id`, `payroll_run_id`). | Support can debug without PII. |
| PII reveal | Application may show masked fields; full reveal only via masked fields with a separate audited "reveal" action/endpoint. | Reveal writes append-only audit log tables. Proven by `backend/tests/security/test_pii_masking.py`. |
| Fixtures | Real June 2026 workbook PII never enters git/CI/logs. | `scripts/ci/pii_fixture_guard.sh` + pre-commit policy in [testing.md](testing.md). |

---

## Support access policy

Platform support administrator access is **not** ordinary tenancy.

| Control | Behavior | Expectation |
| --- | --- | --- |
| Break-glass | Explicit break-glass grant required; no standing production data access. | Default deny. |
| Time-boxing | Access expires automatically (short TTL). | No indefinite impersonation. |
| Mandatory audit | Every support read/write emits append-only audit log tables events with support actor + target `organization_id`. | Auditable after the fact. |
| Distinct from normal RLS | Support path is a controlled elevation, not “RLS off” for `accord_app`. Prefer dedicated procedure/role with logging; never ship BYPASSRLS on the default API role. | Normal tenant users remain under forced RLS + SET LOCAL per-request tenant context. |
| Capability checks | capability/permission checks at the API layer for Platform support administrator actions. | Proven by `backend/tests/security/test_support_break_glass.py`. |

Threat mapping: [threat-model.md](threat-model.md) §10 (Support-administrator abuse).
Gate checklist item in [release-acceptance.md](release-acceptance.md).

---

## Posted payroll immutability (security lens)

| Control | Behavior | Expectation |
| --- | --- | --- |
| API | Posted `payroll_run_version` cannot be mutated in place; corrections use `reverse` + new version. | Proven by `backend/tests/workflow/test_posted_immutability.py`. |
| SQL | immutability triggers block UPDATE/DELETE even if API is bypassed. | Proven by `backend/tests/security/test_posted_sql_immutability.py`. |
| Audit | append-only audit log tables record post/reverse with actor and content hash. | Traceability for gate H / final checklist. |

---

## AuthN / AuthZ quick reference

| Topic | Baseline |
| --- | --- |
| Identity | WorkOS AuthKit; memberships/roles in Accord Postgres |
| Roles | Organization administrator; Payroll preparer; Payroll reviewer; Payroll approver; Payment/report releaser; Auditor; Platform support administrator |
| Commands | `calculate`, `submit`, `withdraw`, `approve`, `reject`, `post`, `reverse` — each capability-checked, idempotent where state-changing, audited |
| Tenancy | `organization_id` on tenant rows; forced RLS; SET LOCAL per-request tenant context |
| Webhooks | WorkOS webhook signature verification (`backend/tests/security/test_workos_webhooks.py`) |
| Money | Decimal / minor-units only; `scripts/ci/no_float_payroll_domain.sh` |

---

## Verification map

| Area | Suite / script |
| --- | --- |
| Session hardening | `backend/tests/security/test_session_hardening.py` |
| CSRF | `backend/tests/security/test_csrf.py` |
| WorkOS webhooks | `backend/tests/security/test_workos_webhooks.py` |
| Privilege escalation | `backend/tests/security/test_privilege_escalation.py` |
| PII masking / reveal | `backend/tests/security/test_pii_masking.py` |
| Support break-glass | `backend/tests/security/test_support_break_glass.py` |
| Posted SQL immutability | `backend/tests/security/test_posted_sql_immutability.py` |
| Backup/restore RLS | `backend/tests/security/test_backup_restore_rls.py` |
| Cross-tenant RLS | `backend/tests/rls/test_cross_tenant_isolation.py` |
| Forced RLS coverage | `backend/tests/rls/test_forced_rls_coverage.py` |
| PII fixture guard | `scripts/ci/pii_fixture_guard.sh` |
| Float ban | `scripts/ci/no_float_payroll_domain.sh` |

This baseline is mandatory for production promotion. Deviations require a
signed, time-bounded waiver referencing [threat-model.md](threat-model.md)
and [release-acceptance.md](release-acceptance.md).
