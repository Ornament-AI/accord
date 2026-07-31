# Threat Model

This is the STRIDE threat model for Accord. Accord is a payroll system of
record. Each deployment serves one organization
([ADR 0011](adr/0011-single-organization.md)). The multi-tenant database
kernel under it stays on as migration debt. It must still fail closed. The
stack is FastAPI/Python + PostgreSQL + React/TS, WorkOS AuthKit, forced RLS,
S3-compatible storage, and immutable posted payroll.

STRIDE is a checklist of six attack classes:

| Letter | Attack class |
| --- | --- |
| S | Spoofing (faking an identity) |
| T | Tampering (changing data you should not change) |
| R | Repudiation (denying an action because there is no trace) |
| I | Information disclosure (seeing data you should not see) |
| D | Denial of service (making the system unusable) |
| E | Elevation of privilege (gaining rights you were not given) |

Phase 0 contract. Cross-ref: [testing.md](testing.md),
[security.md](security.md), [release-acceptance.md](release-acceptance.md),
and ADRs 0001–0011.

**Roles in scope** (code names from `backend/app/auth/capabilities.py`):

| Role | Code name |
| --- | --- |
| Organization administrator | `organization_administrator` |
| Payroll preparer | `payroll_preparer` |
| Payroll reviewer | `payroll_reviewer` |
| Payroll approver | `payroll_approver` |
| Payment/report releaser | `report_releaser` |
| Auditor | `auditor` |
| Platform support administrator | Not a membership role; display-only today, grants no capabilities |

**Commands in scope:** `calculate`, `submit`, `withdraw`, `approve`,
`reject`, `post`, `reverse`.

**Proven-by paths** below exist in the current tree. Where a control is not
implemented, the table says so directly. The dated
[security review](security-review.md) is historical evidence; current gaps are
summarized in [release-readiness.md](release-readiness.md).

---

## Control catalog (named controls)

