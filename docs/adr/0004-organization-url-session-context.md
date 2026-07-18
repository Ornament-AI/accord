# ADR-0004: Organization URL and Session Context

**Status:** Proposed

## Context

Accord is multi-tenant. Every authenticated request that touches tenant data needs a clear answer to: *which organization is in scope?*

Two common API styles:

1. **Organization-implicit routes** — active org resolved from server-side session, e.g. `GET /api/employees`.
2. **Organization-in-path routes** — org appears in every URL, e.g. `GET /api/organizations/{org_id}/employees`.

This choice interacts with forced RLS and transaction GUCs ([0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)) and with WorkOS sessions that store `active_organization_id` ([0002-workos-authentication-sessions.md](0002-workos-authentication-sessions.md)). A wrong choice multiplies IDOR risk across every handler.

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

Resolution order (centralized in shared auth dependency / middleware — not per-handler ad hoc logic):

1. Authenticate session cookie → load server-side session.
2. Require `active_organization_id` for org-scoped routes; if null, return Problem Detail (e.g. 409 `OrganizationContextRequired`) directing the client to switch.
3. Re-validate membership `is_active` for that org (ADR 0002 staleness rules).
4. Open DB transaction and `SET LOCAL app.organization_id` / `app.user_id` / `app.request_id` (ADR 0001) **before** any tenant query.
5. Handlers receive a trusted `TenantContext` and never read organization scope from the JSON body.

### 2. Canonical org-switch endpoint

**Canonical:** `POST /api/auth/switch-organization` (defined in ADR 0002).

```http
POST /api/auth/switch-organization
Content-Type: application/json

{"organization_id": "11111111-1111-1111-1111-111111111111"}
```

Behavior:

- Re-validate active membership for the current user.
- Update session `active_organization_id`, rotate session id, set cookie.
- Response includes the new effective `organization_id`.

**Optional alias:** `POST /api/organizations/{id}/switch` may call the same service for ergonomic REST shape. Clients and docs should treat **`/api/auth/switch-organization` as canonical** to avoid two competing contracts. If the alias is implemented, it must not diverge in authz or side effects.

### 3. Echo effective organization on every org-scoped response

Every authenticated API response that is organization-scoped must echo the **effective** organization id so the frontend can confirm scope without trusting client-only state:

| Mechanism | Requirement |
| --- | --- |
| Header | `X-Organization-Id: <uuid>` on org-scoped responses |
| Body (optional envelope) | Include `organization_id` in a stable response envelope field when lists/resources are returned |

Example:

```http
HTTP/1.1 200 OK
X-Request-ID: a1b2c3d4e5f6789012345678abcdef01
X-Organization-Id: 11111111-1111-1111-1111-111111111111
Content-Type: application/json

{
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "data": [ /* employees */ ]
}
```

The client may display or assert this value; it must **not** send it back as a trusted scoping input on subsequent writes (ADR 0001).

### 4. Why not org-id-in-every-path (IDOR)

Putting `{org_id}` in every route appears explicit but creates systemic IDOR risk:

- A client can tamper with the path (`/api/organizations/OTHER_ORG/employees`).
- **Every** handler must re-validate that the caller’s membership and RLS context match the path `org_id`.
- Forgetting the check on **one** of many endpoints is a full tenant-isolation bug — the failure mode is opt-in correctness per handler.
- Duplicated validation drifts over time (path org vs session org vs body org).

**Session-based approach (chosen):** organization resolution happens **once**, centrally, in shared middleware/dependency. Individual handlers cannot “forget” to bind tenant context if they go through the standard dependency that sets `SET LOCAL` and injects `TenantContext`. RLS still fail-closes if context is missing (ADR 0001).

