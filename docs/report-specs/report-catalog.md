# Report catalog

This file covers the payroll report builders, the shared DTO contract, the reconciliation invariants, and template versioning for Accord Phase 0.

Related: [ADR 0010](../adr/0010-jobs-object-storage.md) (export artifacts, jobs, object storage), [ADR 0009](../adr/0009-audit-outbox.md) (audit + outbox), [ADR 0008](../adr/0008-command-workflow-idempotency.md) (command workflow / idempotency), [payroll-domain.md](../payroll-domain.md) (glossary, gross-to-net, remittance buckets).

---

## Purpose

This catalog defines every first-release payroll report. It lists the inputs each builder takes. It defines the single typed DTO each builder emits. It also sets the cross-report rules that keep all outputs in step. The outputs are: Pay Bill, treasury face, bank advice, payslips, GPF/NPS schedules, statutory schedules, recovery schedules, accommodation schedules, and the approval note. All must agree with the **posted** run snapshot.

Reports are **read models over posted immutable snapshots**. They are not a second calculation engine. They must never look up "current" master data.

---

## Core contract

### Builder inputs

Every report builder gets a `ReportContext` (`backend/app/reports/base.py`). Its identity contract is these three values:

| Parameter | Meaning |
| --- | --- |
| `organization_id` | Tenant scope (RLS / org GUC). |
| `posted_run_id` | Identifier of a **posted** payroll run (and thereby its pinned run version / snapshot). |
| `template_version` | Immutable template/layout version used for formatting and recorded on every artifact. |

The context also carries run metadata (`generated_at`, `engine_version`) and an optional `variant_key`. Only the generic `component_schedule` builder uses `variant_key`. There it names the component code to schedule.

Builders must reject draft runs, calculated-but-unposted runs, and reversed-without-replacement runs. The shared gate is `require_posted_run` in `backend/app/reports/posted_run.py`. That module also holds the shared posted-run loading helpers (result rows, money quantizing, period labels). Every report family uses them. Reports may be built only from posted, immutable state.

### Builder output

Each builder produces **exactly one typed DTO** for that report kind (`ReportDTO` in `base.py`). The DTO is the sole source of truth for presentation:

- **JSON preview** formatter consumes the DTO.
- **Excel** formatter consumes the **same** DTO.
- **PDF** formatter consumes the **same** DTO.

There is **no** separate data-fetching path per output format. Formatters may change columns, page breaks, and type styling. They must not query live tables for amounts, rates, signatories, or employee master fields.

### Snapshot-only reads

Report builders read **only** posted immutable data:

- Pay lines, component classifications, and totals come from the posted run version (`payroll_employee_results`, `payroll_result_lines`, run-version `totals`).
- For the register, payments, recovery, and approval-note families, display data comes from the **immutable report snapshot** (`payroll_report_snapshots`). It is written at posting from the calc-time `inputs_snapshot`. It holds the component catalog (code, name, display order, classification), employee identity (name, designation, PAN, PRAN, GPF account number, bank account), the report profile (DDO code, heads, signatories, bank advice recipient), recovery sources, and run metadata.
- The statutory and GPF/NPS schedule families resolve identity fields (name, PAN, account numbers) from the effective-dated employee versions active at period month-end. This is safe against posted data because versions are never edited in place — they are only superseded (ADR 0005).
- Rate and rule snapshots are captured at calculation time (see [ADR 0007](../adr/0007-payroll-run-calculation-model.md) and [payroll-domain.md](../payroll-domain.md)).

Builders **never** read live master data for amounts, rates, bank accounts, or remittance routing. If a field was not snapshotted, it is absent or null in the DTO. It is never backfilled from today. A posted run with no report snapshot fails with a clear error. It needs an explicit audited backfill first (`backend/app/reports/snapshots.py`).

### Artifact recording

Every generated file (preview payload reference, Excel, PDF) is an export artifact under [ADR 0010](../adr/0010-jobs-object-storage.md). Each artifact row records at least `organization_id`, `posted_run_id`, `report_kind`, `template_version`, content hash / storage key, and format. Downloads are audit-sensitive per [ADR 0009](../adr/0009-audit-outbox.md) / ADR 0010 (`artifact.download`). Live previews write a matching `report.preview` access event. Requests follow the command idempotency patterns in [ADR 0008](../adr/0008-command-workflow-idempotency.md).

