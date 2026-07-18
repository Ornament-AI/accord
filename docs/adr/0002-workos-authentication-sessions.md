# ADR-0002: WorkOS Authentication and Sessions

**Status:** Proposed

## Context

Accord needs authentication for a multi-organization payroll SaaS. Atlas uses Firebase Auth in a single-tenant deployment. Accord instead uses **WorkOS** (AuthKit / SSO) for identity, with **true multi-org tenancy** backed by Accord’s own Postgres membership and role model (see [0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)).

Requirements:

1. Browser login via WorkOS without exposing WorkOS tokens to frontend JavaScript.
2. Accord-minted secure session cookies as the only credential the SPA sees.
3. Authorization sourced exclusively from local `organization_memberships` and capabilities — not from WorkOS Organization membership alone.
4. Active organization selection with safe switching and bounded staleness when memberships are deactivated.
5. Verified, idempotent WorkOS webhooks.
6. Fail-closed production configuration and a non-production test-identity adapter (mirroring Atlas’s `DEV_AUTH_BYPASS` fail-closed rules).

Related: [0003-backend-bootstrap-environment.md](0003-backend-bootstrap-environment.md), [0004-organization-url-session-context.md](0004-organization-url-session-context.md).

## Decision

### 1. WorkOS server-side authorization-code flow

Flow (HTTP/redirect level; exact WorkOS SDK method names are an implementation detail to confirm against current WorkOS docs in Phase 1):

1. Browser `GET /api/auth/login` → Accord redirects to WorkOS AuthKit / SSO authorization URL (includes client id, redirect URI, state/PKCE as required by WorkOS).
2. User authenticates at WorkOS.
3. WorkOS redirects to `GET /api/auth/callback?code=…&state=…`.
4. Accord backend **server-side** exchanges the `code` for WorkOS profile/identity (never returns WorkOS access/refresh/id tokens to the browser).
5. Accord upserts the local `users` row (keyed by WorkOS user id), loads active `organization_memberships`, selects or prompts for active organization, and **mints an Accord session**.
6. Response sets a secure HTTP-only cookie; frontend thereafter calls APIs with that cookie only.

**Invariant:** No WorkOS access token, refresh token, or ID token is ever readable by frontend JavaScript. The SPA only ever sees the opaque Accord session cookie.

### 2. Session cookie and storage

**Choice: opaque session id cookie → server-side session store** (Postgres table or equivalent).

Justification vs signed-only cookie payload:

- Privilege changes (role change, membership deactivation, org switch) can rotate or delete the server row immediately for subsequent requests.
- Cookie stays small and non-sensitive (random id only).
- Fits government payroll expectation of revocable sessions.

Cookie attributes:

| Attribute | Value | Notes |
| --- | --- | --- |
| Name | `accord_session` (`SESSION_COOKIE_NAME`, default `accord_session`) | Configurable |
| HttpOnly | `true` | Not accessible to JS |
| Secure | `true` outside local development | Required in staging/production |
| SameSite | `Lax` | **Lax vs Strict:** login is redirect-based. After WorkOS auth, the browser lands on `/api/auth/callback` as a top-level cross-site navigation. `SameSite=Strict` would omit the cookie on that first landing (and can break redirect-back session establishment). `Lax` allows the cookie to be set/sent on top-level GET navigations while still blocking CSRF on cross-site POSTs. |
| Path | `/` | Entire API/app |
| Max-Age / expiry | **12 hours** absolute session lifetime; idle timeout **2 hours** (server-side) | Tunable via settings |
| Value | Opaque cryptographically random session id (e.g. 32+ bytes, URL-safe) | References server-side session row |
| Integrity | Session id unguessable; optional signing of cookie value with `SESSION_SECRET_KEY` as defense-in-depth | Server store is source of truth |

Server-side session payload includes at minimum: `user_id`, `active_organization_id` (nullable until selected), `created_at`, `expires_at`, `last_seen_at`, `auth_provider` (`workos` | `dev_test`).

**Rotation:** On privilege-affecting events (org switch, role change detected, logout, password/SSO re-auth if applicable), issue a **new** session id, invalidate the old row, and `Set-Cookie` the new value. Do not reuse session ids across privilege boundaries.

