# Canonical payroll export contract

## Purpose

Accord must be able to rebuild the MSIDC payroll workbook from saved payroll
facts. The June 2026 workbook is the layout reference. It is not a safe source
of formulas or defaults.

The source file has broken cells. It also has stale copy and spelling errors.
Accord therefore uses a **normalized 1:1 contract**:

- Keep the same report set, sheet order, grouped fields, row meaning, totals,
  print layout, and blank-versus-zero meaning.
- Recalculate all totals from posted facts.
- Replace broken `#REF!` and `#VALUE!` formulas.
- Use clear labels in new exports. Do not copy spelling errors into the domain.
- Never invent a missing employee, bank, retirement, or pay value.

The PII-free structure is checked in at
`fixtures/sanitized/june-2026/canonical_export_contract.json`. Rebuild it with
`scripts/extract_canonical_export_contract.py` when Finance accepts a new
canonical workbook.

## Version rule

The generic v2 reports remain valid historical artifacts. Canonical exports use
v3. A v3 request must never reuse a v2 artifact.

For v3, the full export is one `.xlsx` workbook. Its sheets are, in order:

1. `office tip`
2. `Bank Tip`
3. `PaySlip`
4. ` Face `
5. `Pay Bill`
6. `Income Tax`
7. `GPF-Nagpur`
8. `P.T.`
9. `GPF-Mumbai`
10. `GPF-IV`
11. `GIS`
12. `HBA Ad`
13. `Motor car Ad` (hidden)
14. `Motor cycale Ad (2)` (hidden; source name retained for compatibility)
15. `Pension Sub (2)`
16. `Festival` (hidden)
17. `WORLI`
18. `Mumbai`

The v2 ZIP is kept for old callers. It is not the canonical workbook.

The checked-in structural template contains layout only. It must not contain
names, account numbers, amounts, formulas, comments, hyperlinks, shared
strings, media, or external relationships. Rebuild it with
`scripts/build_canonical_schedule_template.py`; that command fails closed if a
payload is found.

## Data ownership

Each value has one owner. The export must not ask for the same fact in two
places.

### Organization export defaults

Set once under payroll export settings:

- legal and office names;
- address, CIN, phone, and website;
- DDO name and code;
- administrative department and department code;
- treasury code and head-of-account defaults;
- bank-advice recipient and address;
- Mumbai and Nagpur GPF remittance destinations, account codes, and authority
  text;
- NPS employee- and employer-contribution account-head narratives;
- salary letter reference prefix;
- fund source and plan status;
- maker, checker, approving officer, and final approver;
- optional footer text used by the organization template.

These values are copied into the calculation snapshot. If they change after a
run is calculated, the run must be calculated again to use the new values.

### Post catalog

The employee's designation post and its Pay Bill grouping post are separate
facts. This matters because one Pay Bill group may contain several
designations, and two distinct groups may print the same heading.

Set on each designation post:

- designation;
- class;

Set on each Pay Bill grouping post:

- the exact Pay Bill heading;
- sanctioned strength;
- vacant count;
- pay scale text;
- export order.

`vacant_count` cannot be greater than `sanctioned_strength`. Unknown values stay
blank. Strength, vacancy, and scale are entered only when that group prints
them; the June reference intentionally leaves some of them blank. Accord must
not derive vacancies from the current employee count.

### Employee record

Set on the employee and effective-dated versions:

- employee number and exact display name;
- posting, designation post, and Pay Bill grouping post;
- PAN;
- Sevarth ID, PRAN, pension account, GPF account and jurisdiction, or EPF number
  when known for the employee's retirement regime;
- basic pay and optional pay-matrix level;
- salary bank account, IFSC, bank name, and optional branch;
- optional payroll export remark.

Unknown source values stay `null`. Sevarth ID, birth date, joining date,
pay-matrix level, GPF jurisdiction, and bank branch must not be fabricated just
to make a form pass.

Account numbers are text. Leading zeroes are significant.

