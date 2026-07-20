# Implementation plan: catalog-driven report exports (rev 3)

Status: **implemented in substance** — verified against the code on 20 Jul 2026. Phases A, C, and D landed close to plan. Phases B and E shipped in a simpler, superseding form. Phase F is partly done. Phase G is still open. Each phase below keeps the original plan text and adds a status note.

Motivation: Pay Bill (and advance-schedule) columns were hardcoded module constants, while `pay_components` is a dynamic per-org catalog. Components outside `_EARNING_CODES` / `_DEDUCTION_COLUMN_CODES` were included in totals but got no column. Visible cells then stopped summing to printed totals. Reference: *Pay bill – June 2026 Regular Staff.xlsx*.

Key revisions from rev 1 (all eight review points were verified against code and accepted):

- No live `PayComponent` reads; snapshot presentation metadata instead.
- Keep the `v1` layout; ship the dynamic layout as `v2` with per-report default versions. (Superseded in the shipped code — see Phase B.)
- Full gross-to-net layout, including `gross_adjustment`.
- Snapshot employee identity at calc time.
- Rebuild Phase 4 around posted lines.
- Correct Phase 3: use the existing `*_ADVANCE_INSTALLMENT` codes; no PLI/CGIS defaults.
- Bill numbers are run-level, not org config.
- A combined workbook is an alternate consolidated artifact, not a new report kind.

---

## Phase A — Snapshot metadata at calculation time (prerequisite)

Plan: write two blocks into `payroll_run_versions.inputs_snapshot` (JSONB — no migration).

**A1. Component catalog block.** At calc time, write `inputs_snapshot["component_catalog"]`: a list of `{code, name, display_order, classification}` for every component that produced a line. Reports read only this. Renaming a live component never changes a posted report.

**A2. Employee report identity block.** Write `inputs_snapshot["employee_identity"]` keyed by employee id: `{name, designation, pan, gpf_account_number}` resolved from the effective-dated versions pinned at calc time. This replaces the register's month-end re-resolution (`_resolve_name_and_designation` in `payroll_register.py`). It closes a snapshot-contract gap and removes per-employee query growth.

**Historical-run fallback (as planned).** Runs posted before this change lack both blocks. Planned fallback: component headers = raw code; ordering = classification group, then the smallest posted line `sequence`; identity = the old month-end resolver. Never fall back to the live catalog for names or order.

Planned tests: snapshot blocks written on calculation; editing a live `PayComponent.name` / `display_order` after posting does not change a regenerated DTO; the fallback path is exercised on a run without the blocks.

**Status: done, and extended.** `run_calculation/command.py` writes `component_catalog` and `employee_identity`, plus two more blocks the plan did not name: `report_profile` (DDO code, heads, signatories, bank advice recipient) and `recovery_sources` (advance and accommodation presentation data). The identity block also carries PRAN and bank account fields. At posting, `run_posting.py` copies all blocks into a dedicated `payroll_report_snapshots` table with a provenance column (`posting`, `workbook_backfill`, `current_master_backfill`). The fallback deviates from plan: a posted run with **no** snapshot fails report generation with a conflict error and needs an explicit audited backfill (`app/reports/snapshots.py`) — there is no silent legacy path in `v2`. The raw-code fallback for components missing from the catalog **is** implemented inside the `v2` register (header = code; order = a large offset plus the smallest posted-line sequence). The regeneration-stability test exists (`test_v2_recovery_reports_ignore_later_master_header_edits`).

## Phase B — Per-report template versions

Plan: `app/services/report_generation.py` had one global `DEFAULT_TEMPLATE_VERSION = "v1"`. Add a per-report-type default version map at registry level, keeping `v1` builders and layouts intact. Pay Bill `v2` registers alongside `v1`; other reports stay `v1`. The consolidated manifest (`{base_version}+{manifest_hash}`) must encode mixed versions. Artifact rows already record `template_version` per artifact, so no schema change.

Planned tests: requesting `v1` after `v2` ships reproduces the old fixed layout byte-for-byte; default resolution picks `v2` for Pay Bill only.