### 3. WorkOS authenticates; Accord authorizes

- WorkOS proves **identity only** (who the human is).
- Accord Postgres is the **sole source of truth for authorization**:
  - `organization_memberships.is_active`
  - `organization_memberships.role` (and any future capabilities table)
- Even if WorkOS Directory Sync / Organizations says a user belongs to a WorkOS Organization, Accord **does not** grant access until a corresponding local membership row exists and is active. WorkOS org linkage may be used as a provisioning signal (via webhooks), never as a live authz check bypass.

### 4. Organization context selection

Active organization lives in the **server-side session** (not in a client-trusted header/body). Selection rules:

| Memberships at login | Behavior |
| --- | --- |
| Exactly one active membership | Auto-select that organization; proceed |
| Multiple active memberships | Session created with `active_organization_id = null` until explicit selection; APIs that require org context return 409/403 with a clear error until switched |
| Zero active memberships | Authenticated but unauthorized for tenant data; `/api/auth/me` reports empty memberships |

**Canonical switch endpoint:** `POST /api/auth/switch-organization` (body: `{ "organization_id": "<uuid>" }`).

- Re-validates target membership exists and `is_active = true` for the current user.
- Updates session `active_organization_id`, rotates session id.
- Alias (optional, same handler): `POST /api/organizations/{id}/switch` — if exposed, it must call the same service; prefer documenting **one** canonical path in clients (`/api/auth/switch-organization`). See [0004-organization-url-session-context.md](0004-organization-url-session-context.md).

**Membership deactivation staleness:**

- Deactivation by an admin is **not** required to abort an in-flight request mid-handler.
- Enforcement: every authenticated request loads the session, then **re-checks** that the membership for `active_organization_id` is still `is_active` (and role still permits the action).
- If inactive: clear active org / reject with 401/403 and force re-selection or logout.
- **Maximum staleness window:** end of the current request only for already-authorized handlers; **next authenticated request** must observe deactivation. Combined with idle timeout (2h) and absolute TTL (12h), worst-case session persistence without a subsequent request is the remaining TTL — but any API call within that window revalidates membership. Optional: webhook-driven session revocation for the affected user shortens this further (recommended when membership webhooks are wired).

### 5. WorkOS webhooks

- Endpoint: `POST /api/auth/webhooks/workos` (unauthenticated by session; authenticated by signature).
- Verify signature using WorkOS’s webhook signing-secret scheme (header + signing secret from `WORKOS_WEBHOOK_SECRET`). Reject missing/invalid signatures with 401/400 — fail closed.
- Process **idempotently**: dedupe by WorkOS event id (store processed event ids in a `workos_webhook_events` table, or reuse `idempotency_keys` from ADR 0001 with a platform/system organization or a dedicated non-tenant table). Redelivery must not double-apply membership creates/deactivates.
- Typical events (illustrative): user updated, organization membership changed — map to local `users` / `organization_memberships` upserts. Exact event type names confirmed against WorkOS docs at implementation time.

### 6. Fail-closed configuration and auth providers

Mirror Atlas’s pydantic-settings `model_validator` pattern (see [0003-backend-bootstrap-environment.md](0003-backend-bootstrap-environment.md)):

- In **production**, missing any of `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_REDIRECT_URI`, `WORKOS_WEBHOOK_SECRET`, `SESSION_SECRET_KEY` → raise `ValueError` at settings load; app **refuses to start**.
- `DEV_AUTH_BYPASS` (or equivalent) **cannot** be enabled in production.
- Auth is never “silently disabled” in production.

**Auth provider interface** (same internal contract for prod and local):

```python
from typing import Protocol

class AuthProvider(Protocol):
    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str: ...
    async def exchange_code(self, *, code: str) -> AuthenticatedIdentity: ...
    # AuthenticatedIdentity: stable subject id, email, display name — no tokens to browser
```

| Implementation | When |
| --- | --- |
| `WorkOSAuthProvider` | Default when WorkOS settings present |
| `DevTestAuthProvider` | Non-production only; gated by `DEV_AUTH_BYPASS=true` (or `AUTH_PROVIDER=dev_test`) which itself fails closed if set in production |