---

## Catalog

The product surface is the 18-sheet allowlist `PRODUCT_REPORT_SHEETS` in `backend/app/reports/registry_setup.py`. Its order is stable. It drives ZIP entry order and how the catalog is shown. Do not invent a second list on the frontend.

| Report kind | Purpose | Output formats | Key totals to reconcile |
| --- | --- | --- | --- |
| **Payroll register — Pay Bill** | Primary bill register: earnings, employer contributions, deductions by classification, gross bill, and net payable for the posted run. Columns are catalog-driven: one column per snapshotted component, grouped by classification, plus aggregate columns. | JSON preview, Excel, PDF | `salary_earnings`, `employer_share`, gross adjustments, `gross_bill`, deduction buckets (AG / treasury / external), `net_payable`; component columns sum to each aggregate; line sum = header totals; builder fails on any mismatch with posted totals |
| **Payroll register — Treasury Face** | Treasury-facing face sheet / abstract of the same posted bill for treasury submission, with a bill header (Bill No., Demand No., heads, DDO code) from the snapshot. | JSON preview, Excel, PDF | Face totals = Pay Bill header totals for the same `posted_run_id`; treasury deduction aggregates match statutory schedules; builder fails if gross − deductions ≠ posted net |
| **Bank / RTGS advice** | Payment instruction list to credit employee bank accounts (RTGS/NEFT/salary credit). Carries full account numbers by design; artifact access control is the protection layer. | JSON preview, Excel, PDF | Sum of advice credit amounts = posted **disbursement** (**not** net payable); one row per payable employee bank credit on the snapshot |
| **Payslips** | Per-employee earnings and deduction statement for the posted period (PAN/PRAN masked). | JSON preview, Excel, PDF | Each payslip's lines and take-home = that employee's posted lines; run-level sum of payslip disbursements = posted disbursement |
| **Office approval note** | Maker/checker approval note with **signatory** blocks for office endorsement of the posted bill. | JSON preview, Excel, PDF | Bill totals on the note = Pay Bill / Treasury Face for the same run; signatory slots present (names/roles from snapshot or configured office block frozen for the artifact) |
| **GPF — Mumbai schedule** | Remittance schedule for **Mumbai** GPF jurisdiction only. | JSON preview, Excel, PDF | Schedule total = sum of posted Mumbai GPF employee subscriptions (and any Mumbai-routed GPF lines); **never** includes Nagpur rows |
| **GPF — Nagpur schedule** | Remittance schedule for **Nagpur** GPF jurisdiction only. | JSON preview, Excel, PDF | Schedule total = sum of posted Nagpur GPF lines; **never** merged with Mumbai into one schedule file |
| **NPS contribution schedule** | NPS/DCPS employee and employer contribution schedule keyed by PRAN. | JSON preview, Excel, PDF | Employee + employer NPS totals = posted NPS lines; **NPS excludes EPF** — never list EPF members or EPF amounts on this schedule |
| **Income Tax schedule** | TDS / income-tax withholding remittance schedule (full PAN where snapshotted, by design). | JSON preview, Excel, PDF | Schedule total = posted income-tax / TDS treasury deductions |
| **Professional Tax schedule** | State professional tax remittance schedule. | JSON preview, Excel, PDF | Schedule total = posted professional-tax treasury deductions |
| **GIS schedule** | Group Insurance Scheme premium / contribution schedule. | JSON preview, Excel, PDF | Schedule total = posted GIS treasury deductions |
| **HBA schedule** | House Building Advance installment recovery schedule. | JSON preview, Excel, PDF | Schedule total = posted HBA external recoveries; installment identity from snapshot |
| **GPF advance schedule** | GPF advance installment recoveries for the run (generic layout). | JSON preview, Excel, PDF | Schedule total = posted `GPF_ADVANCE_INSTALLMENT` external recoveries |
| **Motor car advance schedule** | Motor car advance installment recoveries (generic layout). | JSON preview, Excel, PDF | Schedule total = posted `MOTOR_CAR_ADVANCE_INSTALLMENT` external recoveries |
| **Motorcycle advance schedule** | Motorcycle advance installment recoveries (generic layout). | JSON preview, Excel, PDF | Schedule total = posted `MOTORCYCLE_ADVANCE_INSTALLMENT` external recoveries |
| **Festival advance schedule** | Festival advance installment recoveries (generic layout). | JSON preview, Excel, PDF | Schedule total = posted `FESTIVAL_ADVANCE_INSTALLMENT` external recoveries |
| **Accommodation — Mumbai** | Mumbai government-quarters schedule: **actual** license-fee / HRA-recovery amounts plus separate informational foregone-HRA. | JSON preview, Excel, PDF | Actual recovery total = posted license-fee recoveries for Mumbai allotments; informational foregone-HRA listed separately and **never summed** into the same total as actual recovery |
| **Accommodation — Worli** | Worli government-quarters schedule with the same actual-vs-informational split. | JSON preview, Excel, PDF | Same rules as Mumbai for Worli allotments; Mumbai and Worli schedules remain separate artifacts |

