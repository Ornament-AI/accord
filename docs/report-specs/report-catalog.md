# Report catalog

Payroll report builders, shared DTO contract, reconciliation invariants, and template versioning for Accord Phase 0.

Related: [ADR 0010](../adr/0010-jobs-object-storage.md) (export artifacts, jobs, object storage), [ADR 0009](../adr/0009-audit-outbox.md) (audit + outbox), [ADR 0008](../adr/0008-command-workflow-idempotency.md) (command workflow / idempotency), [payroll-domain.md](../payroll-domain.md) (glossary, gross-to-net, remittance buckets).

---

## Purpose

This catalog defines every first-release payroll report, the inputs each builder accepts, the single typed DTO each builder emits, and the cross-report reconciliation rules that keep Pay Bill, treasury face, bank advice, payslips, GPF/NPS schedules, statutory schedules, recoveries, and accommodation schedules consistent with the **posted** run snapshot.

Reports are **read models over posted immutable snapshots**. They are not a second calculation engine and must never re-resolve “current” master data.

---

## Core contract

### Builder inputs

Every report builder receives **exactly** these three values and nothing else as its identity/input contract:

| Parameter | Meaning |
| --- | --- |
| `organization_id` | Tenant scope (RLS / org GUC). |
| `posted_run_id` | Identifier of a **posted** payroll run (and thereby its pinned run version / snapshot). |
| `template_version` | Immutable template/layout version used for formatting and recorded on every artifact. |

Builders must reject draft, calculated-but-unposted, or reversed-without-replacement runs. Generation is authorized only against posted immutable state.

### Builder output

Each builder produces **exactly one typed DTO** for that report kind. The DTO is the sole source of truth for presentation:

- **JSON preview** formatter consumes the DTO.
- **Excel** formatter consumes the **same** DTO.
- **PDF** formatter consumes the **same** DTO.

There is **no** separate data-fetching path per output format. Formatters may rearrange columns, page breaks, and typography; they must not re-query live tables for amounts, rates, signatories, or employee master fields.

### Snapshot-only reads

Report builders read **only** posted immutable snapshots:

- Pay lines, component classifications, and totals from the posted run version.
- Employee identity and bank/GPF/NPS/EPF account fields **as frozen** on that run (pinned effective-dated version ids from calculation time).
- Rate and rule snapshots captured at calculation time (see [ADR 0007](../adr/0007-payroll-run-calculation-model.md) and [payroll-domain.md](../payroll-domain.md)).

Builders **never** read live/current master data for amounts, eligibility, rates, bank accounts, or remittance routing. If a field was not snapshotted, it is absent or null in the DTO — not backfilled from today.

### Artifact recording

Every generated file (preview payload reference, Excel, PDF) is an export artifact under [ADR 0010](../adr/0010-jobs-object-storage.md). Each artifact row records at least `organization_id`, `posted_run_id`, `report_kind`, `template_version`, content hash / storage key, and format. Downloads are audit-sensitive per [ADR 0009](../adr/0009-audit-outbox.md) / ADR 0010 (`artifact.download`). Generation requests follow command idempotency patterns in [ADR 0008](../adr/0008-command-workflow-idempotency.md).

---

## Catalog