`DevTestAuthProvider` issues the same Accord session cookie after a local test-identity login path; it must not be importable/activatable when `ENVIRONMENT=production`.

### 7. Auth endpoint surface

| Method | Path | Purpose | Auth requirement |
| --- | --- | --- | --- |
| `GET` | `/api/auth/login` | Start WorkOS redirect (or dev-test login entry) | Anonymous |
| `GET` | `/api/auth/callback` | Handle WorkOS code; mint session cookie | Anonymous (one-time code) |
| `POST` | `/api/auth/logout` | Invalidate server session; clear cookie | Authenticated session (idempotent if already logged out) |
| `GET` | `/api/auth/me` | Current user, memberships, active organization, capabilities | Authenticated session |
| `POST` | `/api/auth/switch-organization` | Set active org after membership re-validation; rotate session | Authenticated session |
| `POST` | `/api/auth/webhooks/workos` | WorkOS event ingestion | WorkOS signature (no session cookie) |

### 8. Capability matrix

Roles (rows) × capabilities (columns). Cells: **yes** / **no** / **scoped** (scoped = within active organization only, and subject to audit).

| Role | Master data CRUD | Sensitive field reveal (SSN/bank unmask) | Payroll run create/calculate | Run submit | Run approve | Run post | Run reverse | Report generation/download | Org settings management | Membership management | Audit log read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Organization administrator | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| Payroll preparer | yes | no | yes | yes | no | no | no | yes | no | no | scoped |
| Payroll reviewer | scoped | no | no | no | no | no | no | yes | no | no | scoped |
| Payroll approver | no | no | no | no | yes | no | no | yes | no | no | scoped |
| Payment/report releaser | no | no | no | no | no | yes | scoped | yes | no | no | scoped |
| Auditor (read-only) | no | no | no | no | no | no | no | yes | no | no | yes |
| Platform support administrator | scoped | scoped | no | no | no | no | no | scoped | scoped | scoped | yes |

Notes:

- **Platform support administrator** is not a normal org role. Access is separately audited/logged (distinct audit actor type / break-glass trail) and may use the narrow cross-org route exceptions in ADR 0004.
- **Separation of duties (policy consideration, future ADR):** even when a role matrix cell would allow both, operational policy should generally prevent one person from holding both **submit and approve**, or both **approve and post**, on the same payroll run. This ADR defines capability primitives; the run-approval workflow ADR will enforce SoD rules (e.g. dual control, incompatible capability pairs per run).

## Consequences

- Frontend never holds WorkOS tokens; XSS cannot exfiltrate IdP credentials from JS.
- Authorization bugs in WorkOS org sync cannot silently grant Accord access without local membership rows.
- Server-side sessions enable rotation and revocation at the cost of a session store and lookup per request.
- `SameSite=Lax` is required for redirect login; CSRF protection for state-changing routes still relies on SameSite + standard API CSRF strategies as needed for cookie auth.
- Production misconfiguration fails at startup rather than shipping an open API.
- Capability matrix is the Phase 0 contract for RBAC implementation; SoD across submit/approve/post remains a workflow concern.

## Alternatives Considered

1. **Firebase Auth (Atlas parity)** — Rejected for Accord. Multi-org SaaS + SSO/enterprise readiness favors WorkOS AuthKit; Firebase assumptions must not be copied.
2. **Expose WorkOS tokens to the SPA** — Rejected. Increases XSS blast radius; Accord session cookie is sufficient for API auth.
3. **Signed/encrypted cookie with no server store** — Viable alternative for simpler ops, but weaker immediate revocation. Rejected for Phase 0 in favor of opaque id + server store; may revisit if session store ops become a bottleneck.
4. **WorkOS Organizations as live authz source** — Rejected. Accord’s `organization_memberships` remains authoritative for payroll access.
5. **`SameSite=Strict` cookies** — Rejected; breaks WorkOS redirect-back session establishment on first arrival.
6. **Silent auth disable when WorkOS env vars missing** — Rejected; fail-closed startup validation is mandatory in production (Atlas pattern).
