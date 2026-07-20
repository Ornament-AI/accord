# Payroll domain glossary and contracts

This is the domain contract for Accord payroll. It covers Indian local-government and public-works staff who draw a regular monthly salary. All money is an exact decimal; the money and rounding rules live in [ADR 0006](adr/0006-money-decimal-rounding.md). The run calculation model lives in [ADR 0007](adr/0007-payroll-run-calculation-model.md). Effective-dated master data lives in [ADR 0005](adr/0005-effective-dated-master-data.md).

If you are new to this domain, read the glossary first. It defines each term once. Later sections use the short names.

---

## GLOSSARY

### Statutory funds, tax, insurance, and recoveries

| Term | Definition (government-payroll meaning) |
| --- | --- |
| **GPF (General Provident Fund)** | Mandatory / scheme provident fund for eligible government employees under Accountant General (AG) accounting. The employee subscription is an **AG_deduction**. Remittance and account administration vary by jurisdiction. This product tracks at least **Mumbai** and **Nagpur** GPF jurisdictions as separate remittance buckets (same fund family, different AG/office routing). |
| **NPS (National Pension System) / DCPS** | Defined-contribution pension scheme, including state DCPS variants treated under the same contribution model. The employee contribution is deducted from pay. The employer contribution is a matching scheme share, usually remitted together with the employee share. Contributions are identified by **PRAN**. Classification: employee side is an **AG_deduction** (or the statutory remittance path in jurisdiction config); employer side is **off-bill** — it is never added to the gross bill and is tracked as a separate employer remittance (see the Resolved section). |
| **Employer contribution** | Amount the employer owes into a statutory scheme (NPS/DCPS employer share, EPF employer share, etc.) for the employee for the period. When a contribution is part of the bill (EPF), it is added as an **employer_contribution** component and then transferred out, so it does not inflate **net payable**. |
| **Employee contribution** | Amount deducted from the employee's pay toward a statutory scheme (GPF subscription, NPS/DCPS employee share, EPF employee share). It reduces net pay and is remitted to the scheme authority. |
| **EPF** | Employees' Provident Fund (where it applies to covered staff). It has both employee and employer contribution legs. The employer EPF share is the narrow **employer share** aggregate used in the Proven June 2026 invariants. |
| **Income tax (TDS — Tax Deducted at Source)** | Income-tax withholding computed or instructed for the payroll period and remitted via treasury. Classified as **treasury_deduction**. |
| **Professional tax** | State professional tax deducted from salary and remitted via treasury. Classified as **treasury_deduction**. |
| **GIS (Group Insurance Scheme)** | Group insurance premium / contribution deducted from pay and remitted via treasury (or a configured remittance path). Classified as **treasury_deduction**. |
| **HBA (House Building Advance)** | Government house-building advance, recovered by installment from salary. Typically an **external_recovery** (or the AG path if the jurisdiction remits via AG — config decides the remittance bucket; economically it is a loan recovery). |
| **Other advances / loans by installment** | Non-HBA advances or loans recovered in fixed or scheduled installments from monthly pay (GPF advance, festival advance, motor car, motorcycle, other departmental advances). Classified as **external_recovery** unless a specific remittance path says otherwise. Interest amortization is **not** auto-computed (see Unproven behaviors). |
| **Government quarters / accommodation** | Allotment of government residential accommodation to an employee. An active allotment drives license-fee recovery and may suppress payment of HRA (see informational/foregone HRA). |
| **License-fee recovery** | **Actual** monetary recovery from salary for occupying government quarters. This is a real deduction that reduces net pay. It must be stored and reported separately from informational/foregone HRA. |
| **Informational / foregone HRA** | House Rent Allowance the employee would have received without government quarters. It is shown **for information only** and is **not paid**. It must never be mixed into license-fee recovery, earnings paid, or net payable. It is a separate informational line. |

### Identity and account numbers

| Term | Definition |
| --- | --- |
| **Sevarth ID** | Employee's Sevarth (state HR/payroll) identifier, used as a business key for the person in government HR systems. It is a stable external identity, mapped to the internal employee id. |
| **PRAN** | Permanent Retirement Account Number for NPS/DCPS. Required to attribute NPS contributions. |
| **GPF account number** | Employee's GPF account number within the relevant GPF jurisdiction (Mumbai / Nagpur / other). |
| **EPF number** | Employee's EPF member / UAN-linked account identifier, where EPF applies. |
| **PAN** | Permanent Account Number; required for TDS reporting. |
| **Bank account(s)** | Employee salary-credit bank account(s), effective-dated (see ADR 0005). A pay run posts the credit to the account version active for that run's service period. |