| Report kind | Purpose | Output formats | Key totals to reconcile |
| --- | --- | --- | --- |
| **Payroll register — Pay Bill** | Primary bill register: earnings, employer contributions, deductions by classification, gross bill, and net payable for the posted run. | JSON preview, Excel, PDF | `salary_earnings`, `employer_share`, `gross_bill`, deduction buckets (AG / treasury / external), `net_payable`; line sum = header totals |
| **Payroll register — Treasury Face** | Treasury-facing face sheet / abstract of the same posted bill for treasury submission. | JSON preview, Excel, PDF | Face totals = Pay Bill header totals for the same `posted_run_id`; treasury deduction aggregates match statutory schedules |
| **Bank / RTGS advice** | Payment instruction list to credit employee bank accounts (RTGS/NEFT/salary credit). | JSON preview, Excel, PDF | Sum of advice credit amounts = posted **disbursement** (**not** net payable); one row per payable employee bank credit on the snapshot |
| **Payslips** | Per-employee earnings and deduction statement for the posted period. | JSON preview, Excel, PDF | Each payslip’s lines and take-home = that employee’s posted lines; run-level sum of payslip disbursements = posted disbursement |
| **Office approval note** | Maker/checker approval note with **signatory** blocks for office endorsement of the posted bill. | JSON preview, Excel, PDF | Bill totals on the note = Pay Bill / Treasury Face for the same run; signatory slots present (names/roles from snapshot or configured office block frozen for the artifact) |
| **GPF — Mumbai schedule** | Remittance schedule for **Mumbai** GPF jurisdiction only. | JSON preview, Excel, PDF | Schedule total = sum of posted Mumbai GPF employee subscriptions (and any Mumbai-routed GPF lines); **never** includes Nagpur rows |
| **GPF — Nagpur schedule** | Remittance schedule for **Nagpur** GPF jurisdiction only. | JSON preview, Excel, PDF | Schedule total = sum of posted Nagpur GPF lines; **never** merged with Mumbai into one schedule file |
| **NPS contribution schedule** | NPS/DCPS employee and employer contribution schedule keyed by PRAN. | JSON preview, Excel, PDF | Employee + employer NPS totals = posted NPS lines; **NPS excludes EPF** — never list EPF members or EPF amounts on this schedule |
| **Income Tax schedule** | TDS / income-tax withholding remittance schedule (PAN where snapshotted). | JSON preview, Excel, PDF | Schedule total = posted income-tax / TDS treasury deductions |
| **Professional Tax schedule** | State professional tax remittance schedule. | JSON preview, Excel, PDF | Schedule total = posted professional-tax treasury deductions |
| **GIS schedule** | Group Insurance Scheme premium / contribution schedule. | JSON preview, Excel, PDF | Schedule total = posted GIS treasury deductions |
| **HBA schedule** | House Building Advance installment recovery schedule. | JSON preview, Excel, PDF | Schedule total = posted HBA external recoveries; installment identity from snapshot |
| **Generic advance schedule** | Non-HBA advance / loan installment recoveries for the run. | JSON preview, Excel, PDF | Schedule total = posted generic (non-HBA) external recoveries; does not include HBA rows |
| **Accommodation — Mumbai** | Mumbai government-quarters schedule: **actual** license-fee / HRA-recovery amounts plus separate informational foregone-HRA. | JSON preview, Excel, PDF | Actual recovery total = posted license-fee recoveries for Mumbai allotments; informational foregone-HRA listed separately and **never summed** into the same total as actual recovery |
| **Accommodation — Worli** | Worli government-quarters schedule with the same actual-vs-informational split. | JSON preview, Excel, PDF | Same rules as Mumbai for Worli allotments; Mumbai and Worli schedules remain separate artifacts |

Notes on catalog rows:

- **Pay Bill** and **Treasury Face** are both payroll-register outputs over the same posted snapshot; they differ in layout and treasury presentation, not in source totals.
- **GPF Mumbai** and **GPF Nagpur** are **separate** report kinds and separate artifacts. Operators must not receive a single combined GPF file in first release.
- **NPS** is never conflated with **EPF**. EPF amounts appear on Pay Bill / payslip / employer-share lines as defined in [payroll-domain.md](../payroll-domain.md); they do not appear on the NPS contribution schedule.
- **Accommodation** reports keep **actual HRA-recovery / license-fee** totals in a different DTO field (and printed total) from **informational / notional foregone HRA**. Those two kinds of money must not be added together as if they were the same economic quantity.

---

## Cross-report reconciliation

These invariants are required for any successful multi-artifact generation against the same `(organization_id, posted_run_id)`. Failures are product defects, not “format differences.”

### GPF jurisdictions

```text
GPF_Mumbai_schedule_total + GPF_Nagpur_schedule_total = total_GPF_elsewhere
```

Where `total_GPF_elsewhere` is the consolidated GPF subscription total on Pay Bill / employee AG_deduction aggregates for the same posted run. No third “other GPF” bucket is silently omitted: if a future jurisdiction appears, it needs its own schedule row in this catalog before it can contribute to the identity.

### Bank / RTGS vs disbursement

