# Sanitized June 2026 golden fixture

## Provenance

This directory is a **fully synthetic**, structure-preserving golden payroll fixture for Accord Phase 4 calculation correctness (Gate F).

- No real employee PII is present or derivable.
- Amounts are invented to satisfy the documented **Proven June 2026 invariants** in `docs/payroll-domain.md` exactly (whole INR rupees, no paise).
- Identity fields use obviously fake namespaces documented below.
- This fixture is the golden source that `backend/tests/calculations/test_june_2026_totals.py` will consume in a later phase.

> **WARNING — Gate F golden source**
>
> Do **not** silently alter aggregates, deduction composition, or the NPS/EPF employer asymmetry without first updating the Proven June 2026 invariants table in `docs/payroll-domain.md` and obtaining finance sign-off on any open-question change. Changing this fixture without updating that table breaks Gate F.

## Files

| File | Role |
| --- | --- |
| `organization.json` | Synthetic org, offices (Mumbai / Nagpur / Worli), pay unit, maker/checker/approving-officer signatories |
| `components.json` | Pay component catalog with classifications |
| `employees.json` | Synthetic identity, regime, retirement accounts, bank, PT liability, accommodation |
| `pay.json` | Per-employee component lines for period `2026-06` with per-employee totals |
| `expected_totals.json` | Fixture-wide aggregates + `report_reconciliation` targets |
| `validate.py` | Standalone stdlib Decimal validator (no third-party deps) |
| `README.md` | This document |

## Money representation

All amounts are **whole INR rupees** encoded as integer strings (e.g. `"12345"`). There are no paise/fractional amounts and no floats in this fixture. `validate.py` rejects any non-integer amount string.

## Synthetic identity conventions

| Field | Pattern | Example |
| --- | --- | --- |
| Name | `Employee A-NN` (zero-padded) | `Employee A-01` |
| Sevarth ID | `SYNTH` + 4 digits | `SYNTH0001` |
| PAN | `ZZZPZ####Z` (shape `[A-Z]{5}[0-9]{4}[A-Z]`; 4th char `P` = Person; `ZZZPZ` is not a real PAN prefix) | `ZZZPZ0001Z` |
| PRAN (NPS only) | 12-digit block starting `9000` | `900000000001` |
| GPF account (Mumbai) | `SYNGPF/MUM/####` | `SYNGPF/MUM/0001` |
| GPF account (Nagpur) | `SYNGPF/NGP/####` | `SYNGPF/NGP/0001` |
| EPF number (EPF only) | `SYNTEPF/######/UAN` | `SYNTEPF/000001/UAN` |
| Bank account | 14-digit, zero-prefixed sequential | `00000000000001` |
| IFSC | `SYNT` + 7 digits (`SYNT` is not a real bank prefix) | `SYNT0000001` |
| Signatories | `Employee S-NN` | `Employee S-01` |

Employees have **only** these identity fields — no address, phone, DOB, email, or Aadhaar.

## Headcount and regime breakdown

**32 employees** (within the ~28–34 design range):

| Regime | Count | Retirement lines |
| ---: | ---: | --- |
| `gpf_mumbai` | 9 | GPF subscription (Mumbai jurisdiction) |
| `gpf_nagpur` | 7 | GPF subscription (Nagpur jurisdiction) |
| `nps` | 12 | NPS employee + NPS employer transfer (PRAN-keyed) |
| `epf` | 4 | EPF employee + EPF employer contribution + EPF employer transfer |

Every employee is in **exactly one** regime. Regime exclusivity is enforced by `validate.py`.

Cross-cutting:

- Professional tax liable: **28** employees at **₹200** each (= ₹5,600). Employees A-29…A-32 are not liable.
- Accommodation Mumbai actual recovery: 3 employees (A-01…A-03).
- Accommodation Worli actual recovery: 1 employee (A-17).
- Those four have **no HRA earning**; informational `FOREGONE_HRA` is present and **excluded from all totals**.

## Classifications

Summed classifications used on pay lines:

- `earning`
- `employer_contribution` (EPF employer only in this fixture)
- `AG_deduction` (GPF, NPS employee, EPF employee, employer-transfer lines)
- `treasury_deduction` (income tax, professional tax, GIS)
- `external_recovery` (HBA)
- accommodation license-fee recovery is classified `external_recovery` (its ADR 0007 *calculator kind* remains `accommodation_charge`; classification and calculator kind are distinct axes)

Non-summed:

- `informational` / `excluded_from_totals: true` — `FOREGONE_HRA` only

`gross_adjustment` is defined in the catalog for completeness but unused in this period’s pay lines.

## Proven June 2026 invariants (exact)

| Aggregate | Amount (INR) |
| --- | ---: |
| Salary earnings | 5,073,200 |
| Employer share (EPF employer only) | 29,785 |
| Gross bill | 5,102,985 |
| Total deductions | 1,264,890 |
| Net payable | 3,838,095 |
| GPF total (Mumbai 165,000 + Nagpur 115,000) | 280,000 |
| Income tax | 550,700 |
| GIS | 22,440 |
| HBA | 72,723 |
| Professional tax (28 × 200) | 5,600 |
| Accommodation actual (Mumbai 10,419 + Worli 1,250) | 11,669 |
| NPS employee / employer | 109,245 / 152,943 |
| EPF employee / employer | 29,785 / 29,785 |
| Employer transfer (NPS employer + EPF employer) | 182,728 |
| Employee contribution (NPS employee + EPF employee) | 139,030 |

Identities:

```text
salary_earnings + employer_share = gross_bill
gross_bill − total_deductions = net_payable
```

## Critical asymmetry (do not “fix”)

Documented open question in `docs/payroll-domain.md`:

1. **EPF employer 29,785** is an `employer_contribution` line **inside gross bill**, paired 1:1 with `EPF_EMPLOYER_TRANSFER` 29,785.
2. **NPS employer 152,943** appears **only** as `NPS_EMPLOYER_TRANSFER` (deduction / employer-transfer). It is **not** added to gross bill as `employer_contribution`.
3. Therefore `employer_share` (29,785) ≠ full employer-transfer bucket (182,728).

`validate.py` asserts this asymmetry explicitly.

## Report reconciliation targets

See `expected_totals.json` → `report_reconciliation`:

- Pay Bill / Treasury Face header totals = primary aggregates above
- Bank/RTGS advice sum = net payable 3,838,095
- GPF Mumbai schedule = 165,000; GPF Nagpur schedule = 115,000
- NPS schedule employee/employer = 109,245 / 152,943 (**excludes EPF**)
- Income tax 550,700; Professional tax 5,600; GIS 22,440; HBA 72,723
- Accommodation Mumbai actual 10,419; Worli actual 1,250
- Sum of payslip nets = 3,838,095

## Validation

From the repository root:

```bash
python3 fixtures/sanitized/june-2026/validate.py
```

Must exit 0 and print a PASS summary. The script recomputes every aggregate from `pay.json` / `employees.json` using `decimal.Decimal`, compares against both hardcoded ground truth and `expected_totals.json`, checks per-employee nets, regime exclusivity, EPF pairing, NPS asymmetry, professional-tax liability, and synthetic identity patterns.
