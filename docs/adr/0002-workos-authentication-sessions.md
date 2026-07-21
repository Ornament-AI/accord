# ADR-0002: WorkOS Authentication and Sessions

**Status:** Accepted (identity/session); multi-org switch/selection product claims superseded by [0011-single-organization.md](0011-single-organization.md)

## Context

Accord needs auth for a payroll deployment that serves one org. Accord uses **WorkOS** (AuthKit / SSO) for identity. Access rights come from local `organization_memberships` rows and capabilities (see [0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md) kernel debt and [0011](0011-single-organization.md) product contract).

Requirements:

1. Browser login via WorkOS, without exposing WorkOS tokens to frontend JavaScript.
2. Accord-minted secure session cookies as the only credential the SPA sees.
3. Access rights sourced only from local `organization_memberships` and capabilities — never from WorkOS Organization membership alone.
4. Auto-bind the singleton org when the user has an active membership. There is no multi-org switch or selection UX ([0011](0011-single-organization.md)).
5. Verified, idempotent WorkOS webhooks (identity updates only, unless later extended).
6. Fail-closed production config, plus a non-production test-identity adapter (mirroring Atlas’s `DEV_AUTH_BYPASS` fail-closed rules).

Related: [0003-backend-bootstrap-environment.md](0003-backend-bootstrap-environment.md), [0004-organization-url-session-context.md](0004-organization-url-session-context.md), [0011-single-organization.md](0011-single-organization.md).

## Decision

### 1. WorkOS server-side authorization-code flow

The flow below is at the HTTP/redirect level. Exact WorkOS SDK method names are a build-time detail. Confirm them against current WorkOS docs in Phase 1:

1. Browser sends `GET /api/auth/login`. Accord redirects to the WorkOS AuthKit / SSO auth URL, with client id, redirect URI, and state/PKCE as WorkOS requires.
2. The user signs in at WorkOS.
3. WorkOS redirects to `GET /api/auth/callback?code=…&state=…`.
4. The Accord backend exchanges the `code` for the WorkOS profile and identity **server-side**. It never returns WorkOS access, refresh, or id tokens to the browser.
5. Accord upserts the local `users` row (keyed by WorkOS user id), loads active `organization_memberships`, selects or prompts for the active org, and **mints an Accord session**.
6. The response sets a secure HTTP-only cookie. From then on, the frontend calls APIs with that cookie only.

**Invariant:** No WorkOS access token, refresh token, or ID token is ever readable by frontend JavaScript. The SPA only ever sees the opaque Accord session cookie.

### 2. Session cookie and storage

**Choice: opaque session id cookie → server-side session store** (Postgres table or similar).

Why this beats a signed-only cookie payload:

- When privilege changes (role change, membership turned off, org switch), the server row can rotate or vanish at once, for all later requests.
- The cookie stays small and non-sensitive. It holds a random id only.
- It fits the government payroll expectation that sessions can be revoked.

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

The server-side session payload includes at least: `user_id`, `active_organization_id` (nullable until selected), `created_at`, `expires_at`, `last_seen_at`, and `auth_provider` (`workos` | `dev_test`).

**Rotation:** On events that affect privilege (org switch, detected role change, logout, or password/SSO re-auth where it applies), issue a **new** session id, invalidate the old row, and `Set-Cookie` the new value. Never reuse a session id across a privilege boundary.

### 3. WorkOS authenticates; Accord authorizes

- WorkOS proves **identity only** (who the human is).
- Accord Postgres is the **sole source of truth for access rights**:
  - `organization_memberships.is_active`
  - `organization_memberships.role` (and any future capabilities table)
- WorkOS Directory Sync or Organizations may say a user belongs to a WorkOS Organization. Even then, Accord **does not** grant access until a matching local membership row exists and is active. The WorkOS org link may serve as a signal to provision users (via webhooks). It never bypasses live access checks.

### 4. Organization context (single-organization product)

The active org lives in the **server-side session**, not in a client-trusted header or body. Under [ADR 0011](0011-single-organization.md), the deployment has at most one org. There is no switch or select UX.

| Login situation | Behavior |
| --- | --- |
| No organization row | `/api/auth/me` → `access_state=unbootstrapped` (ops must run `scripts/provision_organization.py`) |
| Org exists; user has no membership and no pending invite | `/api/auth/me` → `access_state=unprovisioned` |
| Org exists; pending invite for user email | Claim invite atomically on login; bind session; `access_state=active` |
| Org exists; active membership | Auto-bind session `active_organization_id` to the singleton; `access_state=active` |

~~`POST /api/auth/switch-organization`~~ is **removed**. The session field `active_organization_id` remains as kernel debt for RLS GUC binding until Phase 2.

**Membership deactivation staleness:**