**Status: superseded.** The shipped code takes a simpler path. There is still one global default, but it is now `DEFAULT_TEMPLATE_VERSION = "v2"`, and `SUPPORTED_TEMPLATE_VERSIONS` contains only `"v2"`. All product reports moved to `v2` together. `v1` can no longer be requested for new builds; requests outside the supported set are rejected, while finalized `v1` artifacts stay downloadable. Some builders keep a non-`v2` code branch, but the service cannot reach it. The planned per-report version map and the byte-for-byte `v1` test were dropped with it. The consolidated manifest hash (`{base_version}+{manifest_hash}`) exists as planned.

## Phase C — Pay Bill register `v2`

Plan: a new layout in `backend/app/reports/families/payroll_register.py`, derived from `component_catalog` plus posted lines. Full gross-to-net structure matching `app/domain/payroll/results.py`:

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

- Aggregate columns are always present. A component column is present when at least one posted line exists for that code in the run, even if all amounts are zero.
- Column keys: `component:BASIC` — exact code case preserved (lowercasing risks duplicate JSON keys).
- Ordering within each classification group: snapshot `display_order`, then code.
- **Fail generation** (ConflictError) if one component code appears under multiple classifications in a single run.
- Headers come from the snapshot `name`, falling back to the raw code.
- Informational lines / `FOREGONE_HRA` stay excluded (existing filter).

Planned tests: per-row and footer reconciliation — component columns sum to each aggregate, and the aggregates satisfy the gross-to-net identity — using a run with a component in no legacy list (e.g. CLA); key uniqueness; classification-conflict rejection; a zero-amount component still gets a column; ordering.

**Rendering check (planned, before sign-off):** JSON and Excel are width-safe. The generic PDF gives every column equal width, so a wide catalog-driven register can become hard to read. Visually test a maximum-width run. If it fails, the PDF `v2` may need a landscape or split-section layout — a scoped decision within this phase, not a blocker for Excel/JSON.

**Status: done.** The `v2` builder implements the full layout and all the rules above. It goes further than planned in two ways. First, each row is re-checked against the posted per-employee totals (earnings, employer share, gross bill, deductions, net payable); any mismatch fails the build with a ConflictError. Second, the DTO carries trusted `FormulaSpec` relationships, so the Excel formatter can emit real formulas for row totals, footer totals, and column sums. It also cross-checks the snapshot classification against the posted line classification and fails on conflict. Tests cover the dynamic columns and formulas (`test_pay_bill_v2_dynamic_columns_reconcile_and_excel_uses_formulas`). On the rendering check: the shared PDF writer now renders landscape A4, but columns are still equal width.

## Phase D — Fixture and seed corrections

Plan:

- `scripts/seed_paybill_xlsx.py` collapsed CLA + wash + other into `OTHER_ALLOWANCE`. Emit separate `CLA` and `WASH_ALLOWANCE` recurring instructions (and matching components in the fixture).
- Use the existing engine codes `FESTIVAL_ADVANCE_INSTALLMENT`, `MOTOR_CAR_ADVANCE_INSTALLMENT`, `MOTORCYCLE_ADVANCE_INSTALLMENT` (already in the run-calculation resolver and `recovery.py`) — no new parallel codes.
- No PLI/CGIS defaults — the workbook heading is a grouped label; add them only if real source lines or onboarding policy require them.
- No "default org component bootstrap" exists; out of scope here. (If wanted, it is a separately named feature.)
- Off-bill NPS employer: already present in `components.json` — no action.

**Status: done.** The seed script defines and emits `CLA` and `WASH_ALLOWANCE` as their own components. The advance codes above are the ones used by the resolver (`run_calculation/resolution.py`) and the recovery report family. No PLI/CGIS defaults were added. `components.json` carries the off-bill `NPS_EMPLOYER_TRANSFER` note.

## Phase E — Combined non-HBA advance schedule