### Pay component catalog

Each component owns:

- code, label, classification, and display order;
- calculator and rate version;
- optional canonical Pay Bill column;
- optional schedule kind, title, and account head;
- employer-transfer pairing, when used.

The canonical column tells the Pay Bill where a component is shown. It does not
change calculation. More than one component may map to one canonical column.
Their posted order is kept as detail lines and their total feeds the column.

An amount-bearing component that has no canonical column is a readiness issue
for v3. It must not disappear from the export.

Each employee can print at most five nonzero component detail lines in one Pay
Bill column. Readiness blocks the export when a column would exceed that fixed
canonical employee block, so the renderer cannot truncate or overlap details.

### Employee payroll setup

Recurring items, advances, and accommodation hold long-lived employee facts.
Advance data owns the sanction reference and installment progress.
Accommodation data owns the location, quarters identity, address, charge
breakdown, and foregone HRA.

### Pay run

The monthly roster and run inputs own:

- included employees and their order;
- payable days;
- DA and HRA rates or approved overrides;
- DA difference;
- transport and other one-time values;
- an amount for an exception or one-time item;
- an amount or rate, never both, for an override (a rate can replace only an
  existing rate-based component);
- service-period start and end for arrears and differences;
- the reason or display remark for an override.

Run report details own:

- bill number, bill date, and payment date (all required for the canonical Pay
  Bill export);
- demand, major, sub, and detailed heads when they override organization
  defaults;
- bank-advice number and date;
- approval-note number and date;
- treasury token number and date;
- voucher number and date.

Run report details are copied into the posted report snapshot.

### Derived values

Accord derives these values. Users do not enter them again:

- DA and HRA calculated from the selected rate;
- employer and employee contribution amounts;
- gross salary;
- gross after recovery;
- grouped deductions;
- net amount payable;
- page and grand totals;
- statutory schedule totals;
- amount in words.

All money uses `Decimal`. A blank source value is not the same as an entered
zero. Reports may show either a blank or `0` based on that fact.

## Release acceptance

An export is complete only after the generated workbook passes the independent
validator:

```bash
backend/.venv/bin/python scripts/validate_canonical_export.py generated-v3.xlsx
```

The validator compares all 18 sheet names, order, visibility, used and print
ranges, merges, row and column dimensions, print settings, and manual page
breaks. It then recalculates a temporary copy with LibreOffice and requires
zero formula errors. The input file is never modified.

For the normalized 28-employee June acceptance case, the Pay Bill keeps page
summary blocks at rows 62:67, 129:134, and 197:202, with the grand block at
203:208. The validator also checks the 28 numbered columns, employee total
formulas, page rollups, and these approved totals:

- salary earnings: `5073200.00`;
- employer share: `29785.00`;
- gross bill: `5102985.00`;
- deductions: `1264890.00`;
- net payable: `3838095.00`.

The historical workbook is not expected to pass this validator: its broken
cached formulas are source defects that v3 repairs.

## Pay Bill layout

The canonical register has 28 numbered columns:

1. serial number;
2. employee name;
3. basic or grade pay;
4. DA and DA difference;
5. CLA;
6. HRA;
7. wash, child, and other allowance;
8. reimbursement and salary or increment difference;
9. extra conveyance and allowance;
10. TA, PTA, and honorarium;
11. gross salary;
12. employer share;
13. festival or overpayment recovery;
14. gross after recovery;
15. GPF account number;
16. GPF subscription, refund, and arrears;
17. pension employer share;
18. pension employee share;
19. advance recovery;
20. flood-affected advance;
21. income tax;
22. PLI, CGIS, MSI, or GIS;
23. HRR, service charge, and arrears;
24. professional tax and difference;
25. co-operative recovery;
26. total deductions;
27. net amount payable;
28. remarks.

Columns 15 through 20 sit under **Adjustable by AG**. Columns 21 through 26
sit under **Adjustable by Treasury**. Both groups sit under **Deductions**.

