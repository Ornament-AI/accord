# ADR-0011: Single-Organization Product Contract

**Status:** Accepted  
**Date:** 2026-07-19  
**Supersedes (product claims):** multi-org switch / open create / membership-list UX in [0002](0002-workos-authentication-sessions.md) and [0004](0004-organization-url-session-context.md)  
**Related (kernel debt):** [0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)

## Context

Accord was scaffolded with a multi-tenant SaaS kernel: `organization_id` columns, forced RLS, and a session `active_organization_id`. But support for many organizations was never the product goal here. Before production, the public contract must serve one organization and nothing more. It must not pretend that switching orgs or creating many orgs is supported.

Removing `organization_id` and RLS right away would rewrite most of the schema. It would also collide with in-flight payroll work. So Phase 1 changes only the **product and API contract**. The tenancy kernel stays in place as documented migration debt until Phase 2.

## Decision

### 1. Singular public auth contract

`GET /api/auth/me` returns:

- `access_state`: `unbootstrapped` | `unprovisioned` | `active`
- `organization`: the singleton org summary, or `null` when unbootstrapped
- `membership`: role + capabilities when the user is an active member, else `null`

These are removed from the public contract: `organizations[]`, `active_organization`, `POST /api/auth/switch-organization`, self-serve `POST /api/organizations`, and the select/create-many UI.

The server computes `access_state` from `COUNT(organizations)` and the user’s active membership. Any existing organization row means the deployment is provisioned (not `unbootstrapped`). Turning an organization off is not a product path.

### 2. Privileged CLI bootstrap only

Only `scripts/provision_organization.py` can create the singleton organization. It runs with the migrator/ops database credential. There is no HTTP bootstrap endpoint and no bootstrap secret header.

Reruns are idempotent and never grant new access:

- The first create succeeds.
- A rerun with the same name/slug/admin-email is a no-op success.
- A rerun with a different name/slug/admin-email fails clearly. It never adds an administrator.

Later access changes go through `scripts/provision_member.py` only. There is no in-app members UI and no HTTP API for it.

### 3. Member provisioning

Invitations and memberships are managed through the CLI (`scripts/provision_member.py`). That path cannot demote or deactivate the last active `organization_administrator`. On login, a pending invitation is claimed in one atomic step. The email match ignores case.

### 4. Database singleton

A unique index allows at most one `organizations` row. Migrations preflight `COUNT(organizations)` and abort with reset instructions when `count > 1`. Tests must not insert a second organization. RLS proofs use fail-closed GUC checks against one org.

### 5. Phase 2 kernel removal (not this change)

Checklist for the later initiative:

1. Stop per-request `app.organization_id` binding / replace the RLS model.
2. Drop FORCE RLS policies as appropriate.
3. Drop `organization_id` columns, org-leading uniques, artifact key prefixes, and worker per-org claim loops.
4. Drop `sessions.active_organization_id`.
5. Run follow-up migrations and rewrite the remaining tenancy tests.

Until then, `organization_id`, the GUCs, forced RLS, and `active_organization_id` are **migration debt**. They are not a multi-org product surface.

## Consequences

- Deployments must run the provision CLI before any user can become `active`.
- Gate D / RLS suites prove fail-closed binding for a single deployment. They do not prove SaaS cross-tenant isolation via Org A/B rows.
- OpenAPI and the frontend auth types mirror the singular `/me` shape.
