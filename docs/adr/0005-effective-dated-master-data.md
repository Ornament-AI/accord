# ADR 0005: Effective-dated master data

- **Status:** Accepted (Phase 0)
- **Date:** 2026-07-17
- **Related:** [payroll-domain.md](../payroll-domain.md), [ADR 0006](0006-money-decimal-rounding.md), [ADR 0007](0007-payroll-run-calculation-model.md)

## Context

Local-government payroll master data changes over time. Examples: post and pay placement, bank accounts, and recurring deduction and contribution instructions. So do accommodation assignments and statutory rates. Payroll runs must be reproducible years later. A posted June 2026 run must still show exactly which bank account version, pay placement, and rate rows it used.

Editing a single “current” row in place destroys history. Posted runs then cannot be audited. “Current” rows that overlap for the same business key make as-of lookups unclear.

We need:

1. Stable identity for the business entity.
2. Immutable, effective-dated versions for values that change over time.
3. Active periods that do not overlap, enforced by the database.
4. One canonical “effective on date D” query, used everywhere.
5. Posted payroll run versions that pin exact source version ids (see ADR 0007).

## Decision

### Pattern: header + immutable versions

- **Header / identity table:** stable surrogate `id`, org scope, and immutable business keys (e.g., the Sevarth ID on an employee). Headers do not store pay values that change over time.
- **Version table:** append-only rows for values that change. Each row has:
  - `id` (version id, UUID or bigint)
  - FK to header
  - `organization_id`
  - business key columns as needed for exclusion
  - `effective_period` as PostgreSQL `daterange` (convention: `[effective_from, effective_to)` — the start is included, the end is not; an open upper bound means “until further notice”)
  - payload columns (pay scale, bank account numbers, instruction amounts, etc.)
  - audit columns (`created_at`, `created_by`, reason/change note)

**Rules:**

1. Changes **always** insert a new version row. History rows are **never** updated or deleted (append-only, immutable). A fix for a wrong future version still appends a new version that supersedes it (or it goes through a controlled admin process that adds compensating versions). A fix never overwrites a row that a posted run points to.
2. **Future-dated** changes are allowed (`lower(effective_period)` in the future).
3. PostgreSQL **GiST `EXCLUDE`** constraints stop **active** version periods from overlapping per `(organization_id, business_key)` (and per header id where the business key is the header).
4. Posted payroll run versions store the **exact source version id(s)** they read. Once created, those version rows never change. Posting does not change this — it only adds references. Even versions that no run points to are never rewritten. Posting only strengthens the retention rule for referenced ids.

### Canonical “effective on date D” primitive

Define this **once** (as a SQL function and/or view) and reuse it from all app queries and calculators:

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

App queries on a concrete version table always filter with the same predicate, e.g. `effective_period @> :on_date` (or `version_effective_on(effective_period, :on_date)`), plus org and business-key filters. Calculators in ADR 0007 must read master data only through this primitive, or through repositories that wrap it. They must never use ad-hoc date logic.

### Representative DDL

Example: employee bank account. The header employee already exists; bank account versions are effective-dated.

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

Statutory rates, recurring instructions, and accommodation assignments use the same pattern: header/version, plus `daterange`, plus GiST exclusion.

### Interaction with posted runs

`payroll_run_versions` (ADR 0007) store references such as `employee_pay_placement_version_id`, `employee_bank_account_version_id`, rate version ids, and instruction version ids on each line’s calculation trace. Those FKs point at immutable version rows. To fix master data after posting, insert a **new** version with a new period. Never edit the row a posted run already points to.

## Consequences

**Positive:**

- As-of payroll and audits of past data are well defined.
- The database enforces that versions do not overlap.
- Posted runs stay reproducible, when combined with the engine version and decimal policy (ADR 0006, ADR 0007).

**Negative / costs:**

- All master-data APIs must be version-aware. There is no silent in-place edit of a payload.
- When the app inserts a superseding version, it must close or clip the prior open-ended range in the same transaction. Otherwise the GiST exclusion cannot be met.
- Storage grows with every change (we accept this; payroll must stay fit for audit).

**Open questions:**

- The exact timezone and calendar rules for period bounds across state holidays (write these down when the pay calendar is defined).
- Whether non-primary bank accounts need a separate exclusion key (purpose code). Decide when multi-account payments are in scope.