Notes on catalog rows:

- **Pay Bill** and **Treasury Face** are both register outputs over the same posted snapshot. They differ in layout and treasury framing, not in source totals.
- **GPF Mumbai** and **GPF Nagpur** are **separate** report kinds and separate artifacts. Operators must not get a single combined GPF file in first release.
- **NPS** is never mixed with **EPF**. EPF amounts appear on Pay Bill / payslip / employer-share lines as defined in [payroll-domain.md](../payroll-domain.md). They do not appear on the NPS contribution schedule. A dedicated EPF schedule is out of scope this release.
- **Accommodation** reports keep **actual license-fee recovery** totals in a different DTO field (and printed total) from **informational / notional foregone HRA**. These are two kinds of money. Never add them up as if they were the same thing.
- The advance schedules share one builder in `backend/app/reports/families/recovery.py`, keyed by advance type. Two more entries are registered but sit **outside** the product pack: `advance_schedule` (advance type "other") and the variant-driven `component_schedule`.

---

## Cross-report reconciliation

These invariants must hold for any set of artifacts built against the same `(organization_id, posted_run_id)`. A failure is a product defect, not a "format difference."

### GPF jurisdictions

```text
GPF_Mumbai_schedule_total + GPF_Nagpur_schedule_total = total_GPF_elsewhere
```

Here `total_GPF_elsewhere` is the combined GPF subscription total on the Pay Bill / employee AG_deduction aggregates for the same posted run. No third "other GPF" bucket may be dropped in silence. If a new jurisdiction appears, it needs its own schedule row in this catalog before it can feed the identity.

### Bank / RTGS vs disbursement

```text
sum(bank_rtgs_advice.credit_amount) = posted_run.disbursement
posted_run.disbursement = posted_run.net_payable + posted_run.offbill_employer_remittance
```

The advice reconciles to **disbursement**, *not* to `net_payable`. Off-bill NPS employer is deducted from the treasury-face net with no matching gross addition. So the two figures differ by exactly that amount. They **must never be asserted equal** (department sign-off 18 Jul 2026; see [payroll-domain.md](../payroll-domain.md) "Resolved"). The bank advice builder runs this check at build time and fails on any mismatch.

Every employee credit on the advice comes from the posted disbursement line and the snapshotted bank account. Employees with zero disbursement get no credit row.

### Payslips vs posted employee lines

Payslip DTOs are a projection of posted employee lines:

- Line by line, the component codes, classifications, and amounts match the posted run version for that employee.
- Per-employee take-home (`disbursement`) on the payslip equals that employee's posted disbursement. The treasury-face `net_payable` shows as a separate line. The off-bill employer NPS share appears as its own labeled line when non-zero.
- The sum of payslip disbursements equals the run-level posted disbursement.

### NPS and EPF separation

- The NPS contribution schedule includes **only** NPS/DCPS lines (employee and employer as defined on the snapshot).
- EPF employee and employer amounts are tracked on register / payslip / employer-share paths, on their own.
- The Pay Bill (and any register lines that reference both) must **sum correctly**: NPS totals feed NPS-labeled lines; EPF totals feed EPF-labeled lines; neither pads the other.

### Amount in words

Wherever an artifact prints an amount in words (approval note, bank advice, treasury face, etc.):