| Control | Meaning |
| --- | --- |
| forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`) | Tenant tables enable and force RLS so even table owners cannot skip policies |
| NOSUPERUSER NOBYPASSRLS runtime database role | `accord_app` / `accord_worker` never bypass RLS (`backend/scripts/create_roles.sql`) |
| SET LOCAL per-request tenant context | Transaction-local GUCs (`app.organization_id`, etc.) bound by `backend/app/api/deps.py` via `backend/app/tenancy.py` |
| HTTP-only + Secure-in-production + SameSite=Lax cookies (justify Lax for WorkOS redirect auth) | Opaque `accord_session` cookie flags (`backend/app/auth/session.py`) |
| WorkOS webhook signature verification | Reject forged/replayed provider callbacks (`backend/app/auth/webhooks.py`) |
| idempotency keys | Deduplicate workflow/posting commands per org (`backend/app/services/idempotency.py`); calculate is a current gap |
| append-only audit log tables | `audit_events` never updated/deleted in place (triggers + revoked DML) |
| immutability triggers | Block UPDATE/DELETE on posted `payroll_run_version` rows; runtime DML on snapshot tables is also revoked |
| capability/permission checks at the API layer | Role/capability enforcement before commands (`require_capability` in `backend/app/api/deps.py`) |
| masked fields with a capability-gated reveal option | Default mask; explicit reveal requires `reveal_sensitive_fields`; reveal audit is not yet implemented (see [security.md](security.md)) |

**CSRF strategy (normative):** CSRF (cross-site request forgery) tricks a
logged-in browser into sending a request the user never meant. The required
defense has two parts. First, the session cookie uses SameSite=Lax. Second,
each state-changing route must require a synchronizer CSRF token: the server
issues a token, and the client must echo it back in a header. Lax covers the
cross-site redirects that WorkOS login needs. The token guards writes
(POST/PUT/PATCH/DELETE), including same-site adjacent risks. The token is not
built yet — see the current gap inventory in [security.md](security.md).

---

## 1. Session fixation / session hijack

| Field | Detail |
| --- | --- |
| **Vector** | Attacker fixes a pre-auth session id, steals `accord_session` via XSS/network, or reuses a stale cookie after logout. |
| **Impact** | Full account takeover for the victim’s membership; unauthorized payroll commands. |
| **Mitigations** | HTTP-only + Secure + SameSite=Lax cookies (justify Lax for WorkOS redirect auth); opaque `accord_session` (not JWT in cookie); a fresh session row per login and revocation on logout; short idle/absolute expiry; no session tokens in logs; capability/permission checks at the API layer on every command. |
| **Proven-by** | `backend/tests/auth/test_session.py`; `backend/tests/gate_d/test_session_adversarial.py`; auth API tests |

---

## 2. CSRF on state-changing routes

| Field | Detail |
| --- | --- |
| **Vector** | Malicious site triggers browser to send `accord_session` on POST/PUT/PATCH/DELETE (cross-site or same-site adjacent). WorkOS AuthKit redirect flow requires top-level cross-site navigations that carry Lax cookies. |
| **Impact** | Unauthorized `submit` / `approve` / `post` / `reverse` or membership changes without user intent. |
| **Mitigations** | SameSite=Lax session cookie **plus** synchronizer CSRF token on state-changing routes (header must match server-issued token). Lax alone is insufficient for state-changing APIs; the synchronizer token is mandatory for mutations. GET/safe navigations remain CSRF-safe by design. |
| **Proven-by** | Gap: signed OAuth-state tests exist, but no synchronizer-token middleware or mutation suite exists |

---

## 3. WorkOS webhook replay / forgery

| Field | Detail |
| --- | --- |
| **Vector** | Attacker posts forged WorkOS webhook payloads, or replays a legitimate signed payload to re-apply identity changes. |
| **Impact** | Corrupted local identity metadata now; unauthorized access changes if membership handling is added without preserving the same controls. |
| **Mitigations** | WorkOS webhook signature verification; timestamp/skew checks; idempotent processing with durable event-id dedup (`webhook_events` table). The current handler updates an existing user for `user.updated`; it does not grant or change memberships. |
| **Proven-by** | `backend/tests/api/test_webhooks_workos.py` |

---

## 4. Organization confusion / cross-tenant IDOR

IDOR (insecure direct object reference) means you guess or supply someone
else’s resource id and get access to it. The product is single-organization
now, but the kernel still scopes rows by `organization_id`. It must fail
closed when the context is missing or wrong.

| Field | Detail |
| --- | --- |
| **Vector** | Client supplies a foreign resource UUID; a query misses `WHERE organization_id = …`; a worker job runs without `SET LOCAL`; object key enumeration. |
| **Impact** | Breach-class exposure of employees, bank details, and payroll results outside valid org context. |
| **Mitigations** | forced RLS (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`); NOSUPERUSER NOBYPASSRLS runtime database role (`accord_app` / `accord_worker`); SET LOCAL per-request tenant context from session `active_organization_id` (clients never choose org via path/body for ordinary resources); capability/permission checks at the API layer; S3 keys scoped `{organization_id}/{object_uuid}`. |
| **Proven-by** | `backend/tests/rls/`; `backend/tests/gate_d/`; `backend/tests/api/test_tenant_context.py`; artifact API/service tests |

---

## 5. Privilege escalation between roles

| Field | Detail |
| --- | --- |
| **Vector** | Preparer invokes `approve`/`post`; reviewer self-approves own submission; Auditor mutates data; forged role claim in session. |
| **Impact** | Bypass of segregation of duties; fraudulent payroll release. |
| **Mitigations** | capability/permission checks at the API layer for all six membership roles; server-side role from membership tables (not client claims); append-only audit log tables. |
| **Proven-by** | `backend/tests/gate_d/test_capability_matrix.py`; `backend/tests/api/test_deps_capabilities.py`; workflow API/service suites |

---

## 6. Maker/checker bypass

Maker/checker (dual control) means the person who prepares a run cannot also
approve it.