### Pay component classifications

Every pay line has exactly one classification. The engine (`backend/app/domain/payroll/inputs.py`) accepts these seven values:

| Classification | Meaning |
| --- | --- |
| **earning** | Amount that forms part of salary earnings payable to the employee (basic, allowances actually paid, etc.). |
| **employer_contribution** | Employer statutory share added into the **gross bill** as an earning-like addition, then matched by a transfer-out deduction line so it does not remain in **net payable**. |
| **AG_deduction** | Accountant General deduction — amounts remitted to / through the AG (notably GPF, and statutory items configured for AG remittance). |
| **treasury_deduction** | Deduction remitted via treasury (income tax / TDS, professional tax, GIS). |
| **gross_adjustment** | Adjustment that affects gross bill construction without being a normal recurring earning (e.g., certain bill-level adjustments). Distinct from net-only recoveries. In the engine it is its own aggregate inside the gross bill. |
| **external_recovery** | Recovery remitted to an external lender / advance authority (HBA and other loan installment recoveries). |
| **informational** | Line kept for audit and display only (e.g., `FOREGONE_HRA`). It contributes to **no** money aggregate. A line can also carry `informational=True` or `excluded_from_totals=True` flags with the same effect. |

### Payroll process terms

| Term | Definition |
| --- | --- |
| **Payroll period** | The calendar service month (or defined pay calendar period) being paid, e.g., June 2026. Aggregate: `payroll_periods` (ADR 0007). |
| **Pay run** | One execution of payroll against a payroll period for an organization / bill scope. Aggregate: `payroll_runs`. |
| **Run version** | Immutable snapshot produced by one calculation execution of a pay run (`payroll_run_versions`). Posted runs pin exact source version ids (ADR 0005, ADR 0007). |
| **Monthly exception / override** | Draft, mutable input for a specific period that overrides or supplements normal recurring calculation (with reason, service period, optimistic-concurrency version). |
| **Recurring instruction** | Effective-dated standing instruction for a deduction, contribution, or fixed amount that applies across periods until superseded. |
| **Effective-dated version** | Immutable version row with a validity period; "as of date D" resolves to at most one active version per business key (ADR 0005). |
| **Posting** | Irreversible (except via formal reversal) commitment of an approved run version to books / remittance outputs; freezes referenced master versions for audit. |
| **Reversal** | Formal counter-document / counter-run that negates a posted run's effects without mutating the original posted version. |
| **Maker / checker** | Dual-control workflow: one user prepares (maker), another reviews and approves (checker). Maps to submit / approve transitions (ADR 0007 workflow enumeration). |
| **Gross bill** | Bill total = salary earnings + employer share (in bill) + gross adjustments. See Gross-to-net identity. |
| **Net payable** | The treasury-face / bill amount: gross bill minus all deductions, including employer-transfer lines. It is **not** the employee's take-home; see **disbursement**. |
| **Disbursement** | What the employee actually receives as a bank credit: `net_payable + offbill_employer_remittance`. Reconciled separately from net payable (see the Resolved section). |
| **Employer share** | Aggregate of **employer_contribution** amounts included in the gross bill for the run. In the Proven June 2026 invariants the labeled **employer share** equals **EPF employer** only; NPS employer is off-bill (see the Resolved section). |

---

## Gross-to-net identity

These identities are **audit checks that must always hold**. All amounts are exact decimals (ADR 0006). The engine (`backend/app/domain/payroll/engine.py`) builds them in by construction. `validation.py` then re-checks them for each employee.

### Primary bill construction

```text
salary_earnings + employer_share + gross_adjustments = gross_bill
```

Where:

- `salary_earnings` is the sum of `earning` lines.
- `employer_share` is the sum of `employer_contribution` lines that sit in the bill. Reports call this narrow total "employer share".
- `gross_adjustments` is the sum of `gross_adjustment` lines. The engine keeps this as its own total inside the gross bill. It does not fold it into salary earnings. The June 2026 fixture has no such lines, so there the gross bill is just earnings plus employer share.

