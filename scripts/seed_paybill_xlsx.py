#!/usr/bin/env python3
"""Seed a running Accord org from the June 2026 MSIDC pay-bill spreadsheet.

Parses real employee / pay / deduction rows from the xlsx (not the synthetic
golden fixture), wipes existing master data for the active org, then posts via
the public HTTP APIs.

Usage:
  backend/.venv/bin/python scripts/seed_paybill_xlsx.py \\
    --xlsx "/Users/darshan/Downloads/Pay bill - June 2026 Regular Staff.xlsx"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from seed_paybill_parser import EmployeeRow, SeedError, _require, money_str, parse_paybill  # noqa: E402

EFFECTIVE_FROM = "2026-01-01"

COMPONENT_SPECS: list[tuple[str, str, str, str]] = [
    ("BASIC", "Basic Pay", "earning", "basic_pay"),
    ("DA", "Dearness Allowance", "earning", "dearness_allowance"),
    ("CLA", "City Compensatory Allowance", "earning", "city_compensatory_allowance"),
    ("HRA", "House Rent Allowance", "earning", "house_rent_allowance"),
    ("WASH_ALLOWANCE", "Wash Allowance", "earning", "wash_child_other_charges"),
    (
        "ADDITIONAL_ALLOWANCE",
        "Additional Allowance",
        "earning",
        "additional_conveyance_transport_allowance",
    ),
    ("TRANSPORT", "Transport / PTA", "earning", "transport_pta_honorarium"),
    (
        "OTHER_ALLOWANCE",
        "Other Allowances",
        "earning",
        "other_reimbursement_salary_increment_difference",
    ),
    (
        "GPF_SUBSCRIPTION",
        "GPF Subscription",
        "ag_deduction",
        "gpf_subscription_refund_arrears",
    ),
    ("NPS_EMPLOYEE", "NPS Employee Contribution", "ag_deduction", "pension_employee_share"),
    (
        "NPS_EMPLOYER_TRANSFER",
        "NPS Employer Transfer",
        "ag_deduction",
        "pension_employer_share",
    ),
    ("EPF_EMPLOYEE", "EPF Employee Contribution", "ag_deduction", "pension_employee_share"),
    (
        "EPF_EMPLOYER",
        "EPF Employer Contribution",
        "employer_contribution",
        "employer_share",
    ),
    (
        "EPF_EMPLOYER_TRANSFER",
        "EPF Employer Transfer",
        "ag_deduction",
        "pension_employer_share",
    ),
    ("INCOME_TAX", "Income Tax", "treasury_deduction", "income_tax"),
    (
        "PROFESSIONAL_TAX",
        "Professional Tax",
        "treasury_deduction",
        "professional_tax",
    ),
    ("GIS", "Group Insurance Scheme", "treasury_deduction", "insurance"),
    ("HBA_INSTALLMENT", "House Building Advance", "external_recovery", "advances"),
    (
        "ACCOMMODATION_LICENSE_FEE",
        "Accommodation License Fee",
        "external_recovery",
        "house_rent_service_charge_arrears",
    ),
]


def component_create_payload(
    *,
    code: str,
    name: str,
    classification: str,
    register_column: str,
    display_order: int,
) -> dict[str, Any]:
    """Build source-faithful catalog metadata, including transfer pairing."""

    payload: dict[str, Any] = {
        "code": code,
        "name": name,
        "classification": classification,
        "register_column": register_column,
        "display_order": display_order,
    }
    if code == "NPS_EMPLOYER_TRANSFER":
        # NPS employer money is remitted off bill: it reduces Pay Bill net but
        # is added back to the employee bank disbursement.
        payload["employer_transfer"] = True
    elif code == "EPF_EMPLOYER_TRANSFER":
        # EPF employer share is first included in gross and then transferred
        # out through the matching deduction.
        payload.update(
            {
                "employer_transfer": True,
                "transfer_of": "EPF_EMPLOYER",
            }
        )
    return payload


def reconciliation_summary(employees: list[EmployeeRow]) -> dict[str, int]:
    """Return normalized workbook totals, failing when required source facts are unresolved."""
    if not employees:
        raise SeedError("Pay Bill contains no employee rows")
    serials = [employee.sr for employee in employees]
    if len(serials) != len(set(serials)):
        raise SeedError("Pay Bill contains duplicate employee serial numbers")
    for employee in employees:
        if employee.regime is None:
            raise SeedError(f"{employee.name}: retirement regime is unresolved")
        components = sum(
            (
                employee.basic,
                employee.da,
                employee.cla,
                employee.hra,
                employee.wash,
                employee.other,
                employee.additional_allowance,
                employee.ta,
            )
        )
        if components != employee.gross:
            raise SeedError(
                f"{employee.name}: earning components {components} do not match gross {employee.gross}"
            )

    salary_earnings = sum(employee.gross for employee in employees)
    employer_share = sum(
        employee.nps_employee for employee in employees if employee.regime == "epf"
    )
    total_deductions = sum(
        employee.gpf
        + employee.nps_employer
        + employee.nps_employee
        + employee.hba
        + employee.income_tax
        + employee.gis
        + employee.professional_tax
        + (employee.accommodation.license_fee if employee.accommodation else 0)
        for employee in employees
    )
    gross_bill = salary_earnings + employer_share
    net_payable = gross_bill - total_deductions
    offbill_employer_remittance = sum(
        employee.nps_employer for employee in employees if employee.regime == "nps"
    )
    return {
        "headcount": len(employees),
        "salary_earnings": salary_earnings,
        "employer_share": employer_share,
        "gross_bill": gross_bill,
        "total_deductions": total_deductions,
        "net_payable": net_payable,
        "offbill_employer_remittance": offbill_employer_remittance,
        "employee_disbursement": net_payable + offbill_employer_remittance,
        "additional_allowance": sum(employee.additional_allowance for employee in employees),
        "gpf_total": sum(employee.gpf for employee in employees),
        "pension_employer": sum(employee.nps_employer for employee in employees),
        "pension_employee": sum(employee.nps_employee for employee in employees),
        "income_tax": sum(employee.income_tax for employee in employees),
        "gis": sum(employee.gis for employee in employees),
        "professional_tax": sum(employee.professional_tax for employee in employees),
    }


def wipe_org_master_data(org_id: str, *, dsn_env: dict[str, str]) -> None:
    import subprocess

    # Validate before any SQL construction; psql :'org_id' quotes the bound value.
    org_uuid = str(UUID(org_id))
    tables = [
        "payroll_report_snapshots",
        "payroll_result_lines",
        "payroll_employee_results",
        "payroll_approvals",
        "payroll_run_inputs",
        "payroll_run_employees",
        "payroll_run_versions",
        "payroll_runs",
        "payroll_periods",
        "export_artifacts",
        "report_configurations",
        "accommodation_charge_versions",
        "accommodation_assignments",
        "advance_installment_versions",
        "advance_accounts",
        "recurring_instruction_versions",
        "recurring_instructions",
        "employee_bank_account_versions",
        "employee_pay_versions",
        "employee_posting_versions",
        "employee_profile_versions",
        "employees",
        "component_rate_versions",
        "pay_components",
        "posts",
        "offices",
        "jobs",
        "outbox_events",
        "idempotency_keys",
    ]
    # Escape immutability triggers and break run↔version FK before deleting versions.
    sql = (
        "BEGIN;\n"
        "SET LOCAL accord.allow_immutable_ddl = 'on';\n"
        "UPDATE payroll_runs\n"
        "   SET current_version_id = NULL\n"
        " WHERE organization_id = :'org_id'::uuid;\n"
    )
    for table in tables:
        sql += f"DELETE FROM {table} WHERE organization_id = :'org_id'::uuid;\n"
    sql += "COMMIT;\n"
    env = {**os.environ, **dsn_env}
    proc = subprocess.run(
        [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"org_id={org_uuid}",
            "-d",
            dsn_env.get("PGDATABASE", "accord"),
        ],
        env=env,
        input=sql,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SeedError(f"wipe failed: {proc.stderr or proc.stdout}")
    print(f"Wiped master data for org {org_uuid}")


def employee_create_payload(
    emp: EmployeeRow,
    *,
    office_id: UUID,
    post_id: UUID,
    pay_bill_post_id: UUID | None = None,
) -> dict[str, Any]:
    """Build an API payload containing only workbook-backed employee values."""
    if emp.regime in {"gpf_mumbai", "gpf_nagpur", "gpf"}:
        regime = "gpf"
        gpf_jurisdiction = (
            "mumbai"
            if emp.regime == "gpf_mumbai"
            else "nagpur"
            if emp.regime == "gpf_nagpur"
            else None
        )
    elif emp.regime in {"nps", "epf"}:
        regime = emp.regime
        gpf_jurisdiction = None
    else:
        raise SeedError(f"{emp.name}: unsupported retirement regime {emp.regime!r}")

    profile: dict[str, Any] = {
        "name": emp.name,
        "sevarth_id": emp.sevarth_id,
        "pan": emp.pan,
        "date_of_birth": None,
        "date_of_joining": None,
        "retirement_regime": regime,
        "gpf_jurisdiction": gpf_jurisdiction,
        "pran": emp.pran,
        "gpf_account_number": emp.gpf_account,
        "epf_number": emp.epf_number,
        "pension_account": emp.pension_account,
    }
    payload: dict[str, Any] = {
        "employee_number": f"MSIDC{emp.sr:03d}",
        "effective_from": EFFECTIVE_FROM,
        "profile": profile,
        "posting": {
            "office_id": str(office_id),
            "post_id": str(post_id),
            "pay_bill_post_id": (None if pay_bill_post_id is None else str(pay_bill_post_id)),
        },
        "pay": {"pay_matrix_level": None, "basic_pay": money_str(emp.basic)},
    }
    bank_fields = (emp.bank_account, emp.ifsc, emp.bank_name)
    if all(bank_fields):
        payload["bank"] = {
            "account_number": emp.bank_account,
            "ifsc": emp.ifsc,
            "bank_name": emp.bank_name,
            "branch": emp.bank_branch,
            "is_primary_salary": True,
        }
    elif any(bank_fields) or emp.bank_branch:
        raise SeedError(f"{emp.name}: partial bank details cannot be seeded")
    return payload


def seed(base_url: str, xlsx: Path, *, pg: dict[str, str]) -> None:
    employees = parse_paybill(xlsx)
    summary = reconciliation_summary(employees)
    print(f"Parsed {len(employees)} employees from {xlsx.name}")
    print(
        "Reconciled normalized totals: "
        f"gross={summary['gross_bill']} deductions={summary['total_deductions']} "
        f"net={summary['net_payable']} disbursement={summary['employee_disbursement']}"
    )
    for emp in employees:
        print(
            f"  {emp.sr:2} {emp.name[:32]:32} {emp.regime:12} "
            f"basic={emp.basic} da={emp.da} hra={emp.hra} gpf={emp.gpf} "
            f"nps={emp.nps_employee}/{emp.nps_employer} it={emp.income_tax} gis={emp.gis}"
        )

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0) as client:
        login = client.get("/api/auth/login", follow_redirects=False)
        if login.status_code not in {200, 302}:
            raise SeedError(f"login failed: {login.status_code}")
        me = _require(client.get("/api/auth/me"), context="me")
        if me.get("access_state") != "active" or not me.get("organization"):
            raise SeedError(
                "No active organization membership. Bootstrap with "
                "scripts/provision_organization.py and ensure this user is a member, then re-run."
            )
        org = me["organization"]
        try:
            org_id = str(UUID(org["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise SeedError(f"organization id is not a UUID: {org.get('id')!r}") from exc
        print(f"Seeding into {org['name']} ({org['slug']})")

        wipe_org_master_data(org_id, dsn_env=pg)

        # Offices
        offices: dict[str, UUID] = {}
        for name, jurisdiction in (
            ("MSIDC Mumbai HQ", "mumbai"),
            ("MSIDC Nagpur GPF Circle", "nagpur"),
            ("MSIDC Worli Quarters", "worli"),
        ):
            body = _require(
                client.post(
                    "/api/offices",
                    json={"name": name, "jurisdiction": jurisdiction},
                ),
                context=f"office {name}",
            )
            offices[jurisdiction] = UUID(body["id"])
            print(f"  office {name}")

        # Actual employee posts and Pay Bill grouping posts are distinct. The
        # canonical workbook has repeated headings and groups that contain
        # several employee designations, so one designation cannot safely be
        # overloaded as the group identity.
        post_ids: dict[str, UUID] = {}
        for designation in sorted({e.designation for e in employees}):
            class_name = "I"
            dl = designation.lower()
            if "clerk" in dl:
                class_name = "III"
            elif "junior" in dl or "deputy" in dl or "assistant" in dl:
                class_name = "II"
            post_payload: dict[str, Any] = {
                "designation": designation,
                "class_name": class_name,
            }
            body = _require(
                client.post(
                    "/api/posts",
                    json=post_payload,
                ),
                context=f"post {designation}",
            )
            post_ids[designation] = UUID(body["id"])
            print(f"  post {designation}")

        pay_bill_groups = {
            employee.pay_bill_group.order: employee.pay_bill_group
            for employee in employees
            if employee.pay_bill_group is not None
        }
        pay_bill_post_ids: dict[int, UUID] = {}
        for order, group in sorted(pay_bill_groups.items()):
            owner = (group.owner_designation or "").lower()
            class_name = "I"
            if "clerk" in owner:
                class_name = "III"
            elif "junior" in owner or "deputy" in owner or "assistant" in owner:
                class_name = "II"
            body = _require(
                client.post(
                    "/api/posts",
                    json={
                        "designation": f"Pay Bill Group {order:02d}: {group.heading}",
                        "pay_bill_heading": group.heading,
                        "class_name": class_name,
                        "sanctioned_strength": group.sanctioned_strength,
                        "vacant_count": group.vacant_count,
                        "pay_scale": group.pay_scale,
                        "display_order": order,
                    },
                ),
                context=f"Pay Bill group {order}: {group.heading}",
            )
            pay_bill_post_ids[order] = UUID(body["id"])
            print(f"  Pay Bill group {order:02d} {group.heading}")

        # Components
        component_ids: dict[str, UUID] = {}
        for order, (code, name, classification, register_column) in enumerate(
            COMPONENT_SPECS, start=1
        ):
            component_payload = component_create_payload(
                code=code,
                name=name,
                classification=classification,
                register_column=register_column,
                display_order=order,
            )
            body = _require(
                client.post(
                    "/api/pay-components",
                    json=component_payload,
                ),
                context=f"component {code}",
            )
            cid = UUID(body["id"])
            component_ids[code] = cid
            if code not in {"HBA_INSTALLMENT", "ACCOMMODATION_LICENSE_FEE"}:
                _require(
                    client.post(
                        f"/api/pay-components/{cid}/rate-versions",
                        json={
                            "effective_from": EFFECTIVE_FROM,
                            "calc_kind": "fixed_recurring_amount",
                            "amount": "0.00",
                            "rounding_rule": "ROUND_HALF_UP_RUPEE",
                        },
                    ),
                    context=f"rate {code}",
                )
            print(f"  component {code}")

        for emp in employees:
            if emp.regime == "gpf_nagpur":
                office_id = offices["nagpur"]
                regime = "gpf"
            elif emp.regime == "gpf_mumbai":
                office_id = offices["mumbai"]
                regime = "gpf"
            elif emp.regime == "nps":
                office_id = (
                    offices["worli"]
                    if emp.accommodation and emp.accommodation.location == "worli"
                    else offices["mumbai"]
                )
                regime = "nps"
            elif emp.regime == "epf":
                office_id = offices["mumbai"]
                regime = "epf"
            elif emp.regime == "gpf":
                office_id = offices["mumbai"]
                regime = "gpf"
            else:
                raise SeedError(f"{emp.name}: unsupported retirement regime {emp.regime!r}")

            body = _require(
                client.post(
                    "/api/employees",
                    json=employee_create_payload(
                        emp,
                        office_id=office_id,
                        post_id=post_ids[emp.designation],
                        pay_bill_post_id=(
                            None
                            if emp.pay_bill_group is None
                            else pay_bill_post_ids[emp.pay_bill_group.order]
                        ),
                    ),
                ),
                context=f"employee {emp.name}",
            )
            employee_id = UUID(body["id"])

            recurring: list[tuple[str, int]] = [
                ("DA", emp.da),
                ("CLA", emp.cla),
                ("HRA", emp.hra),
                ("WASH_ALLOWANCE", emp.wash),
                ("ADDITIONAL_ALLOWANCE", emp.additional_allowance),
                ("TRANSPORT", emp.ta),
                ("OTHER_ALLOWANCE", emp.other),
                ("INCOME_TAX", emp.income_tax),
                ("PROFESSIONAL_TAX", emp.professional_tax),
                ("GIS", emp.gis),
            ]
            if regime == "gpf" and emp.gpf:
                recurring.append(("GPF_SUBSCRIPTION", emp.gpf))
            elif regime == "nps":
                if emp.nps_employee:
                    recurring.append(("NPS_EMPLOYEE", emp.nps_employee))
                if emp.nps_employer:
                    recurring.append(("NPS_EMPLOYER_TRANSFER", emp.nps_employer))
            elif regime == "epf":
                if emp.nps_employee:
                    recurring.append(("EPF_EMPLOYEE", emp.nps_employee))
                    recurring.append(("EPF_EMPLOYER", emp.nps_employee))
                    recurring.append(("EPF_EMPLOYER_TRANSFER", emp.nps_employee))

            for code, amount in recurring:
                if amount <= 0:
                    continue
                _require(
                    client.post(
                        f"/api/employees/{employee_id}/recurring-instructions",
                        json={
                            "component_id": str(component_ids[code]),
                            "effective_from": EFFECTIVE_FROM,
                            "amount": money_str(amount),
                        },
                    ),
                    context=f"{emp.name} {code}",
                )

            if emp.hba > 0:
                total_inst = 24
                recovered = 0
                if emp.hba_installments and "/" in emp.hba_installments:
                    parts = emp.hba_installments.split("/")
                    try:
                        recovered = max(int(parts[0]) - 1, 0)
                        total_inst = int(parts[1])
                    except ValueError:
                        pass
                principal = emp.hba * max(total_inst - recovered, 1)
                _require(
                    client.post(
                        f"/api/employees/{employee_id}/advances",
                        json={
                            "advance_type": "hba",
                            "principal": money_str(principal),
                            "sanctioned_on": EFFECTIVE_FROM,
                            "reference": f"HBA-{emp.pan}",
                            "installment": {
                                "installment_amount": money_str(emp.hba),
                                "installments_total": total_inst,
                                "installments_recovered_opening": recovered,
                                "effective_from": EFFECTIVE_FROM,
                            },
                        },
                    ),
                    context=f"{emp.name} HBA",
                )

            if emp.accommodation and emp.accommodation.license_fee > 0:
                if not emp.accommodation.address:
                    raise SeedError(f"{emp.name}: accommodation address is missing")
                charge: dict[str, Any] = {
                    "license_fee": money_str(emp.accommodation.license_fee),
                    "effective_from": EFFECTIVE_FROM,
                }
                for field_name in (
                    "house_rent",
                    "service_charge",
                    "parking_charge",
                    "additional_parking_charge",
                ):
                    amount = getattr(emp.accommodation, field_name)
                    if amount is not None:
                        charge[field_name] = money_str(amount)
                if emp.accommodation.foregone_hra > 0:
                    charge["informational_hra_foregone"] = money_str(emp.accommodation.foregone_hra)
                _require(
                    client.post(
                        f"/api/employees/{employee_id}/accommodation",
                        json={
                            "quarters_location": emp.accommodation.location,
                            "quarters_identifier": emp.accommodation.address,
                            "quarters_address": emp.accommodation.address,
                            "charge": charge,
                        },
                    ),
                    context=f"{emp.name} accommodation",
                )

            print(f"  employee {emp.sr:02d} {emp.name}")

        listed = _require(
            client.get("/api/employees", params={"page_size": 100}),
            context="verify",
        )
        print(f"Done. {listed.get('total')} real employees loaded into {org['name']}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=Path("/Users/darshan/Downloads/Pay bill - June 2026 Regular Staff.xlsx"),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--pghost", default=os.environ.get("PGHOST", "127.0.0.1"))
    parser.add_argument("--pgport", default=os.environ.get("PGPORT", "5433"))
    parser.add_argument("--pguser", default=os.environ.get("PGUSER", "accord"))
    parser.add_argument("--pgpassword", default=os.environ.get("PGPASSWORD", "accord"))
    parser.add_argument("--pgdatabase", default=os.environ.get("PGDATABASE", "accord"))
    args = parser.parse_args()
    if not args.xlsx.is_file():
        print(f"error: spreadsheet not found: {args.xlsx}", file=sys.stderr)
        return 1
    pg = {
        "PGHOST": args.pghost,
        "PGPORT": str(args.pgport),
        "PGUSER": args.pguser,
        "PGPASSWORD": args.pgpassword,
        "PGDATABASE": args.pgdatabase,
    }
    try:
        seed(args.base_url, args.xlsx, pg=pg)
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