| Field | Detail |
| --- | --- |
| **Vector** | Same actor performs prepare and approve; skip `submit`; direct `post` without approvals; race that collapses dual control. |
| **Impact** | Fraudulent or erroneous payroll posts without independent review. |
| **Mitigations** | Maker/checker workflow enforced in domain + API (`backend/app/services/run_workflow.py`); distinct capabilities for preparer vs approver; reject self-approval; locking where needed; idempotency and append-only audit for workflow/posting commands. Calculate is row-locked but lacks idempotency and audit. |
| **Proven-by** | `backend/tests/services/test_run_workflow.py`; `backend/tests/api/test_run_workflow.py`; `backend/tests/services/test_idempotency.py` |

---

## 7. Posted-data tampering (API + direct SQL)

| Field | Detail |
| --- | --- |
| **Vector** | API `UPDATE` on posted `payroll_run_version`; SQL client as table owner; restore of altered dump; reverse without audit. |
| **Impact** | Silent corruption of statutory/payment truth; undetectable fraud. |
| **Mitigations** | Immutable posted `payroll_run_version`; immutability triggers plus revoked runtime UPDATE/DELETE on snapshot tables; API rejects mutate-in-place (corrections via `reverse` + new version); NOSUPERUSER NOBYPASSRLS runtime database role; append-only audit log tables; content hash on posted results. |
| **Proven-by** | Posting API/service suites; `backend/tests/rls/test_immutable_grants.py`; `backend/tests/rls/test_payroll_run_rls.py` |

---

## 8. Sensitive-PII exposure

| Field | Detail |
| --- | --- |
| **Vector** | PAN/bank/PRAN/GPF/full name in API responses by default, logs, fixtures, screenshots, or golden artifacts; overly broad list endpoints. |
| **Impact** | Regulatory/privacy breach; irreversible identifier leakage. |
| **Mitigations** | masked fields with capability-gated reveal; structured log redaction ([security.md](security.md)); sanitized fixtures only (`fixtures/sanitized/june-2026/`); never commit real June 2026 workbook PII. Reveal auditing and a dedicated fixture-PII CI guard remain gaps. |
| **Proven-by** | Employee API/service suites; `backend/tests/test_log_redaction.py`; synthetic fixture validator |

---

## 9. Object storage enumeration / leak

| Field | Detail |
| --- | --- |
| **Vector** | Guessable keys; listing another tenant’s prefix; pre-signed URL leakage; missing auth on download. |
| **Impact** | Exfiltration of Excel/PDF payroll exports and artifacts. |
| **Mitigations** | Opaque `{organization_id}/{object_uuid}` keys (`backend/app/storage/protocol.py`); authorization on artifact metadata under forced RLS; SET LOCAL per-request tenant context before metadata reads; authenticated backend-streamed downloads; append-only `artifact.download` access events (`backend/app/services/artifacts.py`); no PII in object paths. |
| **Proven-by** | `backend/tests/storage/`; `backend/tests/services/test_artifacts.py`; `backend/tests/api/test_artifacts.py` |

---

## 10. Support-administrator abuse

| Field | Detail |
| --- | --- |
| **Vector** | Platform support administrator accesses tenant data without ticket, retains access indefinitely, or impersonates silently. |
| **Impact** | Insider breach; loss of customer trust; unauditable access. |
| **Mitigations** | Break-glass only; time-boxed support sessions; mandatory append-only audit log tables (support actor + target `organization_id`); distinct from normal RLS path; capability/permission checks at the API layer for platform support; no standing production data access. See the [security.md](security.md) support access policy. Current code has no support elevation path at all — `is_platform_admin` is display-only, which fails closed. |
| **Proven-by** | Gap: there is no support elevation path; default deny is enforced by the absence of a capability bypass |

---

## 11. Supply-chain / dependency risks

