# Implementation plan: catalog-driven report exports (rev 2)

Status: draft for review — revised 20 Jul 2026 after reviewer feedback; all eight review points verified against code and accepted.
Motivation: Pay Bill (and advance-schedule) columns are hardcoded module constants while `pay_components` is a dynamic per-org catalog. Components outside `_EARNING_CODES` / `_DEDUCTION_COLUMN_CODES` are included in totals but get no column, so visible cells stop summing to printed totals. Reference: *Pay bill – June 2026 Regular Staff.xlsx*.

Key revisions from rev 1: no live `PayComponent` reads (snapshot presentation metadata instead); `v1` layout preserved, dynamic layout ships as `v2` with per-report default versions; full gross-to-net layout including `gross_adjustment`; employee identity snapshotted at calc time; Phase 4 rebuilt around posted lines; Phase 3 corrected (existing `*_ADVANCE_INSTALLMENT` codes, no PLI/CGIS defaults); bill numbers are run-level, not org config; combined workbook is an alternate consolidated artifact, not a new report kind.

---

## Phase A — Snapshot metadata at calculation time (prerequisite)

Both blocks go into `payroll_run_versions.inputs_snapshot` (JSONB — no migration).

**A1. Component catalog block.** At calc time (`app/services/run_calculation.py`), write `inputs_snapshot["component_catalog"]`: list of `{code, name, display_order, classification}` for every component that produced a line. Reports read only this; renaming a live component never changes a posted report.

**A2. Employee report identity block.** Write `inputs_snapshot["employee_identity"]` (or a parallel structure keyed by employee id): `{name, designation, pan, gpf_account_number}` resolved from the effective-dated versions pinned at calc time. This replaces the register's month-end re-resolution (`_resolve_name_and_designation`, `payroll_register.py:189`), closing an existing snapshot-contract gap and removing per-employee query growth.

**Historical-run fallback.** Runs posted before this change lack both blocks. Fallback: component headers = raw code, ordering = classification group then minimum posted line `sequence`; identity = the existing month-end resolver (documented as legacy behavior for legacy runs). Never fall back to the live catalog for names/order.

Tests: snapshot blocks written on calculation; mutation of live `PayComponent.name`/`display_order` after posting does not change regenerated DTO; fallback path exercised on a run without the blocks.

## Phase B — Per-report template versions

`app/services/report_generation.py` has one global `DEFAULT_TEMPLATE_VERSION = "v1"`. Add a per-report-type default version map (registry-level), keeping `v1` builders/layouts intact. Pay Bill `v2` registers alongside `v1`; other reports stay `v1`. The consolidated manifest (`{base_version}+{manifest_hash}`) must encode mixed versions. Artifact rows already record `template_version` per artifact — no schema change expected.

Tests: requesting `v1` after `v2` ships reproduces the old fixed layout byte-for-byte (existing tests pinned to `v1`); default resolution picks `v2` for Pay Bill only.

## Phase C — Pay Bill register `v2`

`backend/app/reports/families/payroll_register.py`, new layout derived from `component_catalog` + posted lines. Full gross-to-net structure matching `app/domain/payroll/results.py`:

- Identity: Employee No., Name, Designation, PAN, GPF Account No. (from A2)
- Earning components → **Earnings Total**
- Employer-contribution components → **Employer Share Total**
- Gross-adjustment components → **Gross Adjustment Total**
- **Gross Bill**
- AG-deduction components → **AG Total**
- Treasury-deduction components → **Treasury Total**
- External-recovery components → **External Recovery Total**
- **Deductions Total**
- **Net Payable**

Rules:

- Aggregate columns always present. Component columns present when ≥1 posted line exists for that code in the run, even if all amounts are zero.
- Column keys: `component:BASIC` — exact code case preserved (lowercasing risks duplicate JSON keys).
- Ordering within each classification group: snapshot `display_order`, then code.
- **Fail generation** (ConflictError) if one component code appears under multiple classifications in a single run.
- Headers from snapshot `name`, fallback raw code.
- Informational lines / `FOREGONE_HRA` stay excluded (existing filter).

