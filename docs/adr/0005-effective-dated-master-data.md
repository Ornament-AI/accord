# ADR 0005: Effective-dated master data

- **Status:** Accepted (Phase 0)
- **Date:** 2026-07-17
- **Related:** [payroll-domain.md](../payroll-domain.md), [ADR 0006](0006-money-decimal-rounding.md), [ADR 0007](0007-payroll-run-calculation-model.md)

## Context

Local-government payroll master data changes over time: post and pay placement, bank accounts, recurring deduction/contribution instructions, accommodation assignments, and statutory rates. Payroll runs must be reproducible years later: a posted June 2026 run must still show exactly which bank account version, pay placement, and rate rows it used.

Mutating a single “current” row in place destroys history and makes posted runs non-auditable. Overlapping “current” rows for the same business key create ambiguous as-of resolution.

We need:

1. Stable identity for the business entity.
2. Immutable, effective-dated versions for time-varying attributes.
3. Database-enforced non-overlapping active periods.
4. A single canonical “effective on date D” query used everywhere.
5. Posted payroll run versions that pin exact source version ids (see ADR 0007).

## Decision

### Pattern: header + immutable versions

- **Header / identity table:** stable surrogate `id`, organization scope, immutable business keys (e.g., Sevarth ID on employee). Headers are not used to store time-varying pay attributes.
- **Version table:** append-only rows for attributes that change. Each row has:
  - `id` (version id, UUID or bigint)
  - FK to header
  - `organization_id`
  - business key columns as needed for exclusion
  - `effective_period` as PostgreSQL `daterange` (convention: `[effective_from, effective_to)` — inclusive start, exclusive end; open upper bound for “until further notice”)
  - payload columns (pay scale, bank account numbers, instruction amounts, etc.)
  - audit columns (`created_at`, `created_by`, reason/change note)

**Rules:**

1. Changes **always** insert a new version row. History rows are **never** updated or deleted (append-only / immutable). Corrections that fix a mistaken future version still append a superseding version (or a controlled admin correction process that inserts compensating versions)—they do not overwrite posted-referenced rows.
2. **Future-dated** changes are allowed (`lower(effective_period)` in the future).
3. PostgreSQL **GiST `EXCLUDE`** constraints prevent overlapping **active** version periods per `(organization_id, business_key)` (and header id where the business key is the header).
4. Posted payroll run versions store the **exact source version id(s)** they read. Those version rows remain immutable forever once created; posting does not change this—it only adds references. Even unreferenced versions are not rewritten; posting strengthens the retention requirement for referenced ids.

### Canonical “effective on date D” primitive

Define **once** (SQL function and/or view) and reuse from all application queries and calculators:

```sql
-- Canonical primitive: version active on date D
-- Example name; implement exactly once and reuse.
CREATE OR REPLACE FUNCTION version_effective_on(
  p_period daterange,
  p_on date
) RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT p_period @> p_on;
$$;
```

Application queries for a concrete version table always filter with the same predicate, e.g. `effective_period @> :on_date` (or `version_effective_on(effective_period, :on_date)`), plus organization and business-key predicates. Calculators in ADR 0007 must resolve master data only through this primitive (or repositories that wrap it), never ad-hoc date logic.

### Representative DDL

Example: employee bank account — header employee already exists; bank account versions are effective-dated.

```sql
-- Identity/header (attributes that are not time-sliced live here)
CREATE TABLE employee (
  id              uuid PRIMARY KEY,
  organization_id uuid NOT NULL,
  sevarth_id      text NOT NULL,
  -- other stable identity fields...
  UNIQUE (organization_id, sevarth_id)
);

-- Effective-dated versions of salary bank account
CREATE TABLE employee_bank_account_version (
  id              uuid PRIMARY KEY,
  organization_id uuid NOT NULL,
  employee_id     uuid NOT NULL REFERENCES employee (id),
  effective_period daterange NOT NULL,
  account_holder  text NOT NULL,
  bank_name       text NOT NULL,
  account_number  text NOT NULL,
  ifsc            text NOT NULL,
  is_primary      boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  created_by      uuid NOT NULL,
  change_reason   text,
  CONSTRAINT employee_bank_account_version_period_valid
    CHECK (NOT isempty(effective_period)),
  -- Prevent overlapping active periods for primary account per employee
  EXCLUDE USING gist (
    organization_id WITH =,
    employee_id WITH =,
    effective_period WITH &&
  ) WHERE (is_primary)
);

-- Effective-on-date query (reuse everywhere)
-- :on_date is the service date / period anchor used by the pay run
SELECT v.*
FROM employee_bank_account_version v
WHERE v.organization_id = :organization_id
  AND v.employee_id = :employee_id
  AND v.is_primary
  AND v.effective_period @> :on_date::date;
```

Example shape for pay placement (same pattern):

```sql
CREATE TABLE employee_pay_placement_version (
  id               uuid PRIMARY KEY,
  organization_id  uuid NOT NULL,
  employee_id      uuid NOT NULL REFERENCES employee (id),
  effective_period daterange NOT NULL,
  post_name        text NOT NULL,
  pay_level        text NOT NULL,
  basic_pay        numeric(18, 2) NOT NULL, -- money: NUMERIC; see ADR 0006
  created_at       timestamptz NOT NULL DEFAULT now(),
  created_by       uuid NOT NULL,
  change_reason    text,
  CONSTRAINT employee_pay_placement_version_period_valid
    CHECK (NOT isempty(effective_period)),
  EXCLUDE USING gist (
    organization_id WITH =,
    employee_id WITH =,
    effective_period WITH &&
  )
);
```

Statutory rates, recurring instructions, and accommodation assignments use the same header/version + `daterange` + GiST exclusion pattern.

### Interaction with posted runs

`payroll_run_versions` (ADR 0007) persist references such as `employee_pay_placement_version_id`, `employee_bank_account_version_id`, rate version ids, and instruction version ids on each line’s calculation trace. Those FKs point at immutable version rows. Correcting master data after posting means inserting a **new** version with a new period—not editing the row a posted run already referenced.

## Consequences

**Positive:**

- As-of payroll and historical audit are well-defined.
- Database enforces non-overlapping versions.
- Posted runs remain reproducible when combined with engine version + decimal policy (ADR 0006, ADR 0007).

**Negative / costs:**

- All master-data APIs must be version-aware (no silent in-place edit of payload).
- Application must close/clip prior open-ended ranges when inserting a superseding version (transactionally) so GiST exclusion remains satisfiable.
- Storage grows with every change (accepted for payroll auditability).

**Open questions:**

- Exact timezone / calendar convention for period boundaries across state holidays (document when pay calendar is specified).
- Whether non-primary bank accounts need a separate exclusion key (purpose code) — decide when multi-account payments are in scope.