- Words are always generated by code from the numeric amount on the DTO (`backend/app/reports/amount_in_words.py`).
- Words are **never** typed, stored, or edited as a free string that could drift from the number.

### Rates

- No hardcoded statutory or allowance rates in report builders or templates.
- Rates shown, or used for display breakouts, come from the **rate snapshot at calculation time** pinned on the posted run version.
- Template version controls layout only. It does not embed business rates.

### Accommodation actual vs notional

For Mumbai and Worli accommodation schedules:

```text
actual_hra_recovery_total  ≠  informational_foregone_hra_total  (as kinds)
actual_hra_recovery_total + informational_foregone_hra_total  must not be printed as "total HRA"
```

Only actual recoveries affect net pay and remittance; foregone HRA remains informational.

---

## Template versioning

- Every export artifact records `template_version` (ADR 0010 `export_artifacts`).
- New builds support **v2 only** (`SUPPORTED_TEMPLATE_VERSIONS` in `backend/app/services/report_generation.py`); v2 is also the default. The v2 layouts read the immutable report snapshot. Artifacts finalized under older versions stay downloadable. Requests for versions outside the supported set are rejected.
- Building the same report again for the same posted run with a newer template makes a new artifact row. Old downloads stay tied to the template version used when that artifact was created.
- JSON preview, Excel, and PDF for one job share one DTO and one `template_version`. The consolidated ZIP records a pack version of the form `{base_version}+{manifest_hash}`.
- Template changes are versioned. Silent in-place edits of a shipped template id are forbidden.

---

## First-release scope and exclusions

First release ships **provisional / generic** formats for the catalog rows above only.

The named legacy / specialized **form layouts** are **NOT** in first release. Generic-layout schedules now cover the advance recoveries beneath them. The legacy printed forms wait for a later template pack:

| Legacy form | Status |
| --- | --- |
| **GPF-IV** | Legacy form layout — not in first release; the generic **GPF advance schedule** covers GPF advance recoveries |
| **Motor car advance** form | Legacy form layout — not in first release; the generic **motor car advance schedule** covers these recoveries |
| **Motorcycle advance** form | Legacy form layout — not in first release; the generic **motorcycle advance schedule** covers these recoveries |
| **Festival advance** form | Legacy form layout — not in first release; the generic **festival advance schedule** covers these recoveries |

Non-HBA installment recoveries with advance type "other" use the registered `advance_schedule` builder, which sits outside the product pack.

---

## Generation flow (normative sketch)

1. The caller sends a generate-report command with `(organization_id, posted_run_id, report_kind, template_version, formats[])` under ADR 0008 idempotency. A live JSON preview path exists for any registered report kind. It writes a `report.preview` audit event.
2. The handler checks that the run is posted and readable in org scope, and that the template version is supported.
3. The report builder loads **only** posted snapshot data and emits one typed DTO.
4. Each requested format runs a pure formatter over that DTO.
5. Artifacts are stored and indexed per ADR 0010 with `template_version` on every row. If a finalized artifact already exists for the same run, kind, version, and format, it is reused. No rebuild happens.
6. Audit/outbox side effects follow ADR 0009 (including sensitive download auditing).

A consolidated export job (`consolidated_xlsx`) builds all 18 product sheets as Excel workbooks and stores them as one ZIP artifact.

---

## Open follow-ups

- Exact DTO field schemas per report kind. Today all kinds share the generic tabular `ReportDTO` / `TableSection` shape in `backend/app/reports/base.py`. Per-kind type specs can land under `docs/report-specs/` as needed.
- Treasury-submission fields (Token No., Voucher No.) are not yet modeled on the run. The bill header renders what the snapshot and run metadata provide.
- A single multi-sheet consolidated workbook (instead of the current ZIP of per-report workbooks) remains a separate design decision.

Resolved since the first draft of this catalog:

- Signatory source of truth for the office approval note: the `report_profile` block of the immutable report snapshot. The org-level `ReportConfiguration` "signatories" entry is the legacy source.
- Treasury Face is its own builder and DTO over the same posted lines. It is not a strict subset layout of Pay Bill. Both must reconcile to the same posted totals.
- Job-based async builds (ADR 0010) and live preview both exist. Preview is not limited to the product allowlist.