```python
# Central dependency sketch — handlers depend on this, not on path org_id
async def require_tenant_context(request: Request) -> TenantContext:
    session = await load_session(request)
    if session.active_organization_id is None:
        raise AccordError(
            "Active organization required.",
            status_code=409,
            error="OrganizationContextRequired",
        )
    await assert_membership_active(session.user_id, session.active_organization_id)
    # bind SET LOCAL on the request's DB connection/transaction here or in get_session()
    return TenantContext(
        user_id=session.user_id,
        organization_id=session.active_organization_id,
    )
```

### 5. Narrow exceptions where org appears in the URL

Org id (or slug) may appear in the URL only in these cases:

| Route class | Example | Why allowed |
| --- | --- | --- |
| Switch command | `POST /api/auth/switch-organization` (body) or alias `POST /api/organizations/{id}/switch` | The target org **is** the command argument; membership is re-validated before session update |
| Platform support admin | e.g. `GET /api/support/organizations/{org_id}/…` | Caller is **platform support administrator** (ADR 0002) — not a normal tenant user; separately audited; explicitly allowed to name a target org |

Rules for support routes:

- Distinct router prefix (e.g. `/api/support/…`).
- Capability check for platform support role; normal org roles receive 403.
- Still bind RLS/`SET LOCAL` to the **target** org for data access, and write an audit event with support actor + target `organization_id`.
- Do not reuse normal tenant route handlers without the support authz gate.

Normal tenant users never pass `organization_id` in path or body to select read/write scope for ordinary resources.

### 6. Frontend cache clearing on identity / org change

Whenever identity changes (login/logout) or active organization changes (switch), the frontend **must fully clear** all client-side data caches so one organization’s data cannot flash or merge into another’s UI.

**Required reset actions:**

1. Clear React Query / SWR (or equivalent) cache entirely — e.g. `queryClient.clear()` (not selective `invalidateQueries` alone).
2. Reset in-memory stores (Zustand/Redux/context) that hold org-scoped entities.
3. Clear any org-scoped `localStorage` / `sessionStorage` keys.
4. Prefer a **hard navigation** or **full remount** of the app shell after switch/login/logout so no mounted component retains stale props/state.

```ts
// On successful org switch (and on login/logout)
async function onOrganizationSwitched(nextOrganizationId: string): Promise<void> {
  queryClient.clear();
  resetOrgScopedStores();
  clearOrgScopedWebStorage();
  // Full remount / navigation — do not patch-merge old org pages
  window.location.assign("/"); // or router hard-nav to org home
}
```

**Never** merge or patch stale cross-org collections into the UI after a switch. Treat org switch like a soft “relogin” for client state.

## Consequences

- Handlers stay thin: they do not re-implement tenant binding; IDOR surface for org selection shrinks to the switch + support routes.
- Frontend must always honor `X-Organization-Id` / echoed `organization_id` and reset caches on switch — product UX includes a brief full reload/remount.
- Deep-linking to “org B while session is org A” is intentionally unsupported for normal users; they must switch first.
- Platform support tooling gets explicit cross-org URLs with stronger audit requirements.
- Consistent with ADR 0001 (no body-supplied org scope) and ADR 0002 (session-stored active org).

## Alternatives Considered

1. **Org id in every path (`/api/organizations/{org_id}/…`)** — Rejected as the default. Explicit but IDOR-prone; every handler must remember path↔membership checks. Session + central dependency is safer for a large payroll API surface.
2. **Org id only in `X-Organization-Id` request header** — Rejected as primary selector. Headers are still client-controlled; easier to forget to validate than a server session field set only by switch. Response echo header is fine; request header must not authorize scope.
3. **Org id in request body for all writes** — Rejected (ADR 0001). Hostile input; ignored or 422.
4. **Allow soft cache invalidation only** — Rejected. Selective invalidation risks leaving org-scoped detail queries in memory; full `queryClient.clear()` + remount is mandatory.
5. **Subdomain-per-org (`org-slug.accord.example`)** — Deferred. Possible future UX; would still resolve to server-side session/org binding and must not bypass membership checks.
