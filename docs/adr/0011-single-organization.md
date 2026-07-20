# ADR-0011: Single-Organization Product Contract

**Status:** Accepted  
**Date:** 2026-07-19  
**Supersedes (product claims):** multi-org switch / open create / membership-list UX in [0002](0002-workos-authentication-sessions.md) and [0004](0004-organization-url-session-context.md)  
**Related (kernel debt):** [0001-tenancy-rls-database-roles.md](0001-tenancy-rls-database-roles.md)

## Context

Accord was scaffolded with a multi-tenant SaaS kernel (`organization_id`, forced RLS, session `active_organization_id`). Multi-organization was never the product goal for this deployment. Pre-production, the public contract must become genuinely single-organization without pretending switch/create-many are supported.

Removing `organization_id` / RLS immediately would rewrite most of the schema and collide with in-flight payroll work. Therefore Phase 1 changes the **product and API contract**; the tenancy kernel remains documented migration debt until Phase 2.

## Decision

### 1. Singular public auth contract

`GET /api/auth/me` returns:

- `access_state`: `unbootstrapped` | `unprovisioned` | `active`
- `organization`: the singleton org summary, or `null` when unbootstrapped
- `membership`: role + capabilities when the user is an active member, else `null`

Removed from the public contract: `organizations[]`, `active_organization`, `POST /api/auth/switch-organization`, self-serve `POST /api/organizations`, select/create-many UI.

`access_state` is server-computed from `COUNT(organizations)` and the user’s active membership. Any existing organization row means the deployment is provisioned (not `unbootstrapped`). Organization deactivation is not a product path.

### 2. Privileged CLI bootstrap only

The singleton organization is created only by `scripts/provision_organization.py` using the migrator/ops database credential. There is no HTTP bootstrap endpoint and no bootstrap secret header.

Idempotency is non-escalating:

- First create succeeds.
- Rerun with identical name/slug/admin-email is a no-op success.
- Rerun with different name/slug/admin-email fails clearly and never adds administrators.

Later access changes use `scripts/provision_member.py` only (no in-app members UI or HTTP API).

### 3. Member provisioning

Invitations + memberships are managed via CLI (`scripts/provision_member.py`). The last active `organization_administrator` cannot be demoted or deactivated through that path. Pending invitations are claimed atomically on login (case-insensitive email match).

### 4. Database singleton

A unique index enforces at most one `organizations` row. Migrations preflight `COUNT(organizations)` and abort with reset instructions when `count > 1`. Tests must not insert a second organization; RLS proofs use fail-closed GUC checks against one org.

### 5. Phase 2 kernel removal (not this change)

Later initiative checklist:

1. Stop per-request `app.organization_id` binding / replace RLS model.
2. Drop FORCE RLS policies as appropriate.
3. Drop `organization_id` columns, org-leading uniques, artifact key prefixes, worker per-org claim loops.
4. Drop `sessions.active_organization_id`.
5. Follow-up migrations and rewrite remaining tenancy tests.

Until then, `organization_id`, GUCs, forced RLS, and `active_organization_id` are **migration debt**, not a multi-org product surface.

## Consequences

- Deployments must run the provision CLI before users can become `active`.
- Gate D / RLS suites prove fail-closed binding for a single deployment, not SaaS cross-tenant isolation via Org A/B rows.
- OpenAPI and frontend auth types mirror the singular `/me` shape.