### Net payable (operational form)

Here **total deductions** includes **both**:

1. **Employee-side deductions** — GPF, NPS/EPF employee shares, income tax, professional tax, GIS, HBA, license fee, and other recoveries.
2. **Employer-transfer lines** — lines that move employer money back out of the employee's net. This includes the off-bill NPS employer amount.

Then:

```text
gross_bill − total_deductions = net_payable
```

In the engine, total deductions is the sum of three buckets: `AG_deduction + treasury_deduction + external_recovery`.

### Equivalent expanded form

Let `employee_deductions` be total deductions **without** the employer-transfer lines. Let `employer_transfer` be the sum of those transfer lines. Then:

```text
gross_bill − employee_deductions = net_payable + employer_transfer
```

which rearranges to the same net:

```text
net_payable = gross_bill − employee_deductions − employer_transfer
```

### Employer contribution ↔ transfer-out pairing identity

Every `employer_contribution` addition that enters `gross_bill` **must** have a matching transfer-out deduction line (same scheme, same employee, same run version):

```text
sum(employer_contribution additions in gross_bill)
  = sum(paired employer transfer-out deduction lines for those additions)
```

This pairing rule covers **gross-bill additions only** (EPF in the June fixture). Do not assert it over the full employer-transfer total. NPS employer is off-bill (see the Resolved section). The engine enforces the paired case itself. A transfer line names its partner via `transfer_of`. The run fails if the partner is missing or the amounts differ. A transfer line with no partner is an **off-bill employer remittance** and feeds `offbill_employer_remittance`. Unpaired additions or unpaired transfer-outs are **defects**. They must fail the run or fail the checks.

Informational / foregone HRA sits **outside** these identities. It must not appear in `salary_earnings`, `gross_bill`, `total_deductions`, or `net_payable`.

### Classification ↔ calculator alignment

Calculator kinds that emit these lines are defined in [ADR 0007](adr/0007-payroll-run-calculation-model.md). The closed registry (`backend/app/domain/payroll/calculators.py`) has seven kinds: `fixed_recurring_amount`, `direct_monthly_amount`, `percentage_of_component_bases`, `employer_employee_contribution`, `loan_installment_recovery`, `accommodation_charge`, and `one_time_adjustment`. Classification says what a line **is**. Calculator kind says how its amount was **made**.

---

## Proven June 2026 invariants

A synthetic June 2026 fixture / test dataset **MUST** reproduce these figures **exactly** (INR, exact decimal; display scale per ADR 0006). These are exact checks, not rough targets.

| Aggregate | Amount (INR) | Notes |
| --- | --- | ---: |
| Salary earnings | 5,073,200 | |
| Employer share | 29,785 | EPF employer only (gross-bill); see resolution below |
| Gross bill | 5,102,985 | |
| Total deductions | 1,264,890 | Includes employer transfer |
| Net payable | 3,838,095 | Treasury-face net; employee disbursement is 3,991,038 (see resolution) |
| GPF | 280,000 | Mumbai 165,000 / Nagpur 115,000 |
| Employer transfer | 182,728 | |
| Employee contribution | 139,030 | |
| HBA | 72,723 | |
| Income tax | 550,700 | |
| GIS | 22,440 | |
| Accommodation actual recovery | 11,669 | Mumbai 10,419 / Worli 1,250 |
| Professional tax | 5,600 | |
| NPS employer / employee | 152,943 / 109,245 | |
| EPF employer / employee | 29,785 / 29,785 | |

### Internal consistency checks (proven)

| Check | Expression | Result |
| --- | --- | --- |
| Gross bill from earnings + employer share | 5,073,200 + 29,785 | **5,102,985** ✓ |
| Net from gross − total deductions | 5,102,985 − 1,264,890 | **3,838,095** ✓ |
| GPF jurisdictions | 165,000 + 115,000 | **280,000** ✓ |
| Accommodation locations | 10,419 + 1,250 | **11,669** ✓ |
| Employee contribution legs | NPS employee 109,245 + EPF employee 29,785 | **139,030** ✓ |
| Employer transfer legs | NPS employer 152,943 + EPF employer 29,785 | **182,728** ✓ |
| Deduction detail rollup | GPF + employer transfer + employee contribution + HBA + income tax + GIS + accommodation + professional tax | **1,264,890** ✓ (280,000 + 182,728 + 139,030 + 72,723 + 550,700 + 22,440 + 11,669 + 5,600) |
| Narrow employer share vs EPF employer | employer share 29,785 vs EPF employer 29,785 | **Equal** ✓ |

