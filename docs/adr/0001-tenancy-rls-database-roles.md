# ADR-0001: Tenancy, RLS, and Database Roles

**Status:** Accepted (kernel); product multi-org superseded by [0011-single-organization.md](0011-single-organization.md)

## Context

Accord’s storage layer was built as a multi-tenant kernel. Each tenant table carries `organization_id`. RLS is forced, and tenant context lives in transaction-local GUCs. The **product** runs one organization per deployment ([ADR 0011](0011-single-organization.md)). The kernel below stays in place as **migration debt** until Phase 2 removes it. A tenancy bug in the kernel must still fail closed. An unset or wrong `app.organization_id` must never expose rows.

PostgreSQL Row Level Security (RLS) is a **forced, mandatory** tenancy control for Accord. It is not optional defense in depth. App filters alone are not enough. One query that misses `WHERE organization_id = …` would leak rows. RLS must block cross-tenant access even when app code forgets to filter.

We also need:

1. A clear multi-org data model, with `organization_id` on every tenant-owned table.
2. Composite foreign keys and unique constraints that include `organization_id`, so joins cannot silently cross tenants.
3. Tenant context that is local to the transaction and safe with pooled async connections (asyncpg / SQLAlchemy).
4. Separate database roles: migration owner, runtime API, and background workers.
5. An invariant that clients never supply org scope to authorize reads or writes.
6. A test strategy that proves isolation under the runtime role.

Related: [0002-workos-authentication-sessions.md](0002-workos-authentication-sessions.md), [0004-organization-url-session-context.md](0004-organization-url-session-context.md).

## Decision

### 1. Explicit multi-organization data model

- Every tenant-owned table carries `organization_id uuid NOT NULL` referencing `organizations(id)`.
- Child tables use **composite foreign keys** that pair `organization_id` with the parent key. A child row therefore cannot point at a parent in another org.
- Natural-key uniqueness is always scoped: `UNIQUE (organization_id, …)`.
- `users` is **tenant-independent**. A person may belong to more than one org via `organization_memberships`. User identity is not a row owned by one org.

Representative DDL:

```sql
CREATE TABLE organizations (
  id          uuid PRIMARY KEY,
  name        text NOT NULL,
  slug        text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id              uuid PRIMARY KEY,
  workos_user_id  text NOT NULL UNIQUE,
  email           text NOT NULL,
  display_name    text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE organization_memberships (
  id               uuid PRIMARY KEY,
  organization_id  uuid NOT NULL REFERENCES organizations (id),
  user_id          uuid NOT NULL REFERENCES users (id),
  role             text NOT NULL,
  is_active        boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);

CREATE TABLE organization_settings (
  organization_id  uuid PRIMARY KEY REFERENCES organizations (id),
  timezone         text NOT NULL DEFAULT 'Asia/Kolkata',
  currency_code    text NOT NULL DEFAULT 'INR',
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_keys (
  id               uuid PRIMARY KEY,
  organization_id  uuid NOT NULL REFERENCES organizations (id),
  idempotency_key  text NOT NULL,
  request_hash     text NOT NULL,
  response_status  integer,
  response_body    jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, idempotency_key)
);

-- Example child table: composite FK prevents cross-tenant parent reference
CREATE TABLE employees (
  id               uuid PRIMARY KEY,
  organization_id  uuid NOT NULL REFERENCES organizations (id),
  sevarth_id       text NOT NULL,
  UNIQUE (organization_id, sevarth_id)
);

CREATE TABLE employee_bank_accounts (
  id               uuid PRIMARY KEY,
  organization_id  uuid NOT NULL,
  employee_id      uuid NOT NULL,
  account_number   text NOT NULL,
  UNIQUE (organization_id, employee_id, account_number),
  FOREIGN KEY (organization_id, employee_id)
    REFERENCES employees (organization_id, id)
);
```

### 2. Forced Row Level Security (mandatory)

Every org-owned table enables **and forces** RLS in the **first** migration that creates it. RLS is never bolted on later:

```sql
ALTER TABLE organization_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_memberships FORCE ROW LEVEL SECURITY;

ALTER TABLE organization_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_settings FORCE ROW LEVEL SECURITY;

ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;

ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees FORCE ROW LEVEL SECURITY;

-- Repeat for every tenant-owned table at creation time.
```

`FORCE ROW LEVEL SECURITY` makes RLS bind even the table owner. The migration-owner role uses `BYPASSRLS`, or a separate privilege path, for DDL and migrations; see roles below. Runtime roles never bypass RLS.

