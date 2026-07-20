# Payroll domain glossary and contracts

Domain contract for Indian local-government / public-works **regular monthly salaried staff** payroll. Exact-decimal money rules are in [ADR 0006](adr/0006-money-decimal-rounding.md). Run calculation structure is in [ADR 0007](adr/0007-payroll-run-calculation-model.md). Effective-dated master data is in [ADR 0005](adr/0005-effective-dated-master-data.md).

---

## GLOSSARY

### Statutory funds, tax, insurance, and recoveries

| Term | Definition (government-payroll meaning) |
| --- | --- |
| **GPF (General Provident Fund)** | Mandatory / scheme provident fund for eligible government employees under Accountant General (AG) accounting. Employee subscription is an **AG_deduction**. Remittance and account administration are jurisdiction-specific; this product tracks at least **Mumbai** and **Nagpur** GPF jurisdictions as separate remittance buckets (same fund family, different AG/office routing). |
| **NPS (National Pension System) / DCPS** | Defined-contribution pension scheme (including state DCPS variants treated under the same contribution model). Employee contribution is deducted from pay; employer contribution is a matching / scheme employer share that is typically remitted with the employee share. Contributions are identified by **PRAN**. Classification: employee side as **AG_deduction** (or statutory remittance path per jurisdiction config); employer side as **employer_contribution** with a corresponding transfer-out line (see Gross-to-net identity). |
| **Employer contribution** | Amount the employer owes into a statutory scheme (NPS/DCPS employer share, EPF employer share, etc.) for the employee for the period. In bill construction it is added as an **employer_contribution** component and then transferred out so it does not inflate **net payable** to the employee. |
| **Employee contribution** | Amount deducted from the employee’s pay toward a statutory scheme (GPF subscription, NPS/DCPS employee share, EPF employee share). Reduces net pay; remitted to the scheme authority. |
| **EPF** | Employees’ Provident Fund (where applicable to covered staff). Has both employee and employer contribution legs. Employer EPF share is the narrow **employer share** aggregate used in the Proven June 2026 invariants unless a future fixture revises that definition. |
| **Income tax (TDS — Tax Deducted at Source)** | Income-tax withholding computed/instructed for the payroll period and remitted via treasury. Classified as **treasury_deduction**. |
| **Professional tax** | State professional tax deducted from salary and remitted via treasury. Classified as **treasury_deduction**. |
| **GIS (Group Insurance Scheme)** | Group insurance premium / contribution deducted from pay and remitted via treasury (or configured remittance path). Classified as **treasury_deduction**. |
| **HBA (House Building Advance)** | Government house-building advance; recovery is by installment from salary. Typically an **external_recovery** (or AG path if jurisdiction remits via AG—config decides remittance bucket; economically it is a loan recovery). |
| **Other advances / loans by installment** | Non-HBA advances or loans recovered in fixed or scheduled installments from monthly pay (e.g., other departmental advances). Classified as **external_recovery** unless a specific remittance path says otherwise. Complex interest amortization is **not** auto-computed in Phase 0 (see Unproven behaviors). |
| **Government quarters / accommodation** | Allotment of government residential accommodation to an employee. Presence of an active allotment drives license-fee recovery and may suppress payment of HRA (see informational/foregone HRA). |
| **License-fee recovery** | **Actual** monetary recovery from salary for occupying government quarters. This is a real deduction affecting net pay. Must be stored and reported separately from informational/foregone HRA. |
| **Informational / foregone HRA** | House Rent Allowance amount that would have been payable if the employee were not in government quarters, shown **for information only** and **not paid**. Must never be mixed into license-fee recovery, earnings paid, or net payable. Separate informational line / flag. |

### Identity and account numbers

| Term | Definition |
| --- | --- |
| **Sevarth ID** | Employee’s Sevarth (state HR/payroll) identifier used as a business key for the person in government HR systems. Stable external identity; mapped to the internal employee id. |
| **PRAN** | Permanent Retirement Account Number for NPS/DCPS. Required to attribute NPS contributions. |
| **GPF account number** | Employee’s GPF account number within the relevant GPF jurisdiction (Mumbai / Nagpur / other). |
| **EPF number** | Employee’s EPF member / UAN-linked account identifier where EPF applies. |
| **PAN** | Permanent Account Number; required for TDS reporting. |
| **Bank account(s)** | Employee salary-credit bank account(s), effective-dated (see ADR 0005). A pay run posts net payable to the account version active for that run’s service period. |

