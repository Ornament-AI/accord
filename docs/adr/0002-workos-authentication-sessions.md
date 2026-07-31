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
5. Accord upserts the local `users` row (keyed by WorkOS user id), loads the
   singleton organization and active membership (or records an unprovisioned
   access state), and **mints an Accord session**.
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
| Secure | `true` when `ENVIRONMENT=production` | Current implementation contract; staging must set `ENVIRONMENT=production` to receive production cookie/config enforcement |
| SameSite | `Lax` | **Lax vs Strict:** login is redirect-based. After WorkOS auth, the browser lands on `/api/auth/callback` as a top-level cross-site navigation. `SameSite=Strict` would omit the cookie on that first landing (and can break redirect-back session establishment). `Lax` allows the cookie to be set/sent on top-level GET navigations while still blocking CSRF on cross-site POSTs. |
| Path | `/` | Entire API/app |
| Max-Age / expiry | **12 hours** absolute session lifetime; idle timeout **2 hours** (server-side) | Absolute TTL is `SESSION_MAX_AGE_SECONDS`; idle timeout is configurable with `SESSION_IDLE_TIMEOUT_SECONDS` |
| Value | Signed opaque session-row UUID | References the server-side session row without exposing identity data |
| Integrity | `SESSION_SECRET_KEY` signs the opaque UUID | Server store remains the source of truth |

The server-side `sessions` row includes `user_id`,
`active_organization_id`, `issued_at`, `expires_at`, `last_seen_at`,
`revoked_at`, and an optional user-agent hash. The cookie does not carry those
fields.

Each successful login creates a new session row and signed cookie. Logout
revokes that row and clears the cookie. Membership and role changes are
re-checked on every authenticated request, so they take effect without
trusting stale capabilities stored in the session.

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
- Process events **idempotently**: `webhook_events` claims the WorkOS event id
  and stores its payload digest in the same transaction as handling. A
  redelivery is acknowledged without applying the event twice.
- The current handler applies `user.updated` to an existing local `users` row.
  Other validly signed events are acknowledged and durably deduplicated but do
  not change memberships. Any membership-sync behavior requires an explicit
  implementation change and tests.

### 6. Fail-closed configuration and auth providers

Mirror Atlas’s pydantic-settings `model_validator` pattern (see [0003-backend-bootstrap-environment.md](0003-backend-bootstrap-environment.md)):

- In **production**, empty `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`,
  `WORKOS_REDIRECT_URI`, `WORKOS_WEBHOOK_SECRET`, or `SESSION_SECRET_KEY`
  values raise `ValueError`. `WORKOS_REDIRECT_URI` has a nonempty localhost
  default, so operators must override it with the registered production
  callback; omitting the variable does not currently fail startup.
- `DEV_AUTH_BYPASS` (or any stand-in for it) **cannot** be enabled in production.
- Auth is never “silently disabled” in production.

**Auth provider interface** (same internal contract for prod and local):

```python
from typing import Protocol

class AuthAdapter(Protocol):
    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str: ...
    async def exchange_code(self, *, code: str) -> AuthenticatedIdentity: ...
    # AuthenticatedIdentity: stable subject id, email, display name — no tokens to browser
```

| Implementation | When |
| --- | --- |
| `WorkOSAuthAdapter` | Selected when WorkOS settings are present; mandatory in production |
| `DevAuthAdapter` | Non-production only; selected only when `DEV_AUTH_BYPASS=true`, which fails closed in production |

`DevAuthAdapter` issues the same Accord session cookie after a local
test-identity login path. No `AUTH_PROVIDER` setting exists. Production
selection is guarded both by settings validation and `get_auth_adapter()`.

### 7. Auth endpoint surface

| Method | Path | Purpose | Auth requirement |
| --- | --- | --- | --- |
| `GET` | `/api/auth/login` | Start WorkOS redirect (or dev-test login entry) | Anonymous |
| `POST` | `/api/auth/login/password` | Server-side WorkOS password authentication | Anonymous; rate limited |
| `POST` | `/api/auth/magic-code` | Request a WorkOS email sign-in code | Anonymous; rate limited |
| `POST` | `/api/auth/login/magic-code` | Exchange an email sign-in code for an Accord session | Anonymous; rate limited |
| `GET` | `/api/auth/callback` | Handle WorkOS code; mint session cookie | Anonymous (one-time code) |
| `POST` | `/api/auth/logout` | Invalidate server session; clear cookie | Authenticated session (idempotent if already logged out) |
| `GET` | `/api/auth/me` | Current user, `access_state`, singular organization, membership, capabilities | Authenticated session |
| `POST` | `/api/auth/webhooks/workos` | WorkOS event ingestion | WorkOS signature (no session cookie) |

### 8. Capability matrix

`backend/app/auth/capabilities.py` is the executable source of truth. Every
capability is organization-scoped through the authenticated membership.

| Role | Granted capabilities |
| --- | --- |
| Organization administrator | All current capabilities: `manage_organization`, `manage_master_data`, `view_master_data`, `reveal_sensitive_fields`, `create_run`, `submit_run`, `approve_run`, `post_run`, `generate_reports`, `release_reports`, `view_audit` |
| Payroll preparer | `manage_master_data`, `view_master_data`, `create_run`, `submit_run`, `generate_reports`, `view_audit` |
| Payroll reviewer | `view_master_data`, `generate_reports`, `view_audit` |
| Payroll approver | `approve_run`, `generate_reports`, `view_audit` |
| Payment/report releaser | `post_run`, `generate_reports`, `release_reports`, `view_audit` |
| Auditor (read-only) | `generate_reports`, `view_audit` |

Notes:

- Platform support is not an organization-membership role and receives no
  capability bypass in the current implementation.
- There is no standalone run-reversal capability or membership-management API.
- Maker/checker separation is implemented in the run workflow: a submitter
  cannot approve or reject the same submission. Posting follows ADR 0008 and
  may be performed by the approver when that user also has `post_run`.

## Consequences

- The frontend never holds WorkOS tokens, so XSS cannot steal IdP credentials from JS.
- Bugs in WorkOS org sync cannot silently grant Accord access without local membership rows.
- Server-side sessions let us rotate and revoke at will. The cost is a session store and one lookup per request.
- `SameSite=Lax` is required for redirect login. CSRF protection for state-changing routes still relies on SameSite plus standard API CSRF strategies as needed for cookie auth.
- A bad production config fails at startup, instead of shipping an open API.
- The capability matrix is enforced by request dependencies; maker/checker
  separation is additionally enforced by the run-workflow service.

## Alternatives Considered

1. **Firebase Auth (Atlas parity)** — Rejected for Accord. Multi-org SaaS plus SSO/enterprise needs favor WorkOS AuthKit. Firebase assumptions must not be copied.
2. **Expose WorkOS tokens to the SPA** — Rejected. It widens the XSS blast radius. The Accord session cookie is enough for API auth.
3. **Signed/encrypted cookie with no server store** — A viable option with simpler ops, but weaker instant revocation. Rejected for Phase 0 in favor of an opaque id plus server store. May revisit if session store ops become a bottleneck.
4. **WorkOS Organizations as live authz source** — Rejected. Accord’s `organization_memberships` stays the source of truth for payroll access.
5. **`SameSite=Strict` cookies** — Rejected. Strict breaks the session on the first redirect back from WorkOS.
6. **Silent auth disable when WorkOS env vars missing** — Rejected. Fail-closed startup checks are mandatory in production (Atlas pattern).