The workbook uses Pay Bill group rows. A group row shows its configured heading
and, when entered, sanctioned strength, vacancies, and pay scale. Employees
follow the group export order, then employee number. The actual employee
designation is printed inside the employee block and is never used as an
implicit group key.

The formulas are:

```text
gross salary = sum(columns 3 through 10)
gross after recovery = gross salary + employer share - recovery
total deductions = sum(columns 16 through 25)
net amount payable = gross after recovery - total deductions
```

Formula cells stay live in Excel. The builder also checks their expected values
against the immutable posted result before it writes the file.

### PDF reference

`Salary head for Accord.pdf` is a one-page print of the first four employee
blocks. It uses US letter paper in landscape. It proves that all 28 columns are
shown in one horizontal table; they are not split into unrelated column blocks.

The full v3 Pay Bill PDF applies that layout to all employees. It repeats the
grouped header on each page. It may use more pages than the sample. The stale
source footer path (`jan - 2025`) is not a payroll fact and is not hardcoded.
An organization may set footer copy in export settings.

## Readiness

Readiness is report-specific. It is not a single “profile complete” flag.

At minimum, v3 must report:

- missing organization identity and header fields;
- missing signatory name/designation pairs;
- incomplete bank records for employees in bank advice;
- missing PAN for income-tax rows;
- missing GPF or NPS identifiers for the matching schedules;
- missing Pay Bill group heading or export order, and invalid entered
  strength/vacancy pairs;
- posted components with no canonical Pay Bill column;
- missing jurisdiction-specific GPF remittance fields when that jurisdiction
  has activity;
- missing NPS account-head narratives when NPS activity exists;
- incomplete accommodation address or charge buckets, or buckets that do not
  reconcile to the posted recovery;
- incomplete run metadata pairs such as number without date;
- incomplete service-period pairs;
- source values that could not be parsed as money.

The UI must show who owns each issue and link to that screen. A report must not
silently omit an unresolved amount.

## Source workbook corrections

The June workbook has known faults:

- `Pay Bill!C172` contains text. The same employee block states basic pay of
  66,000. Import uses that block value and records the correction.
- Many totals then show `#VALUE!`. Accord recalculates them.
- PaySlip has deleted references and many `#REF!` cells. Accord rebuilds those
  formulas from posted facts.
- PaySlip prints employee emoluments and recoveries, not employer-contribution
  detail lines. Employer contributions remain on Pay Bill and their statutory
  schedules. **Amount Credited** uses posted disbursement, including any
  off-bill employer remittance, exactly as the normalized workbook requires.
- Some labels and footer paths are stale. They are template copy, not payroll
  data.

The approved normalized June values are:

| Check | Value |
| --- | ---: |
| Employees | 28 |
| Salary earnings | 5,073,200.00 |
| Employer share | 29,785.00 |
| Gross bill | 5,102,985.00 |
| Total deductions | 1,264,890.00 |
| Net payable | 3,838,095.00 |

These totals are the result of restoring `Pay Bill!C172` to 66,000 and letting
the workbook recalculate. The repair adds 93 to both gross and deductions, so
the net payable remains unchanged. They are not stale cached formula values.

These values differ from the fully synthetic 32-person calculation fixture.
Both fixtures are useful, but they prove different contracts.

## Acceptance checks

Do not compare raw `.xlsx` bytes. ZIP order and timestamps make byte hashes
fragile. Compare the normalized workbook model instead:

- exact sheet names, order, and hidden state;
- exact header labels and group merges;
- row and column order;
- formulas and their calculated meaning;
- number formats, widths, heights, and print settings;
- approved totals and cross-sheet reconciliation;
- no unexpected formula errors;
- PDF page size, orientation, repeated headers, readable text, and no clipping.

The real workbook acceptance test is optional in normal CI and uses
`ACCORD_CANONICAL_PAYBILL_XLSX`. CI uses only PII-free structure and synthetic
payroll data.