### Pay component classifications

Every pay line item has exactly one classification:

| Classification | Meaning |
| --- | --- |
| **earning** | Amount that forms part of salary earnings payable to the employee (basic, allowances actually paid, etc.). |
| **employer_contribution** | Employer statutory share added into the **gross bill** as an earning-like addition, then matched by a transfer-out deduction line so it does not remain in **net payable**. |
| **AG_deduction** | Accountant General deduction — amounts remitted to / through the AG (notably GPF, and NPS/statutory items configured for AG remittance). |
| **treasury_deduction** | Deduction remitted via treasury (e.g., income tax / TDS, professional tax, GIS). |
| **gross_adjustment** | Adjustment that affects gross bill construction without being a normal recurring earning (e.g., certain bill-level adjustments). Distinct from net-only recoveries. |
| **external_recovery** | Recovery remitted to an external lender / advance authority (e.g., HBA, other loan installment recoveries). |

### Payroll process terms

| Term | Definition |
| --- | --- |
| **Payroll period** | The calendar service month (or defined pay calendar period) being paid, e.g., June 2026. Aggregate: `payroll_periods` (ADR 0007). |
| **Pay run** | One execution of payroll against a payroll period for an organization / bill scope. Aggregate: `payroll_runs`. |
| **Run version** | Immutable snapshot produced by one calculation execution of a pay run (`payroll_run_versions`). Posted runs pin exact source version ids (ADR 0005, ADR 0007). |
| **Monthly exception / override** | Draft, mutable input for a specific period that overrides or supplements normal recurring calculation (with reason, service period, optimistic-concurrency version). |
| **Recurring instruction** | Effective-dated standing instruction for a deduction, contribution, or fixed amount that applies across periods until superseded. |
| **Effective-dated version** | Immutable version row with a validity period; “as of date D” resolves to at most one active version per business key (ADR 0005). |
| **Posting** | Irreversible (except via formal reversal) commitment of an approved run version to books / remittance outputs; freezes referenced master versions for audit. |
| **Reversal** | Formal counter-document / counter-run that negates a posted run’s effects without mutating the original posted version. |
| **Maker / checker** | Dual-control workflow: one user prepares (maker), another reviews/approves (checker). Maps to submit / approve transitions (ADR 0007 workflow enumeration). |
| **Gross bill** | Bill total = salary earnings + employer share (employer_contribution additions included in the bill). See Gross-to-net identity. |
| **Net payable** | Amount actually payable to the employee (salary credit), after all employee-side deductions and after employer-contribution transfer-out lines have removed employer shares from the employee’s net. |
| **Employer share** | Aggregate of **employer_contribution** amounts included in gross bill for the run. In the Proven June 2026 invariants, the labeled **employer share** equals **EPF employer** only; whether NPS employer belongs inside this narrow aggregate is an **open question** (see that section). |

---

## Gross-to-net identity

These identities are **auditable reconciliation contracts**. All amounts are exact decimals (ADR 0006).

### Primary bill construction

```text
salary_earnings + employer_share = gross_bill
```

Where:

- `salary_earnings` = sum of components classified **earning** (and any **gross_adjustment** items configured to enter salary earnings—product config must label which adjustments enter this sum).
- `employer_share` = sum of components classified **employer_contribution** that are included in the bill (the narrow aggregate named “employer share” on reports).

### Net payable (operational form)

When **total deductions** is defined to include **both**:

1. **Employee-side deductions** — GPF, NPS/EPF employee contributions, income tax, professional tax, GIS, HBA, license-fee recovery, other recoveries, etc.; and  
2. **Employer-contribution transfer-out lines** — pass-through deductions that reverse the employer_contribution additions out of the employee’s net;

then:

```text
gross_bill − total_deductions = net_payable
```

### Equivalent expanded form

Let `employee_deductions` be total deductions **excluding** employer transfer-out lines, and let `employer_transfer` be the sum of those transfer-out lines. Then:

```text
gross_bill − employee_deductions = net_payable + employer_transfer
```

which rearranges to the same operational net:

```text
net_payable = gross_bill − employee_deductions − employer_transfer
```

### Employer contribution ↔ transfer-out pairing identity

Every `employer_contribution` addition line that enters `gross_bill` **must** have a corresponding transfer-out deduction line (same scheme, same employee, same run version) such that:

```text
sum(employer_contribution additions in gross_bill)
  = sum(paired employer transfer-out deduction lines for those additions)
```