**Policy pattern** (tenant isolation via transaction GUCs):

```sql
CREATE POLICY tenant_isolation ON employees
  FOR ALL
  TO accord_app
  USING (
    organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid
  )
  WITH CHECK (
    organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid
  );
```

Behavior when the setting is unset:

- `current_setting('app.organization_id', true)` returns `NULL` when the setting is missing. The `true` argument means “missing OK”.
- `NULLIF(..., '')::uuid` yields `NULL`.
- The predicate `organization_id = NULL` is never true for a real UUID row. So **SELECT/UPDATE/DELETE return zero rows** (fail closed).
- `WITH CHECK` rejects INSERT and UPDATE when the cast or setting is NULL, or when the row’s `organization_id` does not match. **Writes fail closed** too.

Apply the same `tenant_isolation` policy (or per-command policies) to every tenant-owned table, for the runtime and worker roles.

### 3. Transaction-local context (`SET LOCAL`)

The app binds tenant context right after it gets a connection or transaction for a tenant-scoped request. It does so **before** any tenant query:

```sql
SET LOCAL app.organization_id = '11111111-1111-1111-1111-111111111111';
SET LOCAL app.user_id = '22222222-2222-2222-2222-222222222222';
SET LOCAL app.request_id = 'a1b2c3d4e5f6789012345678abcdef01';
```

Python sketch (SQLAlchemy async session / connection):

```python
async def bind_tenant_context(
    connection,
    *,
    organization_id: str,
    user_id: str,
    request_id: str,
) -> None:
    await connection.execute(
        text("SELECT set_config('app.organization_id', :org, true)"),
        {"org": organization_id},
    )
    await connection.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": user_id},
    )
    await connection.execute(
        text("SELECT set_config('app.request_id', :rid, true)"),
        {"rid": request_id},
    )
```

`SET LOCAL` / `set_config(..., is_local=true)` is **required**. Session-scoped `SET` is not allowed. Accord uses a pooled async engine (asyncpg plus SQLAlchemy), so connections are reused across requests. A session-scoped `app.organization_id` left by tenant A would still be set when tenant B checks out the same connection. That is a silent cross-tenant context leak. Transaction-local settings reset when the transaction ends, so the next checkout starts clean.

### 4. Database roles

Three roles, created in an early migration or ops bootstrap:

```sql
-- Owns schema/tables; runs Alembic; may bypass RLS for DDL/data migrations.
CREATE ROLE accord_migrator WITH
  LOGIN
  PASSWORD /* from secrets manager — never committed */
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  BYPASSRLS;

-- Runtime API role: RLS always applies; DML only; does not own tables.
CREATE ROLE accord_app WITH
  LOGIN
  PASSWORD /* from secrets manager */
  NOSUPERUSER
  NOBYPASSRLS
  NOCREATEDB
  NOCREATEROLE;

-- Background workers / jobs: same RLS constraint; narrower grants as needed.
CREATE ROLE accord_worker WITH
  LOGIN
  PASSWORD /* from secrets manager */
  NOSUPERUSER
  NOBYPASSRLS
  NOCREATEDB
  NOCREATEROLE;

-- Ownership and grants (illustrative)
ALTER TABLE employees OWNER TO accord_migrator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE employees TO accord_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE employees TO accord_worker;

-- Prefer granting on a schema or via future table groups; never GRANT BYPASSRLS
-- or ownership to accord_app / accord_worker.
GRANT USAGE ON SCHEMA public TO accord_app, accord_worker;
```

| Role | Purpose | RLS |
| --- | --- | --- |
| `accord_migrator` | Alembic / DDL / controlled data migrations (`MIGRATIONS_DATABASE_URL`) | May `BYPASSRLS` for migration tooling only |
| `accord_app` | FastAPI request path (`DATABASE_URL`) | Always subject to RLS (`NOBYPASSRLS`) |
| `accord_worker` | Background jobs | Always subject to RLS; grants may be narrower than API |

Runtime and worker DSNs must never use the migrator credentials (see [0003-backend-bootstrap-environment.md](0003-backend-bootstrap-environment.md)).

### 5. Invariant: organization scope is never client-supplied

A request body **must never** carry `organization_id` (or any equivalent org scope) as trusted input for read or write scoping. The server resolves the org from the authenticated session’s active organization. The URL may carry it only in the narrow cases in [0004-organization-url-session-context.md](0004-organization-url-session-context.md).

Rules:

- Create or update payloads for tenant-owned rows that include `organization_id` are **ignored or rejected**. Phase 1 prefers reject, with a 422 Problem Detail. The value is never honored over session context.
- Handlers stamp `organization_id` from session or middleware before INSERT.
- RLS `WITH CHECK` is the last line of defense if app code is wrong.

### 6. Testing strategy (direct SQL as runtime role)

RLS tests connect **as `accord_app`** (or a test clone of that role). They never connect as a superuser, or as a migrator with `BYPASSRLS`.

Minimum assertions:

1. **Cross-tenant read/update/delete isolation:** seed a row for org A. Set `app.organization_id` to org B. `SELECT`/`UPDATE`/`DELETE` against that row must return **zero rows**, even though the row exists when queried as migrator.
2. **Mismatched INSERT rejected:** with `app.organization_id = A`, an `INSERT` with `organization_id = B` fails `WITH CHECK`.
3. **Cross-tenant matrix:** seed N ≥ 2 orgs with overlapping natural keys (same `sevarth_id`, same idempotency key string, and so on). For every tenant-owned table, one parameterized test binds each org’s context and asserts the org sees only its own rows. Prefer one generic, parameterized harness over one hand-written test per table where feasible.

```sql
-- Shape of a direct-SQL isolation check
SET ROLE accord_app;
SELECT set_config('app.organization_id', :org_b, true);

SELECT count(*) FROM employees WHERE id = :employee_in_org_a;
-- expect 0

UPDATE employees SET sevarth_id = 'x' WHERE id = :employee_in_org_a;
-- expect 0 rows updated

INSERT INTO employees (id, organization_id, sevarth_id)
VALUES (gen_random_uuid(), :org_a, 'overlap-key');
-- expect failure (WITH CHECK) when GUC is org_b
```

### 7. Entity-relationship sketch

```mermaid
erDiagram
  users {
    uuid id PK
    text workos_user_id UK
    text email
    text display_name
  }

  organizations {
    uuid id PK
    text name
    text slug UK
  }

  organization_memberships {
    uuid id PK
    uuid organization_id FK
    uuid user_id FK
    text role
    boolean is_active
  }

  organization_settings {
    uuid organization_id PK_FK
    text timezone
    text currency_code
  }

  idempotency_keys {
    uuid id PK
    uuid organization_id FK
    text idempotency_key
    text request_hash
  }

  users ||--o{ organization_memberships : "memberships"
  organizations ||--o{ organization_memberships : "has"
  organizations ||--|| organization_settings : "settings"
  organizations ||--o{ idempotency_keys : "scoped by org"
```

Notes:

- `users` has **no** `organization_id`. Multi-org membership exists only via `organization_memberships`.
- `idempotency_keys` is per org, with the composite unique key `(organization_id, idempotency_key)`.
- India-specific locale, timezone, currency, and financial-year conventions are app invariants. Their public mutable API is retired. The `organization_settings` table remains for now as a rolling-deploy compatibility shell for older binaries.

## Consequences

- PostgreSQL enforces tenant isolation for every tenant-owned table from day one. When context is bound correctly, a missing app-level `WHERE` clause cannot leak rows across orgs.
- Connection pooling is safe only if every tenant path uses `SET LOCAL` or local `set_config`, and never session-scoped GUCs.
- Ops must keep two DSNs (migrator and app), and must never point the API at a `BYPASSRLS` role.
- Composite FKs demand more care in migrations, since parent uniqueness must include `organization_id`. In return, they remove a whole class of cross-tenant join bugs.
- Direct-SQL RLS tests become a release gate for schema changes that add tenant-owned tables.
- App authors must treat `organization_id` in request bodies as hostile, untrusted input.

## Alternatives Considered

1. **Application-only filters (no RLS)** — Rejected. One missed predicate is a cross-tenant breach. That risk is unacceptable for multi-org government payroll.
2. **RLS without FORCE** — Rejected. Table owners and privileged connections can bypass policies by accident. `FORCE ROW LEVEL SECURITY` closes that gap for non-bypass roles.
3. **Session-scoped `SET app.organization_id`** — Rejected. It is unsafe with asyncpg/SQLAlchemy connection pools. Context can leak across requests.
4. **Separate database/schema per tenant** — Deferred/rejected for Phase 0. It is too heavy to operate for many municipalities. RLS plus a shared schema is the chosen multi-tenant model.
5. **Trust `organization_id` from JSON body** — Rejected. It enables IDOR via body tampering. Session and server-side resolution is mandatory (see ADR 0004).