Tests: per-row and footer reconciliation — component columns sum to each aggregate, aggregates satisfy the gross-to-net identity — using a run with a component in no legacy list (e.g. CLA); key-uniqueness; classification-conflict rejection; zero-amount component still gets a column; ordering.

**Rendering check (before sign-off):** JSON and Excel are width-safe; the generic PDF gives every column equal width (`pdf.py:135`), so a wide catalog-driven register can become unreadable. Visually test a maximum-width run; if unacceptable, PDF `v2` may need landscape/split-section layout — scoped decision within this phase, not a blocker for Excel/JSON.

## Phase D — Fixture and seed corrections

- `scripts/seed_paybill_xlsx.py:601` collapses CLA + wash + other into `OTHER_ALLOWANCE`. Emit separate `CLA` and `WASH_ALLOWANCE` recurring instructions (and matching components in the fixture).
- Use existing engine codes: `FESTIVAL_ADVANCE_INSTALLMENT`, `MOTOR_CAR_ADVANCE_INSTALLMENT`, `MOTORCYCLE_ADVANCE_INSTALLMENT` (already in `run_calculation.py:89` and `recovery.py:73`) — no new parallel codes.
- No PLI/CGIS defaults — the workbook heading is a grouped label; add only if real source lines or onboarding policy require them.
- No "default org component bootstrap" exists; out of scope here. (If wanted, it's a separately named feature.)
- Off-bill NPS employer: already present in `components.json` — no action.

## Phase E — Combined non-HBA advance schedule

`backend/app/reports/families/recovery.py`. Replace per-type generic schedules with **one** combined non-HBA schedule selecting posted lines where `classification = 'external_recovery'` and `calc_kind = 'loan_installment_recovery'` and resolved advance type ≠ `hba`, with an "Advance type / component" column. Fits the fixed three-input builder contract and closed registry (no dynamic report kinds). HBA keeps its dedicated schedule.

Replace `test_recovery_reports.py:430`, which currently asserts the generic schedule *equals* HBA (built with `advance_type="hba"`), with a guard: combined schedule never contains HBA rows; combined total + HBA total = posted `loan_installment_recovery` external recoveries.

## Phase F — Run-level bill metadata (design, then build)

Three tiers, not org-wide `ReportConfiguration` (which is non-versioned and org-scoped; Bill/Token/Voucher are document-level per the MTR-19 Face sheet):

- **Organization defaults** (`ReportConfiguration`): DDO code, default head-of-account fields.
- **Run snapshot**: Bill No., Demand No., resolved accounting heads — captured at/before posting.
- **Treasury-submission record** (future): Token No., Voucher No., dates — assigned after submission.

First release: Face renders org defaults + run snapshot; Token/Voucher render blank. Needs a short design note (where Bill No. lives on the run, who sets it) before implementation.

## Phase G — Single-workbook consolidated export (separate design review)

`consolidated_xlsx` already exists: 13 per-report workbooks zipped (`report_generation.py:495`). A single multi-sheet workbook is an **alternate consolidated artifact format** on that path — not a registered report builder. Note: product allowlist has 13 sheets; the reference workbook's 18 include legacy forms the catalog excludes. Keep as its own design decision; not in this change series.

---

## Sequencing

1. Phase A (snapshot metadata + fallback) — prerequisite.
2. Phase B (per-report template versions, retain `v1`).
3. Phase C (Pay Bill `v2` + full test set + PDF width check).
4. Phase D (fixture/seed corrections).
5. Phase E (combined non-HBA schedule + replaced guard test).
6. Phase F (run-level bill metadata design → build).
7. Phase G (separate review).

A+B+C is the core series; D and E can land independently after A. Nothing deletes or mutates `v1` behavior.

## Out of scope

- PaySlip layout changes (already line-driven).
- Visual fidelity to the workbook (merged headers, Marathi headings) — template-version concern.
- Default-component bootstrap feature.
- Single-workbook consolidated export (Phase G placeholder only).