Unpaired additions or unpaired transfer-outs are **calculation defects** and must fail the run (or fail reconciliation checks).

Informational / foregone HRA is **outside** these identities: it must not appear in `salary_earnings`, `gross_bill`, `total_deductions`, or `net_payable`.

### Classification ↔ calculator alignment

Calculator kinds that typically emit these classifications are defined in [ADR 0007](adr/0007-payroll-run-calculation-model.md) (`employer_employee_contribution`, `loan_installment_recovery`, `accommodation_charge`, etc.). Classification is a property of the pay component / line; calculator kind is how the amount was produced.

---

## Proven June 2026 invariants

A synthetic June 2026 fixture / test dataset **MUST** reproduce these aggregate figures **exactly** (INR, exact decimal; display scale per ADR 0006). These are fixture-reproducing checks, not approximations.

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

### Resolved — NPS employer treatment and “Net Payable” definition

**Status: RESOLVED.** Department sign-off 18 July 2026 (Finance/Payroll). Source of
truth: MSIDC *June 2026 Regular Staff* pay bill and its MTR-19 treasury face
(`Pay Bill` and ` Face ` sheets). The three earlier candidate readings are settled as
follows.

Confirmed facts from the reference bill:

1. **Employer share** added into the gross bill is **EPF employer only** (29,785).
   `Pay Bill!L208 = 29,785`, and the treasury face builds
   `Gross Total = Total Pay + Employer Share` off exactly that cell.
2. **NPS/DCPS employer (152,943) is off-bill**: it is **never** added to the gross
   bill. It appears only on the remittance/deduction side (treasury-face line 47,
   `8342 DCPS`) and is remitted separately.
3. **Employer transfer** (182,728 = NPS employer 152,943 + EPF employer 29,785) is a
   **wider remittance bucket** than gross-bill `employer_contribution`. Only the EPF
   leg (29,785) has a paired gross-bill addition.

Resolution (lock these as engine behavior):

- The gross-bill pairing identity
  `sum(employer_contribution in gross_bill) = sum(paired transfer-outs)` applies to
  **gross-bill employer_contribution only** — EPF in this fixture (29,785 = 29,785). It
  must **not** be asserted over the full employer-transfer total. NPS employer is
  tracked as a distinct **off-bill employer remittance** bucket, reconciled to the NPS
  contribution schedule, and never paired to a gross addition.
- **“Net Payable” (3,838,095) is the treasury-face / bill figure**:
  `gross_bill − total_deductions`, where total deductions include NPS employer.
- **Employee disbursement is a separate figure and is NOT asserted equal to Net
  Payable.** Bank/RTGS advice and payslip nets reconcile to employee disbursement
  (`salary_earnings − employee-side deductions = 5,073,200 − 1,082,162 = 3,991,038`),
  which exceeds Net Payable by exactly the off-bill NPS employer amount
  (3,991,038 − 3,838,095 = 152,943). These two totals are reconciled independently.

Implemented as `offbill_employer_remittance` and `disbursement` on the calculation
result and the posted snapshot (`payroll_employee_results`, run-version `totals`).
Bank/RTGS advice and payslip take-home reconcile to `disbursement`; the Pay Bill
register, treasury face, and approval note continue to report `net_payable`.
`fixtures/sanitized/june-2026/expected_totals.json` records both
(`bank_rtgs_advice_sum` / `payslip_nets_sum` = 3,991,038).

Run `./scripts/verify-disbursement.sh` to check the whole identity end to end.

---

## Unproven behaviors

The following are **explicitly deferred** until historical workbooks arrive. Until then they must be represented only as **explicit approved one-time lines** (manual / exception inputs), **not** computed automatically by the engine:

| Deferred behavior | Interim representation |
| --- | --- |
| Retroactive arrear reconstruction | Approved one-time adjustment lines for the period |
| Complex proration (mid-month join/leave/change beyond simple rules not yet proven) | Approved one-time lines |
| Loan interest amortization | Approved one-time recovery lines; installment principal may use `loan_installment_recovery` only when a fixed installment instruction exists |
| Annual tax projection | Approved TDS override / direct monthly amount; no annual projection engine yet |
| Inactive templates: GPF-IV, motor car advance, motorcycle advance, festival advance | Out of scope for auto templates; if needed in a period, approved one-time lines only |

When workbooks prove a behavior, promote it to a typed calculator (ADR 0007) and effective-dated config (ADR 0005)—do not grow a user-authored formula DSL.
