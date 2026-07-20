# ADR 0007: Payroll run calculation model

- **Status:** Accepted (Phase 0)
- **Date:** 2026-07-17
- **Related:** [payroll-domain.md](../payroll-domain.md), [ADR 0005](0005-effective-dated-master-data.md), [ADR 0006](0006-money-decimal-rounding.md)

## Context

Payroll for a period is not a single mutable spreadsheet. Draft inputs change (monthly exceptions); calculated outputs must be immutable snapshots for maker/checker review, posting, and later audit. Each employee line must explain **how** it was computed: which effective-dated master versions (ADR 0005), which rate, which rounding rule (ADR 0006), and which calculator kind.

User-authored formula DSLs are rejected: they are hard to audit, easy to cycle, and unstable for statutory payroll. Instead we use a **typed calculator registry** with explicit dependency ordering.

Domain aggregates and classifications are defined in [payroll-domain.md](../payroll-domain.md) (gross-to-net identity, component classifications: `earning`, `employer_contribution`, `AG_deduction`, `treasury_deduction`, `gross_adjustment`, `external_recovery`).

## Decision

### Aggregates

| Aggregate | Role |
| --- | --- |
| `payroll_periods` | The pay calendar period being served (e.g., June 2026). |
| `payroll_runs` | An execution instance against a period (and organization / bill scope). Holds workflow status and points at the current draft inputs; does not itself store immutable line results. |
| `payroll_run_versions` | **Immutable** calculation snapshots. Each calculation execution appends a new run version. Never mutated after creation. |

### Mutable draft inputs

Monthly exceptions / overrides live on the run (or period+run scope) as **mutable DRAFT** inputs until a calculation consumes them into a run version:

- **reason** (mandatory text / code)
- **service period** (which dates within the payroll period the exception applies to)
- **optimistic-concurrency version number** (integer; update must supply expected version to prevent lost updates)

Recurring instructions and statutory rates are **not** draft run inputs; they are effective-dated master data (ADR 0005), resolved as-of the run’s service date(s).

### Immutable run versions and line items

Each `payroll_run_version` contains:

- run + period identifiers
- `engine_version` and `content_hash` (ADR 0006)
- per-employee results (gross, deductions, net, employer share contributions, etc.)
- per-employee **line items**

Each line item carries a full **calculation trace**:

| Trace field | Meaning |
| --- | --- |
| `component` | Pay component identity / code |
| `classification` | One of the six classifications in payroll-domain.md |
| `source_version_ids` | Exact effective-dated master version id(s) read (ADR 0005) |
| `basis` | Value/quantity the line was computed from (e.g., basic pay, component bases) |
| `rate` | Rate if applicable (decimal string semantics per ADR 0006) |
| `unrounded_value` | Pre-round `Decimal`/`NUMERIC` |
| `rounding_rule` | Named rule from ADR 0006 |
| `rounded_value` | Post-round amount |
| `calculator_kind` | Key in the typed calculator registry |
| `engine_version` | Engine version string (denormalized for line-level audit if needed; at minimum on the run version) |

### Typed calculator registry (no user-authored DSL)

There is **no** end-user formula language, spreadsheet expression engine, or arbitrary scripting for pay rules. New behaviors are added as reviewed, versioned calculator kinds in code.

Initial calculator kinds:

| Kind | Description |
| --- | --- |
| `fixed_recurring_amount` | Emits a fixed amount from an effective-dated recurring instruction (e.g., standing allowance or fixed deduction). |
| `direct_monthly_amount` | Uses a draft monthly exception / direct amount for the period (approved override or one-time line). |
| `percentage_of_component_bases` | Computes a percentage of one or more already-calculated basis components (depends on those components). |
| `employer_employee_contribution` | Paired employer + employee contribution legs (NPS/DCPS, EPF, etc.) with transfer-out pairing per Gross-to-net identity in payroll-domain.md. |
| `loan_installment_recovery` | Fixed / scheduled installment recovery (HBA and other advances) classified typically as `external_recovery`. |
| `accommodation_charge` | Actual license-fee recovery from effective-dated accommodation assignment; informational/foregone HRA is separate and non-payable. |
| `one_time_adjustment` | Explicit approved one-time line for deferred/unproven behaviors (arrears, complex proration, etc.—see payroll-domain.md Unproven behaviors). |

Component classifications from the domain glossary attach to components/lines; calculators produce amounts that must be consistent with those classifications (e.g., `employer_employee_contribution` produces `employer_contribution` + employee deduction classifications and matching transfer-out lines).

### Effective-dated rates and config

Rates and calculator config tables are themselves effective-dated using the ADR 0005 pattern (`daterange` + GiST exclusion + effective-on-date primitive). Calculators resolve config only through that primitive and record the version ids on the trace.

### Dependency ordering and cycle rejection

Calculators declare dependencies on component codes / calculator outputs (e.g., `percentage_of_component_bases` depends on basis components completing first). The engine:

1. Builds a directed dependency graph for the run’s component set.
2. Topologically orders calculation.
3. **Rejects cycles loudly** — if a cycle is detected, calculation **fails** with an explicit error identifying the cycle; it must not loop, truncate arbitrarily, or produce partial wrong nets.

### Workflow statuses (enumeration only)

A full workflow contract is a **separate future document**. For Phase 0, only enumerate:

| Status / action | One-line description |
| --- | --- |
| `draft` | Run exists; draft exceptions may be edited (with optimistic concurrency). |
| `calculated` | At least one immutable `payroll_run_version` has been produced for review. |
| `submitted` | Maker has submitted a run version for checker approval. |
| `approved` | Checker approved a specific run version. |
| `posted` | Approved version committed to books/remittance outputs; source version ids frozen by reference. |
| `withdraw` | Pull back from submitted (or analogous) before approval completes. |
| `reject` | Checker rejects a submission; returns to an editable pre-submit state per future workflow doc. |
| `reverse` | Formal reversal of a posted run without mutating the original posted version. |

Allowed transitions and authorization matrices are **out of scope** here.

## Consequences

**Positive:**

- Auditable, deterministic runs aligned with ADR 0005/0006 and payroll-domain gross-to-net contracts.
- Typed calculators keep statutory logic reviewable in code review.
- Cycle rejection prevents silent wrong pays.

**Negative / costs:**

- New pay behaviors require engineering changes (calculator kinds), not config-only DSL—accepted for control.
- Storage of full traces increases volume (accepted).

**Open questions:**

- Resolution of NPS employer vs narrow employer share in gross bill (see Proven June 2026 invariants open question in payroll-domain.md)—calculator `employer_employee_contribution` must not assume an answer until finance signs off.
