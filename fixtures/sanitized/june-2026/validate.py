#!/usr/bin/env python3
"""Standalone validator for the sanitized June 2026 golden payroll fixture.

Stdlib only. Decimal-based arithmetic throughout. No floats.
Exit 0 on PASS; non-zero on any violation.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent

# Ground-truth hard requirements (INR whole rupees). Do not derive from expected_totals.json.
HARD = {
    "salary_earnings": Decimal("5073200"),
    "employer_share": Decimal("29785"),
    "gross_bill": Decimal("5102985"),
    "total_deductions": Decimal("1264890"),
    "net_payable": Decimal("3838095"),
    "offbill_employer_remittance": Decimal("152943"),
    "employee_disbursement": Decimal("3991038"),
    "gpf_total": Decimal("280000"),
    "gpf_mumbai": Decimal("165000"),
    "gpf_nagpur": Decimal("115000"),
    "income_tax": Decimal("550700"),
    "gis": Decimal("22440"),
    "hba": Decimal("72723"),
    "professional_tax": Decimal("5600"),
    "accommodation_total": Decimal("11669"),
    "accommodation_mumbai": Decimal("10419"),
    "accommodation_worli": Decimal("1250"),
    "nps_employee": Decimal("109245"),
    "nps_employer": Decimal("152943"),
    "epf_employee": Decimal("29785"),
    "epf_employer": Decimal("29785"),
    "employer_transfer": Decimal("182728"),
    "employee_contribution": Decimal("139030"),
}

PT_RATE = Decimal("200")
PT_LIABLE_COUNT = 28

NAME_RE = re.compile(r"^Employee A-\d{2}$")
PAN_RE = re.compile(r"^ZZZPZ\d{4}Z$")
# Full PAN shape [A-Z]{5}[0-9]{4}[A-Z] satisfied by ZZZPZ####Z; 5th char is P.
PAN_SHAPE_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
PRAN_RE = re.compile(r"^9000\d{8}$")
SEVARTH_RE = re.compile(r"^SYNTH\d{4}$")
BANK_RE = re.compile(r"^\d{14}$")
IFSC_RE = re.compile(r"^SYNT\d{7}$")
GPF_MUM_RE = re.compile(r"^SYNGPF/MUM/\d{4}$")
GPF_NGP_RE = re.compile(r"^SYNGPF/NGP/\d{4}$")
EPF_RE = re.compile(r"^SYNTEPF/\d{6}/UAN$")

SIGNATORY_NAME_RE = re.compile(r"^Employee S-\d{2}$")

DEDUCTION_CLASSIFICATIONS = {
    "AG_deduction",
    "treasury_deduction",
    "external_recovery",
    }

FAILURES: list[str] = []
PASSES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"FAIL: {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    PASSES.append(msg)
    print(f"PASS: {msg}")


def parse_amount(raw: object, context: str) -> Decimal:
    """Parse a whole-rupee amount string. Reject floats and non-integers."""
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        fail(f"{context}: amount must be str or int, got {type(raw).__name__}: {raw!r}")
        return Decimal("0")
    if isinstance(raw, int):
        # Allow ints in JSON only if they are whole; still prefer strings.
        text = str(raw)
    else:
        text = raw
    if isinstance(raw, str) and ("." in raw or "e" in raw.lower() or "E" in raw):
        fail(f"{context}: non-integer / float-like amount string rejected: {raw!r}")
        return Decimal("0")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        fail(f"{context}: cannot parse amount as Decimal: {raw!r}")
        return Decimal("0")
    if value != value.to_integral_value():
        fail(f"{context}: amount is not a whole rupee integer: {raw!r}")
        return Decimal("0")
    return value


def load_json(name: str) -> object:
    path = FIXTURE_DIR / name
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        ok(f"json.load succeeded for {name}")
        return data
    except FileNotFoundError:
        fail(f"missing file: {name}")
        return None
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {name}: {exc}")
        return None


def expect_eq(actual: Decimal, expected: Decimal, label: str) -> None:
    if actual != expected:
        fail(f"{label}: expected {expected}, actual {actual}, diff {actual - expected}")
    else:
        ok(f"{label} = {expected}")


def is_informational(line: dict) -> bool:
    return bool(line.get("informational") or line.get("excluded_from_totals"))


def is_deduction(line: dict) -> bool:
    if is_informational(line):
        return False
    if line.get("classification") in DEDUCTION_CLASSIFICATIONS:
        return True
    if line.get("employer_transfer"):
        return True
    return False


def main() -> int:
    print("=== Sanitized June 2026 fixture validator ===")
    print(f"fixture dir: {FIXTURE_DIR}")

    org = load_json("organization.json")
    components = load_json("components.json")
    employees_doc = load_json("employees.json")
    pay_doc = load_json("pay.json")
    expected_doc = load_json("expected_totals.json")

    if None in (org, components, employees_doc, pay_doc, expected_doc):
        print("\nABORT: could not load all fixture JSON files.")
        return 1

    assert isinstance(org, dict)
    assert isinstance(components, dict)
    assert isinstance(employees_doc, dict)
    assert isinstance(pay_doc, dict)
    assert isinstance(expected_doc, dict)

    employees = employees_doc.get("employees") or []
    pay_employees = pay_doc.get("employees") or []
    if not isinstance(employees, list) or not isinstance(pay_employees, list):
        fail("employees.json / pay.json must contain an employees array")
        return 1

    emp_by_id = {e["employee_id"]: e for e in employees if isinstance(e, dict)}
    pay_by_id = {p["employee_id"]: p for p in pay_employees if isinstance(p, dict)}

    # --- Hard identity arithmetic (hardcoded) ---
    expect_eq(
        HARD["salary_earnings"] + HARD["employer_share"],
        HARD["gross_bill"],
        "hard identity: salary_earnings + employer_share",
    )
    expect_eq(
        HARD["gross_bill"] - HARD["total_deductions"],
        HARD["net_payable"],
        "hard identity: gross_bill - total_deductions",
    )
    expect_eq(
        HARD["gpf_mumbai"] + HARD["gpf_nagpur"],
        HARD["gpf_total"],
        "hard identity: gpf jurisdictions",
    )
    expect_eq(
        HARD["accommodation_mumbai"] + HARD["accommodation_worli"],
        HARD["accommodation_total"],
        "hard identity: accommodation locations",
    )
    expect_eq(
        HARD["nps_employee"] + HARD["epf_employee"],
        HARD["employee_contribution"],
        "hard identity: employee contribution legs",
    )
    expect_eq(
        HARD["nps_employer"] + HARD["epf_employer"],
        HARD["employer_transfer"],
        "hard identity: employer transfer legs",
    )
    deduction_rollup = (
        HARD["gpf_total"]
        + HARD["employer_transfer"]
        + HARD["employee_contribution"]
        + HARD["hba"]
        + HARD["income_tax"]
        + HARD["gis"]
        + HARD["accommodation_total"]
        + HARD["professional_tax"]
    )
    expect_eq(deduction_rollup, HARD["total_deductions"], "hard identity: deduction rollup")

    # --- Recompute aggregates from pay.json ---
    salary_earnings = Decimal("0")
    employer_share = Decimal("0")
    total_deductions = Decimal("0")
    net_payable = Decimal("0")
    gpf_mumbai = Decimal("0")
    gpf_nagpur = Decimal("0")
    income_tax = Decimal("0")
    gis = Decimal("0")
    hba = Decimal("0")
    professional_tax = Decimal("0")
    pt_line_count = 0
    acc_mumbai = Decimal("0")
    acc_worli = Decimal("0")
    nps_employee = Decimal("0")
    nps_employer_transfer = Decimal("0")
    nps_employer_contrib = Decimal("0")
    epf_employee = Decimal("0")
    epf_employer_contrib = Decimal("0")
    epf_employer_transfer = Decimal("0")
    informational_sum = Decimal("0")
    foregone_in_earnings = Decimal("0")

    if set(emp_by_id) != set(pay_by_id):
        fail(
            "employee_id mismatch between employees.json and pay.json: "
            f"only_in_employees={sorted(set(emp_by_id) - set(pay_by_id))} "
            f"only_in_pay={sorted(set(pay_by_id) - set(emp_by_id))}"
        )

    for emp_id, pay in pay_by_id.items():
        emp = emp_by_id.get(emp_id)
        if emp is None:
            fail(f"{emp_id}: present in pay.json but missing from employees.json")
            continue

        lines = pay.get("lines") or []
        earn = Decimal("0")
        er_contrib = Decimal("0")
        ded = Decimal("0")

        for i, line in enumerate(lines):
            ctx = f"{emp_id} lines[{i}] {line.get('component_code')}"
            amount = parse_amount(line.get("amount"), ctx)
            classification = line.get("classification")
            code = line.get("component_code")

            if is_informational(line):
                informational_sum += amount
                if classification == "earning" or code in {
                    "BASIC",
                    "DA",
                    "HRA",
                    "TRANSPORT",
                    "OTHER_ALLOWANCE",
                }:
                    foregone_in_earnings += amount
                    fail(f"{ctx}: informational amount must not be classified as earning")
                continue

            if classification == "earning":
                earn += amount
                salary_earnings += amount
            elif classification == "employer_contribution":
                er_contrib += amount
                employer_share += amount
                if code and "NPS" in code:
                    nps_employer_contrib += amount
                if code == "EPF_EMPLOYER":
                    epf_employer_contrib += amount
            elif is_deduction(line):
                ded += amount
                total_deductions += amount
            else:
                fail(f"{ctx}: unrecognized non-informational classification {classification!r}")

            if code == "GPF_SUBSCRIPTION":
                jur = line.get("gpf_jurisdiction")
                if jur == "Mumbai":
                    gpf_mumbai += amount
                elif jur == "Nagpur":
                    gpf_nagpur += amount
                else:
                    fail(f"{ctx}: GPF line missing Mumbai/Nagpur jurisdiction tag")
            elif code == "NPS_EMPLOYEE":
                nps_employee += amount
            elif code == "NPS_EMPLOYER_TRANSFER" or (
                line.get("employer_transfer") and line.get("transfer_of") == "NPS_EMPLOYER"
            ):
                nps_employer_transfer += amount
            elif code == "EPF_EMPLOYEE":
                epf_employee += amount
            elif code == "EPF_EMPLOYER_TRANSFER" or (
                line.get("employer_transfer") and line.get("transfer_of") == "EPF_EMPLOYER"
            ):
                epf_employer_transfer += amount
            elif code == "INCOME_TAX":
                income_tax += amount
            elif code == "GIS":
                gis += amount
            elif code == "HBA_INSTALLMENT":
                hba += amount
            elif code == "PROFESSIONAL_TAX":
                professional_tax += amount
                pt_line_count += 1
                if amount != PT_RATE:
                    fail(f"{ctx}: professional tax amount must be {PT_RATE}, got {amount}")
            elif code == "ACCOMMODATION_LICENSE_FEE":
                loc = line.get("accommodation_location")
                if loc == "Mumbai":
                    acc_mumbai += amount
                elif loc == "Worli":
                    acc_worli += amount
                else:
                    fail(f"{ctx}: accommodation location must be Mumbai or Worli, got {loc!r}")
            elif code == "FOREGONE_HRA":
                # Should have been caught as informational above.
                if not is_informational(line):
                    fail(f"{ctx}: FOREGONE_HRA must be informational / excluded_from_totals")

        computed_net = earn + er_contrib - ded
        net_payable += computed_net

        totals = pay.get("totals") or {}
        declared_net = parse_amount(totals.get("net_payable", "0"), f"{emp_id}.totals.net_payable")
        declared_earn = parse_amount(totals.get("earnings", "0"), f"{emp_id}.totals.earnings")
        declared_er = parse_amount(
            totals.get("employer_contribution", "0"), f"{emp_id}.totals.employer_contribution"
        )
        declared_ded = parse_amount(totals.get("deductions", "0"), f"{emp_id}.totals.deductions")

        if computed_net != declared_net:
            fail(
                f"{emp_id}: per-employee net mismatch: "
                f"recomputed {computed_net} vs totals.net_payable {declared_net} "
                f"(earnings={earn} + employer_contribution={er_contrib} - deductions={ded})"
            )
        if earn != declared_earn or er_contrib != declared_er or ded != declared_ded:
            fail(
                f"{emp_id}: per-employee totals mismatch: "
                f"recomputed earn/er/ded={earn}/{er_contrib}/{ded} "
                f"vs declared={declared_earn}/{declared_er}/{declared_ded}"
            )

    ok(f"per-employee consistency checked for {len(pay_by_id)} employees")

    # --- Compare recomputed vs HARD ---
    expect_eq(salary_earnings, HARD["salary_earnings"], "recomputed salary_earnings")
    expect_eq(employer_share, HARD["employer_share"], "recomputed employer_share")
    expect_eq(salary_earnings + employer_share, HARD["gross_bill"], "recomputed gross_bill")
    expect_eq(total_deductions, HARD["total_deductions"], "recomputed total_deductions")
    expect_eq(net_payable, HARD["net_payable"], "recomputed net_payable")
    expect_eq(gpf_mumbai, HARD["gpf_mumbai"], "recomputed gpf_mumbai")
    expect_eq(gpf_nagpur, HARD["gpf_nagpur"], "recomputed gpf_nagpur")
    expect_eq(gpf_mumbai + gpf_nagpur, HARD["gpf_total"], "recomputed gpf_total")
    expect_eq(income_tax, HARD["income_tax"], "recomputed income_tax")
    expect_eq(gis, HARD["gis"], "recomputed gis")
    expect_eq(hba, HARD["hba"], "recomputed hba")
    expect_eq(professional_tax, HARD["professional_tax"], "recomputed professional_tax")
    expect_eq(acc_mumbai, HARD["accommodation_mumbai"], "recomputed accommodation_mumbai")
    expect_eq(acc_worli, HARD["accommodation_worli"], "recomputed accommodation_worli")
    expect_eq(
        acc_mumbai + acc_worli,
        HARD["accommodation_total"],
        "recomputed accommodation_total",
    )
    expect_eq(nps_employee, HARD["nps_employee"], "recomputed nps_employee")
    expect_eq(nps_employer_transfer, HARD["nps_employer"], "recomputed nps_employer_transfer")
    expect_eq(epf_employee, HARD["epf_employee"], "recomputed epf_employee")
    expect_eq(epf_employer_contrib, HARD["epf_employer"], "recomputed epf_employer_contribution")
    expect_eq(epf_employer_transfer, HARD["epf_employer"], "recomputed epf_employer_transfer")
    expect_eq(
        nps_employer_transfer + epf_employer_transfer,
        HARD["employer_transfer"],
        "recomputed employer_transfer",
    )
    expect_eq(
        nps_employee + epf_employee,
        HARD["employee_contribution"],
        "recomputed employee_contribution",
    )

    # Professional tax liability
    liable = [e for e in employees if e.get("professional_tax_liable")]
    if len(liable) != PT_LIABLE_COUNT:
        fail(f"professional_tax_liable count: expected {PT_LIABLE_COUNT}, actual {len(liable)}")
    else:
        ok(f"professional_tax_liable count = {PT_LIABLE_COUNT}")
    if pt_line_count != PT_LIABLE_COUNT:
        fail(
            f"professional tax pay lines: expected {PT_LIABLE_COUNT} lines at {PT_RATE}, "
            f"actual line count {pt_line_count}"
        )
    else:
        ok(f"professional tax lines: {PT_LIABLE_COUNT} × {PT_RATE}")

    # EPF pairing + NPS asymmetry
    if epf_employer_contrib != epf_employer_transfer:
        fail(
            f"EPF pairing broken: employer_contribution {epf_employer_contrib} "
            f"!= transfer {epf_employer_transfer}"
        )
    else:
        ok(
            f"EPF employer_contribution/transfer pairing holds "
            f"({epf_employer_contrib} = {epf_employer_transfer})"
        )

    if nps_employer_contrib != Decimal("0"):
        fail(
            f"NPS asymmetry violated: NPS employer_contribution lines summed into gross_bill "
            f"total {nps_employer_contrib}; must be 0 (NPS employer is transfer-only)"
        )
    else:
        ok(
            "NPS asymmetry preserved: no NPS employer_contribution addition in gross_bill "
            f"(NPS employer transfer = {nps_employer_transfer})"
        )

    if employer_share != HARD["epf_employer"]:
        fail(
            f"narrow employer_share must equal EPF employer only: "
            f"employer_share={employer_share}, epf_employer={HARD['epf_employer']}"
        )
    else:
        ok("employer_share equals EPF employer only (narrow share)")

    # Regime exclusivity
    regimes = {"gpf_mumbai", "gpf_nagpur", "nps", "epf"}
    for emp in employees:
        eid = emp.get("employee_id")
        regime = emp.get("regime")
        if regime not in regimes:
            fail(f"{eid}: invalid regime {regime!r}")
            continue
        flags = [
            regime.startswith("gpf"),
            regime == "nps",
            regime == "epf",
        ]
        if sum(1 for f in flags if f) != 1:
            fail(f"{eid}: regime exclusivity broken for {regime!r}")

        pay = pay_by_id.get(eid) or {}
        codes = {ln.get("component_code") for ln in (pay.get("lines") or [])}
        has_gpf = "GPF_SUBSCRIPTION" in codes
        has_nps = bool(codes & {"NPS_EMPLOYEE", "NPS_EMPLOYER_TRANSFER"})
        has_epf = bool(codes & {"EPF_EMPLOYEE", "EPF_EMPLOYER", "EPF_EMPLOYER_TRANSFER"})
        present = sum([has_gpf, has_nps, has_epf])
        if present != 1:
            fail(
                f"{eid}: expected exactly one retirement scheme in pay lines; "
                f"gpf={has_gpf} nps={has_nps} epf={has_epf}"
            )

        if regime == "nps" and not emp.get("pran"):
            fail(f"{eid}: NPS employee missing PRAN")
        if regime.startswith("gpf") and not emp.get("gpf_account"):
            fail(f"{eid}: GPF employee missing gpf_account")
        if regime == "epf" and not emp.get("epf_number"):
            fail(f"{eid}: EPF employee missing epf_number")

    ok("regime exclusivity: each employee in exactly one of gpf_mumbai/gpf_nagpur/nps/epf")

    # NPS schedule reconstruction excludes EPF (and vice versa)
    nps_ids = {e["employee_id"] for e in employees if e.get("regime") == "nps"}
    epf_ids = {e["employee_id"] for e in employees if e.get("regime") == "epf"}
    for emp_id in nps_ids:
        codes = {ln.get("component_code") for ln in (pay_by_id[emp_id].get("lines") or [])}
        if codes & {"EPF_EMPLOYEE", "EPF_EMPLOYER", "EPF_EMPLOYER_TRANSFER"}:
            fail(f"{emp_id}: NPS schedule employee carries EPF lines")
    for emp_id in epf_ids:
        codes = {ln.get("component_code") for ln in (pay_by_id[emp_id].get("lines") or [])}
        if codes & {"NPS_EMPLOYEE", "NPS_EMPLOYER_TRANSFER"}:
            fail(f"{emp_id}: EPF employee carries NPS lines")
    ok("NPS schedule reconstruction excludes EPF employees and vice versa")

    # Informational foregone HRA must not affect totals
    if foregone_in_earnings != Decimal("0"):
        fail(f"informational foregone HRA leaked into earnings: {foregone_in_earnings}")
    else:
        ok("informational foregone HRA excluded from earnings/gross/deductions/net")

    # --- expected_totals.json must match HARD and recomputed ---
    aggregates = expected_doc.get("aggregates") or {}
    for key, hard_val in HARD.items():
        if key not in aggregates:
            fail(f"expected_totals.json aggregates missing key {key}")
            continue
        exp_val = parse_amount(aggregates[key], f"expected_totals.aggregates.{key}")
        if exp_val != hard_val:
            fail(
                f"expected_totals.aggregates.{key}: fixture value {exp_val} "
                f"!= hardcoded HARD {hard_val}"
            )
    ok("expected_totals.json aggregates match hardcoded HARD requirements")

    rr = expected_doc.get("report_reconciliation") or {}
    report_checks = {
        "pay_bill.salary_earnings": (rr.get("pay_bill") or {}).get("salary_earnings"),
        "pay_bill.employer_share": (rr.get("pay_bill") or {}).get("employer_share"),
        "pay_bill.gross_bill": (rr.get("pay_bill") or {}).get("gross_bill"),
        "pay_bill.total_deductions": (rr.get("pay_bill") or {}).get("total_deductions"),
        "pay_bill.net_payable": (rr.get("pay_bill") or {}).get("net_payable"),
        "treasury_face.net_payable": (rr.get("treasury_face") or {}).get("net_payable"),
        "bank_rtgs_advice_sum": rr.get("bank_rtgs_advice_sum"),
        "gpf_mumbai_schedule": rr.get("gpf_mumbai_schedule"),
        "gpf_nagpur_schedule": rr.get("gpf_nagpur_schedule"),
        "nps_contribution_schedule.employee": (rr.get("nps_contribution_schedule") or {}).get(
            "employee"
        ),
        "nps_contribution_schedule.employer": (rr.get("nps_contribution_schedule") or {}).get(
            "employer"
        ),
        "income_tax_schedule": rr.get("income_tax_schedule"),
        "professional_tax_schedule": rr.get("professional_tax_schedule"),
        "gis_schedule": rr.get("gis_schedule"),
        "hba_schedule": rr.get("hba_schedule"),
        "accommodation_mumbai_actual": rr.get("accommodation_mumbai_actual"),
        "accommodation_worli_actual": rr.get("accommodation_worli_actual"),
        "payslip_nets_sum": rr.get("payslip_nets_sum"),
    }
    report_expected = {
        "pay_bill.salary_earnings": HARD["salary_earnings"],
        "pay_bill.employer_share": HARD["employer_share"],
        "pay_bill.gross_bill": HARD["gross_bill"],
        "pay_bill.total_deductions": HARD["total_deductions"],
        "pay_bill.net_payable": HARD["net_payable"],
        "treasury_face.net_payable": HARD["net_payable"],
        "bank_rtgs_advice_sum": HARD["employee_disbursement"],
        "gpf_mumbai_schedule": HARD["gpf_mumbai"],
        "gpf_nagpur_schedule": HARD["gpf_nagpur"],
        "nps_contribution_schedule.employee": HARD["nps_employee"],
        "nps_contribution_schedule.employer": HARD["nps_employer"],
        "income_tax_schedule": HARD["income_tax"],
        "professional_tax_schedule": HARD["professional_tax"],
        "gis_schedule": HARD["gis"],
        "hba_schedule": HARD["hba"],
        "accommodation_mumbai_actual": HARD["accommodation_mumbai"],
        "accommodation_worli_actual": HARD["accommodation_worli"],
        "payslip_nets_sum": HARD["employee_disbursement"],
    }
    for label, raw in report_checks.items():
        actual = parse_amount(raw, f"report_reconciliation.{label}")
        expect_eq(actual, report_expected[label], f"report_reconciliation.{label}")

    if not (rr.get("nps_contribution_schedule") or {}).get("excludes_epf"):
        fail("report_reconciliation.nps_contribution_schedule.excludes_epf must be true")
    else:
        ok("NPS contribution schedule marked excludes_epf=true")

    # --- Synthetic identity / PII guards ---
    identity_failures_before = len(FAILURES)
    for emp in employees:
        eid = emp.get("employee_id")
        name = emp.get("name", "")
        if not NAME_RE.match(str(name)):
            fail(f"{eid}: name {name!r} does not match synthetic convention Employee A-NN")
        pan = emp.get("pan", "")
        if not PAN_RE.match(str(pan)) or not PAN_SHAPE_RE.match(str(pan)):
            fail(f"{eid}: PAN {pan!r} is not in fake ZZZPZ####Z namespace")
        # PAN type letter is the 4th character (1-indexed); P = Person.
        # Example namespace ZZZPZ0001Z → positions Z Z Z P Z 0 0 0 1 Z.
        if not str(pan).startswith("ZZZPZ") or len(str(pan)) < 4 or str(pan)[3] != "P":
            fail(f"{eid}: PAN {pan!r} failed fake-prefix / 4th-char-P (Person) checks")
        sevarth = emp.get("sevarth_id", "")
        if not SEVARTH_RE.match(str(sevarth)):
            fail(f"{eid}: sevarth_id {sevarth!r} does not match SYNTH####")
        bank = emp.get("bank_account", "")
        if not BANK_RE.match(str(bank)):
            fail(f"{eid}: bank_account {bank!r} must be 14-digit zero-prefixed synthetic")
        ifsc = emp.get("ifsc", "")
        if not IFSC_RE.match(str(ifsc)):
            fail(f"{eid}: IFSC {ifsc!r} must match SYNT####### fake prefix")

        regime = emp.get("regime")
        if regime == "nps":
            pran = emp.get("pran", "")
            if not PRAN_RE.match(str(pran)):
                fail(f"{eid}: PRAN {pran!r} must match fake 9000######## block")
        if regime == "gpf_mumbai":
            gpf = emp.get("gpf_account", "")
            if not GPF_MUM_RE.match(str(gpf)):
                fail(f"{eid}: gpf_account {gpf!r} must match SYNGPF/MUM/####")
        if regime == "gpf_nagpur":
            gpf = emp.get("gpf_account", "")
            if not GPF_NGP_RE.match(str(gpf)):
                fail(f"{eid}: gpf_account {gpf!r} must match SYNGPF/NGP/####")
        if regime == "epf":
            epf = emp.get("epf_number", "")
            if not EPF_RE.match(str(epf)):
                fail(f"{eid}: epf_number {epf!r} must match SYNTEPF/######/UAN")

        # Forbidden extra PII fields
        for banned in ("address", "phone", "mobile", "dob", "date_of_birth", "email", "aadhaar"):
            if banned in emp:
                fail(f"{eid}: forbidden PII field present: {banned}")

    if len(FAILURES) == identity_failures_before:
        ok("synthetic identity conventions hold for all employees (name/PAN/PRAN/bank/IFSC/accounts)")

    # Organization offices / signatories
    offices = org.get("offices") or []
    cities = {o.get("city") for o in offices if isinstance(o, dict)}
    for required_city in ("Mumbai", "Nagpur", "Worli"):
        if required_city not in cities:
            fail(f"organization.json missing office city {required_city}")
    if {"Mumbai", "Nagpur", "Worli"} <= cities:
        ok("organization offices include Mumbai, Nagpur, Worli")

    for office in offices:
        if not isinstance(office, dict):
            continue
        sigs = office.get("signatories") or {}
        for role in ("maker", "checker", "approving_officer"):
            person = sigs.get(role) or {}
            sname = person.get("name", "")
            if not SIGNATORY_NAME_RE.match(str(sname)):
                fail(
                    f"office {office.get('office_id')}: signatory {role} name {sname!r} "
                    f"must match Employee S-NN"
                )
    ok("signatories use synthetic Employee S-NN names")

    # Component catalog sanity
    comp_list = components.get("components") or []
    codes = {c.get("code") for c in comp_list if isinstance(c, dict)}
    required_codes = {
        "BASIC",
        "DA",
        "HRA",
        "TRANSPORT",
        "OTHER_ALLOWANCE",
        "FOREGONE_HRA",
        "GPF_SUBSCRIPTION",
        "NPS_EMPLOYEE",
        "NPS_EMPLOYER_TRANSFER",
        "EPF_EMPLOYEE",
        "EPF_EMPLOYER",
        "EPF_EMPLOYER_TRANSFER",
        "INCOME_TAX",
        "PROFESSIONAL_TAX",
        "GIS",
        "HBA_INSTALLMENT",
        "ACCOMMODATION_LICENSE_FEE",
    }
    missing = required_codes - codes
    if missing:
        fail(f"components.json missing codes: {sorted(missing)}")
    else:
        ok("components.json includes all required pay component codes")

    foregone = next((c for c in comp_list if c.get("code") == "FOREGONE_HRA"), None)
    if not foregone or not (
        foregone.get("informational") or foregone.get("excluded_from_totals")
    ):
        fail("FOREGONE_HRA component must be flagged informational / excluded_from_totals")
    else:
        ok("FOREGONE_HRA flagged informational / excluded_from_totals")

    # Headcount
    regime_counts = {
        "gpf_mumbai": 0,
        "gpf_nagpur": 0,
        "nps": 0,
        "epf": 0,
    }
    for emp in employees:
        r = emp.get("regime")
        if r in regime_counts:
            regime_counts[r] += 1
    total_headcount = len(employees)
    if not (28 <= total_headcount <= 34):
        fail(f"employee count {total_headcount} outside required ~28-34 range")
    else:
        ok(
            f"headcount {total_headcount} "
            f"(gpf_mumbai={regime_counts['gpf_mumbai']}, "
            f"gpf_nagpur={regime_counts['gpf_nagpur']}, "
            f"nps={regime_counts['nps']}, epf={regime_counts['epf']})"
        )

    print()
    if FAILURES:
        print(f"=== FAILED: {len(FAILURES)} violation(s), {len(PASSES)} check(s) passed ===")
        for msg in FAILURES:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    print("=== PASS: all June 2026 golden fixture invariants hold ===")
    print(f"checks passed: {len(PASSES)}")
    print(
        "verified: JSON load, hard identities, recomputed aggregates, per-employee nets, "
        "component sums, PT 28×200, EPF pairing, NPS asymmetry (no gross addition), "
        "regime exclusivity, NPS/EPF schedule separation, synthetic PII conventions, "
        "report_reconciliation totals, informational foregone HRA exclusion"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