Plan: in `backend/app/reports/families/recovery.py`, replace per-type generic schedules with **one** combined non-HBA schedule. Select posted lines where `classification = 'external_recovery'`, `calc_kind = 'loan_installment_recovery'`, and the resolved advance type is not `hba`, with an "Advance type / component" column. This fits the fixed three-input builder contract and the closed registry (no dynamic report kinds). HBA keeps its dedicated schedule.

Planned test change: replace the old assertion that the generic schedule *equals* HBA (built with `advance_type="hba"`) with a guard — the combined schedule never contains HBA rows, and combined total + HBA total = posted `loan_installment_recovery` external recoveries.

**Status: superseded.** The product went the other way: **per-type** schedules, not one combined sheet. `AdvanceScheduleBuilder` is parameterized by advance type, and the GPF advance, festival, motor car, and motorcycle schedules are registered as their own report kinds inside the 18-sheet product pack (see the [report catalog](report-catalog.md)). A generic `advance_schedule` (advance type "other") and a variant-driven `component_schedule` are registered outside the pack. Because no combined schedule exists, the planned guard test was not needed; the HBA-equivalence assertion still lives in `test_recovery_reports.py` and now checks that the parameterized builder with `advance_type="hba"` matches the dedicated HBA schedule.

## Phase F — Run-level bill metadata (design, then build)

Plan: three tiers, not org-wide `ReportConfiguration` (which is non-versioned and org-scoped; Bill/Token/Voucher are document-level per the MTR-19 Face sheet):

- **Organization defaults** (`ReportConfiguration`): DDO code, default head-of-account fields.
- **Run snapshot**: Bill No., Demand No., resolved accounting heads — captured at or before posting.
- **Treasury-submission record** (future): Token No., Voucher No., dates — assigned after submission.

First release: the Face renders org defaults plus the run snapshot; Token/Voucher render blank. A short design note (where Bill No. lives on the run, who sets it) was to precede the build.

**Status: partly done.** The first two tiers exist. `PayrollRun.report_metadata` (JSONB, validated by `PayrollRunReportMetadata`) holds run-level fields: bill number and date, payment date, demand number, major/sub/detailed heads, bank-advice number and date, and approval-note number and date. Org defaults (DDO code, treasury code, head-of-account) travel in the snapshot `report_profile`. The Treasury Face `v2` renders a bill header from both. The third tier — Token No. and Voucher No. after treasury submission — is still not modeled; those fields render blank.

## Phase G — Single-workbook consolidated export (separate design review)

Plan: `consolidated_xlsx` already existed as per-report workbooks zipped in `report_generation.py`. A single multi-sheet workbook would be an **alternate consolidated artifact format** on that path — not a registered report builder. The product allowlist and the reference workbook's sheet count differed at the time (13 vs 18, the extra sheets being legacy forms). Keep this as its own design decision; not in this change series.

**Status: not implemented, by design.** The consolidated export is still a ZIP of per-report `.xlsx` files (`execute_consolidated_xlsx`). The sheet-count gap has since closed: the product allowlist now has 18 sheets, because the advance schedules joined the pack. A true single multi-sheet workbook remains an open design decision.

---

## Sequencing (as planned)

1. Phase A (snapshot metadata + fallback) — prerequisite.
2. Phase B (per-report template versions, retain `v1`).
3. Phase C (Pay Bill `v2` + full test set + PDF width check).
4. Phase D (fixture/seed corrections).
5. Phase E (combined non-HBA schedule + replaced guard test).
6. Phase F (run-level bill metadata design → build).
7. Phase G (separate review).

A+B+C was the core series; D and E could land on their own after A. In the shipped code, A, C, and D landed; B and E landed in changed form (global `v2` default; per-type schedules); F landed in part; G stayed open. Note one planned promise did not survive: `v1` behavior is no longer requestable for new builds (see Phase B).

## Out of scope (unchanged)

- Payslip layout changes (already line-driven).
- Visual fidelity to the workbook (merged headers, Marathi headings) — a template-version concern.
- Default-component bootstrap feature.
- Single-workbook consolidated export (Phase G placeholder only).
