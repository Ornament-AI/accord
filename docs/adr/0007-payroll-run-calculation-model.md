# ADR 0007: Payroll run calculation model

- **Status:** Accepted (Phase 0)
- **Date:** 2026-07-17
- **Related:** [payroll-domain.md](../payroll-domain.md), [ADR 0005](0005-effective-dated-master-data.md), [ADR 0006](0006-money-decimal-rounding.md)

## Context

Payroll for a period is not one mutable spreadsheet. Draft inputs change during the month (monthly exceptions). But once a run is calculated, its output must be a frozen snapshot. Maker/checker review, posting, and later audits all rest on that. Each employee line must show **how** it was computed: which master versions as of which dates (ADR 0005), which rate, which rounding rule (ADR 0006), and which calculator kind.

We reject user-authored formula DSLs. They are hard to audit, easy to cycle, and not stable for statutory payroll. Instead, pay rules live in code as a **typed calculator registry**, and each kind states what it depends on.

The domain doc, [payroll-domain.md](../payroll-domain.md), defines the aggregates, the gross-to-net identity, and the six component classes: `earning`, `employer_contribution`, `AG_deduction`, `treasury_deduction`, `gross_adjustment`, `external_recovery`.

## Decision

### Aggregates

| Aggregate | Role |
| --- | --- |
| `payroll_periods` | The pay calendar period being served (e.g., June 2026). |
| `payroll_runs` | An execution instance against a period (and organization / bill scope). Holds workflow status and points at the current draft inputs; does not itself store immutable line results. |
| `payroll_run_versions` | **Immutable** calculation snapshots. Each calculation execution appends a new run version. Never mutated after creation. |

### Mutable draft inputs

Monthly exceptions and overrides live on the run (or period+run scope). They stay **mutable DRAFT** inputs until a calculation consumes them into a run version. Each one carries:

- a **reason** (required text or code)
- a **service period**: the dates within the payroll period that the exception covers
- a **version number for optimistic concurrency**: an integer; each update must send the version it expects, so no update is lost

Recurring instructions and statutory rates are **not** draft run inputs. They are effective-dated master data (ADR 0005), read as of the run’s service date(s).

### Immutable run versions and line items

Each `payroll_run_version` contains:

- run + period identifiers
- `engine_version` and `content_hash` (ADR 0006)
- results per employee (gross, deductions, net, employer share, etc.)
- **line items** per employee

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
| `reason` | User-entered or master-data narration that explains the line |
| `service_period` | User-entered start/end dates for the line, when applicable |

### Typed calculator registry (no user-authored DSL)

There is **no** end-user formula language for pay rules. No spreadsheet expression engine. No arbitrary scripting. New behaviors ship in code, as calculator kinds that are reviewed and versioned.

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

The six classes from the domain glossary attach to components and lines. What a calculator emits must match those classes. For example, `employer_employee_contribution` emits an `employer_contribution` leg, an employee deduction leg, and matching transfer-out lines.

### Effective-dated rates and config

Rate tables and calculator config tables carry effective dates too. They use the ADR 0005 pattern: `daterange` + GiST exclusion + the effective-on-date primitive. Config is read only through that primitive, and the version ids land on the trace.

### Dependency ordering and cycle rejection

Each calculator kind lists what it needs first: component codes and the outputs of other kinds. For example, `percentage_of_component_bases` needs its basis components to finish first. The engine:

1. Builds a directed dependency graph for the run’s component set.
2. Sorts the graph in topological order, so every line runs after the lines it needs.
3. **Rejects cycles loudly.** If it finds a cycle, the run **fails** with an explicit error that names the cycle. It must not loop, cut off at some point, or emit partial wrong nets.

### Workflow statuses (enumeration only)

A full workflow contract will come in a **separate future document**. For Phase 0, we only list the states:

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

Allowed transitions and who may do what are **out of scope** here.

## Consequences

**Positive:**

- Runs can be audited and replayed. They line up with ADR 0005/0006 and the gross-to-net contracts in the domain doc.
- Statutory logic goes through code review, since it lives in typed calculators.
- Cycle rejection blocks silent wrong pays.

**Negative / costs:**

- New pay behaviors need code changes (new calculator kinds), not config-only DSL edits. We accept this for control.
- Full traces take more storage. Accepted.

**Open questions:**

- NPS employer share vs the narrow employer share in the gross bill (see the Proven June 2026 open question in payroll-domain.md). The `employer_employee_contribution` calculator must not assume an answer until finance signs off.