### Resolved — NPS employer treatment and "Net Payable" definition

**Status: RESOLVED.** The department signed off on 18 July 2026 (Finance/Payroll). The source of truth is the MSIDC *June 2026 Regular Staff* pay bill and its MTR-19 treasury face (the `Pay Bill` and ` Face ` sheets). Three earlier readings existed. The reference bill settles them.

Confirmed facts from the reference bill:

1. The **employer share** added into the gross bill is **EPF employer only** (29,785). `Pay Bill!L208 = 29,785`, and the treasury face builds `Gross Total = Total Pay + Employer Share` off exactly that cell.
2. **NPS/DCPS employer (152,943) is off-bill.** It is **never** added to the gross bill. It appears only on the deduction side (treasury-face line 47, `8342 DCPS`) and is remitted on its own.
3. **Employer transfer** (182,728 = NPS employer 152,943 + EPF employer 29,785) is a **wider bucket** than gross-bill `employer_contribution`. Only the EPF leg (29,785) has a paired gross-bill addition.

Resolution (locked as engine behavior):

- The pairing identity `sum(employer_contribution in gross_bill) = sum(paired transfer-outs)` applies to **gross-bill lines only** — EPF in this fixture (29,785 = 29,785). Do **not** assert it over the full employer-transfer total. NPS employer is tracked as its own **off-bill employer remittance** bucket. It reconciles to the NPS contribution schedule. It is never paired to a gross addition.
- **"Net Payable" (3,838,095) is the treasury-face / bill figure**: `gross_bill − total_deductions`, where total deductions include NPS employer.
- **Employee disbursement is a separate figure. It is NOT asserted equal to Net Payable.** Bank/RTGS advice and payslip nets reconcile to disbursement (`salary_earnings − employee-side deductions = 5,073,200 − 1,082,162 = 3,991,038`). Disbursement exceeds Net Payable by exactly the off-bill NPS employer amount (3,991,038 − 3,838,095 = 152,943). The two totals are checked on their own, one by one.

The code implements this as `offbill_employer_remittance` and `disbursement` on the calculation result (`backend/app/domain/payroll/results.py`) and the posted snapshot (`payroll_employee_results`, run-version `totals`). Bank/RTGS advice and payslip take-home reconcile to `disbursement`. The Pay Bill register, treasury face, and approval note keep reporting `net_payable`. `fixtures/sanitized/june-2026/expected_totals.json` records both figures (`bank_rtgs_advice_sum` / `payslip_nets_sum` = 3,991,038).

Run `./scripts/verify-disbursement.sh` to check the whole identity end to end.

---

## Unproven behaviors

The behaviors below are **deferred** until historical workbooks arrive. Until then, enter them only as **approved one-time lines** (manual / exception inputs). The engine must **not** compute them on its own:

| Deferred behavior | Interim representation |
| --- | --- |
| Retroactive arrear reconstruction | Approved one-time adjustment lines for the period |
| Complex proration (mid-month join/leave/change beyond simple rules not yet proven) | Approved one-time lines |
| Loan interest amortization | Approved one-time recovery lines; installment principal may use `loan_installment_recovery` only when a fixed installment instruction exists |
| Annual tax projection | Approved TDS override / direct monthly amount; no annual projection engine yet |
| Legacy printed forms: GPF-IV, motor car advance, motorcycle advance, festival advance forms | The legacy **form layouts** are not built. Fixed-installment **recovery** for GPF advance, festival, motor car, and motorcycle advances is now a typed engine path (`loan_installment_recovery` from advance accounts), and generic-format schedules ship for these types (see [report catalog](report-specs/report-catalog.md)). Interest math stays manual. |

When workbooks prove a behavior, promote it to a typed calculator (ADR 0007) and effective-dated config (ADR 0005). Do not grow a user-authored formula DSL.
