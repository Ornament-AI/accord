# ADR-0004: Organization URL and Session Context

**Status:** Accepted (org-implicit APIs + session GUC bind); multi-org switch / open create superseded by [0011-single-organization.md](0011-single-organization.md)

## Context

Every authenticated request that touches tenant data needs a clear answer to one question: *which organization is in scope?* For the single-organization product ([0011](0011-single-organization.md)), the answer is always the deployment singleton, when the user is a member. The session still stores `active_organization_id` as **kernel debt** for RLS binding.

Two common API styles:

1. **Organization-implicit routes** — the active org comes from the server-side session, e.g. `GET /api/employees`.
2. **Organization-in-path routes** — the org appears in every URL, e.g. `GET /api/organizations/{org_id}/employees`.

This choice interacts with forced RLS and transaction GUCs ([0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)), and with sessions that store `active_organization_id` ([0002-workos-authentication-sessions.md](0002-workos-authentication-sessions.md)).

## Decision

### 1. Default: active organization in server-side session

**Recommend organization-implicit routes as the default** for nearly all tenant resource APIs:

```http
GET    /api/employees
POST   /api/employees
GET    /api/employees/{employee_id}
POST   /api/payroll-runs
GET    /api/payroll-runs/{run_id}
```

Resolution order (central, in a shared auth dependency or middleware — never ad hoc per handler):

1. Authenticate the session cookie and load the server-side session.
2. Require `active_organization_id` for org-scoped routes. If it is null, return a Problem Detail (e.g. 409 `OrganizationContextRequired`). Under ADR 0011 the client shows unbootstrapped or unprovisioned, not an org switcher.
3. Re-check that membership `is_active` for that org (ADR 0002 staleness rules).
4. Open a DB transaction and `SET LOCAL app.organization_id` / `app.user_id` / `app.request_id` (ADR 0001) **before** any tenant query.
5. Handlers receive a trusted `TenantContext`. They never read org scope from the JSON body.

### 2. Org-switch endpoint (superseded)

~~**Canonical:** `POST /api/auth/switch-organization`.~~ **Removed** by [ADR 0011](0011-single-organization.md). The session field `active_organization_id` is auto-bound to the singleton when the user has an active membership.

Historical behavior (for archaeology only):

- Re-check the active membership for the current user.
- Update session `active_organization_id`, rotate the session id, set the cookie.
- The response includes the new effective `organization_id`.

### 3. Response correlation under the singleton contract

The original design required `X-Organization-Id` on org-scoped responses. It
was not implemented and is no longer required by the singleton product
contract. Responses emit `X-Request-ID` for correlation; the server derives
organization scope from the authenticated session and binds it for RLS.
Clients must not depend on an organization response header or send an
organization identifier as trusted scoping input.

### 4. Why not org-id-in-every-path (IDOR)

Putting `{org_id}` in every route looks explicit, but it creates systemic IDOR risk:

- A client can tamper with the path (`/api/organizations/OTHER_ORG/employees`).
- **Every** handler must then re-check that the caller’s membership and RLS context match the path `org_id`.
- Forgetting that check on **one** of many endpoints is a full tenant-isolation bug. The failure mode is opt-in correctness, one handler at a time.
- Duplicated checks drift over time (path org vs session org vs body org).

**Session-based approach (chosen):** the org is resolved **once**, in shared middleware or a shared dependency. Handlers cannot “forget” to bind tenant context if they go through the standard dependency that runs `SET LOCAL` and injects `TenantContext`. RLS still fails closed if context is missing (ADR 0001).

```python
# Central dependency sketch — handlers depend on this, not on path org_id
async def require_tenant_context(request: Request) -> TenantContext:
    session = await load_session(request)
    if session.active_organization_id is None:
        raise OrganizationContextRequiredError("Active organization required.")
    await assert_membership_active(session.user_id, session.active_organization_id)
    # bind SET LOCAL on the request's DB connection/transaction here or in get_session()
    return TenantContext(
        user_id=session.user_id,
        organization_id=session.active_organization_id,
    )
```

### 5. Narrow exceptions where org appears in the URL

No support-administration router exists today. If a future support surface
introduces an org id (or slug) in the URL, it is limited to this route class:

| Route class | Example | Why allowed |
| --- | --- | --- |
| Platform support admin | e.g. `GET /api/support/organizations/{org_id}/…` | Caller is **platform support administrator** (ADR 0002) — not a normal tenant user; separately audited; explicitly allowed to name a target org (support routes may remain out of scope for v1) |

Rules for support routes:

- Distinct router prefix (e.g. `/api/support/…`).
- Capability check for the platform support role; normal org roles receive 403.
- Still bind RLS / `SET LOCAL` to the **target** org for data access, and write an audit event with the support actor and the target `organization_id`.
- Do not reuse normal tenant route handlers without the support authz gate.

Normal tenant users never pass `organization_id` in a path or body to select read or write scope for ordinary resources.

### 6. Frontend cache clearing on identity change

Whenever identity changes, the frontend must clear client-side data caches.
There is no organization switch in the singleton UI. The current login uses a
hard navigation; logout calls `queryClient.clear()`, remounts the app shell,
and navigates to `/login`.

**Required reset actions:**

1. Clear the React Query / SWR (or similar) cache in full — e.g. `queryClient.clear()` (not selective `invalidateQueries` alone).
2. Reset in-memory stores (Zustand/Redux/context) that hold org-scoped entities.
3. Clear any org-scoped `localStorage` / `sessionStorage` keys.
4. Prefer a **hard navigation** or a **full remount** of the app shell after
   login/logout, so no mounted component keeps stale props or state.

## Consequences

- Handlers stay thin. They do not re-implement tenant binding. The ordinary
  product API has no client-selected organization surface.
- The frontend resets caches on identity changes and does not expose an
  organization switcher.
- Cross-organization deep links are outside the singleton product contract.
- Any future platform-support tooling needs a distinct audited authorization
  surface; none is implemented today.
- Consistent with ADR 0001 (no body-supplied org scope) and ADR 0002 (session-stored active org).

## Alternatives Considered

1. **Org id in every path (`/api/organizations/{org_id}/…`)** — Rejected as the default. It looks explicit, but it is IDOR-prone. Every handler must remember path↔membership checks. Session plus a central dependency is safer for a large payroll API surface.
2. **Org id only in an `X-Organization-Id` request header** — Rejected as the primary selector. Headers are client-controlled and must not authorize scope. The originally proposed response echo was never implemented and is unnecessary for the singleton contract.
3. **Org id in the request body for all writes** — Rejected (ADR 0001). Hostile input; ignored or 422.
4. **Allow soft cache invalidation only** — Rejected. Selective invalidation risks leaving org-scoped detail queries in memory. A full `queryClient.clear()` plus remount is mandatory.
5. **Subdomain-per-org (`org-slug.accord.example`)** — Deferred. It is a possible future UX. It would still resolve to server-side session/org binding, and it must not bypass membership checks.

## Addendum (superseded by ADR 0011)

Self-service `POST /api/organizations` is **removed**. Bootstrap is CLI-only
(`scripts/provision_organization.py`) with a DB singleton unique index. See
[0011-single-organization.md](0011-single-organization.md). Gate D now proves
fail-closed GUC isolation against one organization, not dual-org spawn.