| Field | Detail |
| --- | --- |
| **Vector** | Compromised PyPI/npm package; vulnerable base image; unsigned CI artifact. |
| **Impact** | RCE in API/worker, credential theft, silent backdoor in payroll path. |
| **Mitigations** | Dependency/container scanning + SBOM in CI (pip-audit/npm audit, image scan, syft/cyclonedx); pin lockfiles; block critical vulns vs advisory for lower severity ([security.md](security.md)); least-privilege runtime roles. Scanner/SBOM CI steps are not wired yet — see [security-review.md](security-review.md). |
| **Proven-by** | Gap: current CI has no dependency/container scanner or SBOM job |

---

## 12. Backup / restore exposure

| Field | Detail |
| --- | --- |
| **Vector** | Unencrypted backups; restore into shared DB without RLS; backup bucket world-readable; PITR clone reused without credential rotation. |
| **Impact** | Bulk disclosure of payroll data; long-lived credential reuse. |
| **Mitigations** | Encrypted backups; restricted backup credentials; restore rehearsals prove forced RLS and NOSUPERUSER NOBYPASSRLS runtime database role still hold; SET LOCAL per-request tenant context required after restore; gate K in [release-acceptance.md](release-acceptance.md). |
| **Proven-by** | `scripts/backup-restore.sh` covers restore integrity; RLS/runtime-role suites exist separately. A combined post-restore RLS rehearsal remains a gap. |

---

## STRIDE summary matrix

| Threat # | Spoofing | Tampering | Repudiation | Info disclosure | DoS | Elevation |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Session | ✓ | | | ✓ | | ✓ |
| 2 CSRF | ✓ | ✓ | | | | ✓ |
| 3 Webhooks | ✓ | ✓ | ✓ | | | ✓ |
| 4 Cross-tenant | | ✓ | | ✓ | | ✓ |
| 5 Privilege | | | | | | ✓ |
| 6 Maker/checker | | ✓ | ✓ | | | ✓ |
| 7 Posted tamper | | ✓ | ✓ | | | |
| 8 PII | | | | ✓ | | |
| 9 Object storage | | | | ✓ | | |
| 10 Support abuse | ✓ | | ✓ | ✓ | | ✓ |
| 11 Supply chain | ✓ | ✓ | | ✓ | ✓ | ✓ |
| 12 Backup/restore | | ✓ | | ✓ | | ✓ |

---

## Threat → control → suite quick map

| Threat | Current proof | Gap |
| --- | --- | --- |
| Session fixation / hijack | Session/auth and adversarial tests | Staging cookie security remains environment-dependent |
| CSRF | Signed OAuth-state tests | No synchronizer token for general mutations |
| WorkOS webhook replay/forgery | WorkOS webhook API suite | None identified in current contract |
| Org confusion / IDOR | RLS, gate D, tenant-context, and artifact suites | Re-run for the release commit |
| Privilege escalation | Capability matrix and API dependency suites | Support elevation is intentionally absent |
| Maker/checker bypass | Workflow/idempotency API and service suites | Calculate lacks idempotency and audit |
| Posted-data tampering | Posting plus immutable-grant/RLS suites | None identified in current contract |
| Sensitive-PII exposure | Employee masking, log-redaction, fixture validation | Reveal audit and fixture-PII CI guard |
| Object storage leak | Storage/artifact suites with audited backend streaming | Environment persistence rehearsal |
| Support abuse | Default deny | No time-boxed audited support path |
| Supply chain | Pinned manifests/lockfile | No scanner or SBOM CI evidence |
| Backup / restore | Backup helper plus separate RLS/runtime-role suites | No combined post-restore RLS automation |

---

## Out of scope for this Phase 0 document

- Physical data-center threats.
- Customer endpoint compromise (malware on clerk workstations) beyond the
  session hardening and CSRF controls above.
- Cryptanalytic breaks of TLS or of WorkOS itself. We assume current industry
  primitives hold.

Residual risk is accepted only with an explicit signed exception in the
release acceptance packet ([release-acceptance.md](release-acceptance.md)).