- When an admin deactivates a membership, that action is **not** required to abort a request already running mid-handler.
- Enforcement: every request with a session loads it, then **re-checks** that the membership for `active_organization_id` is still `is_active` (and that the role still permits the action).
- If inactive: clear the active org, or reject with 401/403.
- **Maximum staleness window:** the end of the current request, and only for handlers already cleared to act. The **next request with a session** must observe the change. Idle timeout (2h) and absolute TTL (12h) bound the rest. With no further request, the worst case is that the session persists for its remaining TTL — but any API call inside that window checks membership again.

### 5. WorkOS webhooks

- Endpoint: `POST /api/auth/webhooks/workos` (no session auth; the signature is the credential).
- Check the signature with WorkOS’s webhook signing-secret scheme (header plus the signing secret from `WORKOS_WEBHOOK_SECRET`). Reject missing or bad signatures with 401/400 — fail closed.
- Process events **idempotently**: dedupe by WorkOS event id. Store processed event ids in a `workos_webhook_events` table, or reuse `idempotency_keys` from ADR 0001 with a platform/system org or a dedicated non-tenant table. A redelivered event must not apply a membership create or deactivate twice.
- Typical events (examples only): user updated, org membership changed. These map to local `users` / `organization_memberships` upserts. Confirm exact event type names against WorkOS docs at build time.

### 6. Fail-closed configuration and auth providers

Mirror Atlas’s pydantic-settings `model_validator` pattern (see [0003-backend-bootstrap-environment.md](0003-backend-bootstrap-environment.md)):

- In **production**, if any of `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_REDIRECT_URI`, `WORKOS_WEBHOOK_SECRET`, or `SESSION_SECRET_KEY` is missing, settings load raises `ValueError` and the app **refuses to start**.
- `DEV_AUTH_BYPASS` (or any stand-in for it) **cannot** be enabled in production.
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

`DevTestAuthProvider` issues the same Accord session cookie after a local test-identity login path. No code path may import it or turn it on when `ENVIRONMENT=production`.

### 7. Auth endpoint surface

| Method | Path | Purpose | Auth requirement |
| --- | --- | --- | --- |
| `GET` | `/api/auth/login` | Start WorkOS redirect (or dev-test login entry) | Anonymous |
| `GET` | `/api/auth/callback` | Handle WorkOS code; mint session cookie | Anonymous (one-time code) |
| `POST` | `/api/auth/logout` | Invalidate server session; clear cookie | Authenticated session (idempotent if already logged out) |
| `GET` | `/api/auth/me` | Current user, `access_state`, singular organization, membership, capabilities | Authenticated session |
| `POST` | `/api/auth/webhooks/workos` | WorkOS event ingestion | WorkOS signature (no session cookie) |

### 8. Capability matrix

Roles (rows) × capabilities (columns). Cells: **yes** / **no** / **scoped** (scoped = within the active org only, and subject to audit).

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

- **Platform support administrator** is not a normal org role. Its access is audited and logged apart from the rest (distinct audit actor type / break-glass trail). It may use the narrow cross-org route exceptions in ADR 0004.
- **Separation of duties (policy point, future ADR):** even when the matrix would allow both, policy should in general stop one person from holding both **submit and approve**, or both **approve and post**, on the same payroll run. This ADR defines capability primitives only. The run-approval workflow ADR will enforce the SoD rules (for example dual control, or incompatible capability pairs per run).

## Consequences

- The frontend never holds WorkOS tokens, so XSS cannot steal IdP credentials from JS.
- Bugs in WorkOS org sync cannot silently grant Accord access without local membership rows.
- Server-side sessions let us rotate and revoke at will. The cost is a session store and one lookup per request.
- `SameSite=Lax` is required for redirect login. CSRF protection for state-changing routes still relies on SameSite plus standard API CSRF strategies as needed for cookie auth.
- A bad production config fails at startup, instead of shipping an open API.
- The capability matrix is the Phase 0 contract for the RBAC build. SoD across submit/approve/post remains a workflow concern.

## Alternatives Considered

1. **Firebase Auth (Atlas parity)** — Rejected for Accord. Multi-org SaaS plus SSO/enterprise needs favor WorkOS AuthKit. Firebase assumptions must not be copied.
2. **Expose WorkOS tokens to the SPA** — Rejected. It widens the XSS blast radius. The Accord session cookie is enough for API auth.
3. **Signed/encrypted cookie with no server store** — A viable option with simpler ops, but weaker instant revocation. Rejected for Phase 0 in favor of an opaque id plus server store. May revisit if session store ops become a bottleneck.
4. **WorkOS Organizations as live authz source** — Rejected. Accord’s `organization_memberships` stays the source of truth for payroll access.
5. **`SameSite=Strict` cookies** — Rejected. Strict breaks the session on the first redirect back from WorkOS.
6. **Silent auth disable when WorkOS env vars missing** — Rejected. Fail-closed startup checks are mandatory in production (Atlas pattern).