```text
sum(bank_rtgs_advice.credit_amount) = posted_run.disbursement
posted_run.disbursement = posted_run.net_payable + posted_run.offbill_employer_remittance
```

The advice reconciles to **disbursement**, *not* to `net_payable`. Off-bill NPS employer is subtracted from the treasury-face net without a matching gross addition, so the two figures differ by exactly that amount and **must never be asserted equal** (department sign-off 18 Jul 2026; see [payroll-domain.md](../payroll-domain.md) “Resolved”).

Every payable employee credit on the advice comes from the posted disbursement line and snapshotted bank account. Zero-disbursement employees do not invent credits.

### Payslips vs posted employee lines

Payslip DTOs are a projection of posted employee lines:

- Line-by-line component codes, classifications, and amounts match the posted run version for that employee.
- Per-employee take-home (`disbursement`) on the payslip equals that employee’s posted disbursement; the treasury-face `net_payable` is shown as a separate line.
- Sum of payslip disbursements equals run-level posted disbursement.

### NPS and EPF separation

- NPS contribution schedule includes **only** NPS/DCPS lines (employee and employer as defined on the snapshot).
- EPF employee and employer amounts are tracked on register / payslip / employer-share paths separately.
- Consolidated Pay Bill (and any register lines that reference both) must **sum correctly**: NPS totals feed NPS-labeled consolidated lines; EPF totals feed EPF-labeled lines; neither is used to pad the other.

### Amount in words

Wherever an artifact prints an amount in words (approval note, bank advice, treasury face, etc.):

- Words are generated **programmatically** from the numeric amount on the DTO.
- Words are **never** typed, stored, or edited as an independent string that could drift from the number.

### Rates

- No hardcoded statutory or allowance rates in report builders or templates.
- Rates shown or used for display breakouts come from the **rate snapshot at calculation time** pinned on the posted run version.
- Template version controls layout only; it does not embed business rates.

### Accommodation actual vs notional

For Mumbai and Worli accommodation schedules:

```text
actual_hra_recovery_total  ≠  informational_foregone_hra_total  (as kinds)
actual_hra_recovery_total + informational_foregone_hra_total  must not be printed as “total HRA”
```

Only actual recoveries affect net pay and remittance; foregone HRA remains informational.

---

## Template versioning

- Every export artifact records `template_version` (ADR 0010 `export_artifacts`).
- Re-generating the same report for the same posted run with a newer template produces a new artifact row; historical downloads remain tied to the template version used when that artifact was created.
- JSON preview, Excel, and PDF for one generation job share one DTO and one `template_version`.
- Template changes are versioned; silent in-place mutation of a shipped template id is forbidden.

---

## First-release scope and provisional exclusions

First release ships **provisional / generic** formats for the catalog rows above only.

The following legacy / specialized forms are **NOT** in first release (explicitly excluded until a later template pack):

| Excluded form | Status |
| --- | --- |
| **GPF-IV** | Legacy — not in first release |
| **Motor car advance** schedule/form | Legacy / specialized — not in first release |
| **Motorcycle advance** schedule/form | Legacy / specialized — not in first release |
| **Festival advance** schedule/form | Legacy / specialized — not in first release |

Generic advance recovery for non-HBA installments that **are** present on the posted snapshot uses the **generic advance schedule** row in the catalog — not the excluded named legacy forms.

---

## Generation flow (normative sketch)

1. Caller invokes a generate-report command with `(organization_id, posted_run_id, report_kind, template_version, formats[])` under ADR 0008 idempotency.
2. Handler verifies the run is posted and readable in org scope.
3. Report builder loads **only** posted snapshot data and emits one typed DTO.
4. Each requested format runs a pure formatter over that DTO.
5. Artifacts are stored and indexed per ADR 0010 with `template_version` on every row.
6. Audit/outbox side effects follow ADR 0009 (including sensitive download auditing).

---

## Open follow-ups

- Exact DTO field schemas per report kind (separate type specs under `docs/report-specs/` as builders land).
- Signatory source of truth for office approval note (office config snapshot vs run-level endorsement block).
- Whether Treasury Face is a strict subset layout of Pay Bill or a distinct DTO type with shared totals interface.
- Prewarm / async generation via jobs (ADR 0010) versus synchronous preview for small runs.
