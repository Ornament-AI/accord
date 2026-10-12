#!/usr/bin/env python3
"""Seed a sanitized, production-scale dataset into a running Accord API.

Scales the synthetic June 2026 golden fixture (fixtures/sanitized/june-2026/)
to a municipal-council-sized organization: each of the 32 sanitized employee
templates is cloned into many synthetic employees (no real PII — PANs, bank
accounts, IFSCs and identifiers are generated from reserved synthetic
prefixes). Six payroll periods are then driven through every workflow state by
the real role users, so maker-checker and capability gates are exercised:

  2026-04  posted, period closed       2026-07  submitted (awaiting approval)
  2026-05  posted                      2026-08  rejected
  2026-06  approved (awaiting post)    2026-09  calculated, with run inputs

Requires a dev-auth backend (DEV_AUTH_BYPASS=true): role users sign in with
their email through the password login endpoint, exactly like the UI. Provision
the organization and memberships first (scripts/provision_organization.py and
scripts/provision_member.py) for the emails passed below.

Usage:
  backend/.venv/bin/python scripts/seed_scale_fixture.py \\
    --admin-email admin@example.local --preparer-email preparer@example.local \\
    --approver-email approver@example.local --releaser-email releaser@example.local
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.seed_june_fixture import (  # noqa: E402
    SeedError,
    _create_components,
    _create_employee,
    _require,
    _seed_employee_amounts,
)
from tests.e2e.fixture_loader import (  # noqa: E402
    BASIC_CODE,
    EmployeeSeed,
    load_june_fixture,
)

FIRST_NAMES = (
    "Aarav",
    "Ishita",
    "Kabir",
    "Meera",
    "Rohan",
    "Sneha",
    "Vikram",
    "Ananya",
    "Arjun",
    "Priya",
    "Siddharth",
    "Kavya",
    "Nikhil",
    "Pooja",
    "Rahul",
    "Tanvi",
)
LAST_NAMES = (
    "Synthpatil",
    "Synthdeshmukh",
    "Synthjoshi",
    "Synthkulkarni",
    "Synthpawar",
    "Synthshinde",
    "Synthgaikwad",
    "Synthjadhav",
    "Synthmore",
    "Synthchavan",
)
DESIGNATIONS = (
    ("Synthetic Chief Officer", "I"),
    ("Synthetic Assistant Engineer", "II"),
    ("Synthetic Clerk", "III"),
    ("Synthetic Sanitation Inspector", "III"),
    ("Synthetic Peon", "IV"),
)
# Pay Bill grouping export fields, applied to DESIGNATIONS in order.
POST_EXPORT_FIELDS = (
    ("Group A - Officers", 100, 8, "15600-39100 GP 6600"),
    ("Group B - Senior Clerks", 150, 12, "9300-34800 GP 4400"),
    ("Group C - Clerks", 220, 18, "5200-20200 GP 2800"),
    ("Group D - Support Staff", 90, 7, "4440-7440 GP 1650"),
    ("Group E - Field Staff", 40, 4, "4440-7440 GP 1300"),
)
REPORT_PROFILE = {
    "legal_name": "Shaharpur Municipal Council",
    "office_name": "Office of the Chief Officer, Shaharpur Municipal Council",
    "address_lines": ["Municipal Bhavan, Station Road", "Shaharpur 442001, Maharashtra"],
    "phone": "07162-234567",
    "website": "https://shaharpurmc.example.gov.in",
    "ddo_name": "Chief Officer, Shaharpur Municipal Council",
    "ddo_code": "SMC-DDO-1101",
    "department_code": "UD-32",
    "administrative_department": "Urban Development Department, Maharashtra",
    "treasury_code": "TRC-1101",
    "fund_source": "Municipal Fund (0100)",
    "plan_status": "Non-Plan",
    "salary_reference_prefix": "SMC/PAY",
    "pay_bill_footer_text": "Generated under the signature of the Chief Officer.",
    "nps_employee_account_head": "8342-NPS-EMP",
    "nps_employer_account_head": "8342-NPS-EMR",
    "head_of_account": {
        "demand_number": "D-08",
        "major_head": "2217",
        "sub_head": "05",
        "detailed_head": "01",
    },
    "bank_advice_recipient": {
        "bank_name": "Bank of Maharashtra",
        "branch": "Shaharpur Main",
        "address_lines": ["Gandhi Chowk, Shaharpur 442001"],
    },
    "gpf_remittance_profiles": {
        "mumbai": {
            "office_name": "Accounts Officer (GPF), Mumbai",
            "address_lines": ["GPF Bhavan, Bandra (E), Mumbai 400051"],
            "account_code": "8009-GPF-MUM",
            "authority_text": "GPF (CS) Rules",
        },
        "nagpur": {
            "office_name": "Accounts Officer (GPF), Nagpur",
            "address_lines": ["Civil Lines, Nagpur 440001"],
            "account_code": "8009-GPF-NAG",
            "authority_text": "GPF (CS) Rules",
        },
    },
    "signatories": [
        {"role": "maker", "name": "S. Deshmukh", "designation": "Senior Clerk (Accounts)"},
        {"role": "checker", "name": "R. Kulkarni", "designation": "Accountant"},
        {"role": "approving_officer", "name": "A. Pawar", "designation": "Chief Accounts Officer"},
        {"role": "final_approver", "name": "M. Shah", "designation": "Chief Officer"},
    ],
}


def _run_metadata(key: str) -> dict[str, Any]:
    """Complete per-run report metadata so canonical export readiness passes."""
    year, month = int(key[:4]), int(key[5:7])
    return {
        "bill_number": f"PB-{key}-001",
        "bill_date": f"{year}-{month:02d}-10",
        "payment_date": f"{year}-{month:02d}-15",
        "token_number": f"TKN-{year % 100}{month:02d}1",
        "token_date": f"{year}-{month:02d}-11",
        "voucher_number": f"VCH-{year % 100}{month:02d}1",
        "voucher_date": f"{year}-{month:02d}-12",
        "bank_advice_number": f"BA-{year % 100}{month:02d}1",
        "bank_advice_date": f"{year}-{month:02d}-12",
        "approval_note_number": f"AN-{year % 100}{month:02d}1",
        "approval_note_date": f"{year}-{month:02d}-09",
    }


# One run per period; the dict value is the workflow state the seed leaves it in.
PERIOD_PLAN: tuple[tuple[int, int, str], ...] = (
    (2026, 4, "posted_closed"),
    (2026, 5, "posted"),
    (2026, 6, "approved"),
    (2026, 7, "submitted"),
    (2026, 8, "rejected"),
    (2026, 9, "calculated"),
)


def _login(client: httpx.Client, email: str) -> dict[str, Any]:
    """Sign in as ``email`` via the UI's password endpoint (dev auth accepts any password)."""
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    for _ in range(10):
        resp = client.post("/api/auth/login/password", json={"email": email, "password": "uat"})
        if resp.status_code != 429:
            break
        print("  login rate-limited (5/min); waiting 65s…")
        time.sleep(65)
    if resp.status_code != 204:
        raise SeedError(f"login {email}: {resp.status_code} {resp.text}")
    me = _require(client.get("/api/auth/me"), context=f"GET /api/auth/me as {email}")
    assert isinstance(me, dict)
    if me.get("access_state") != "active":
        raise SeedError(f"{email} has no active membership (access_state={me.get('access_state')})")
    csrf = client.cookies.get("accord_csrf")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    print(f"Signed in as {email} ({me.get('role')})")
    return me


def _create_org_structure(client: httpx.Client) -> tuple[dict[str, UUID], list[UUID]]:
    fixture = load_june_fixture()
    office_ids: dict[str, UUID] = {}
    for office in fixture.organization.offices:
        body = _require(
            client.post(
                "/api/offices", json={"name": office.name, "jurisdiction": office.jurisdiction}
            ),
            context=f"create office {office.name}",
        )
        assert isinstance(body, dict)
        office_ids[office.fixture_id] = UUID(body["id"])
    # An office with no staff exercises empty-state paths in pickers and reports.
    _require(
        client.post(
            "/api/offices",
            json={"name": "Synthetic Ward Office (no staff)", "jurisdiction": "other"},
        ),
        context="create empty office",
    )
    post_ids: list[UUID] = []
    for index, ((designation, class_name), (heading, strength, vacant, scale)) in enumerate(
        zip(DESIGNATIONS, POST_EXPORT_FIELDS), start=1
    ):
        body = _require(
            client.post(
                "/api/posts",
                json={
                    "designation": designation,
                    "class_name": class_name,
                    "pay_bill_heading": heading,
                    "display_order": index,
                    "sanctioned_strength": strength,
                    "vacant_count": vacant,
                    "pay_scale": scale,
                },
            ),
            context=f"create post {designation}",
        )
        assert isinstance(body, dict)
        post_ids.append(UUID(body["id"]))
    print(f"  {len(office_ids) + 1} offices, {len(post_ids)} posts")
    return office_ids, post_ids


def _clone(template: EmployeeSeed, index: int) -> EmployeeSeed:
    """Derive synthetic employee ``index`` (1-based) from a sanitized template."""
    number = f"S{index:04d}"
    name = f"{FIRST_NAMES[index % len(FIRST_NAMES)]} {LAST_NAMES[(index // 7) % len(LAST_NAMES)]}"
    if index % 97 == 0:
        # Long and non-ASCII names exercise truncation and font coverage in UI/exports.
        name = f"{name} Synthetic-Very-Long-Middle-Name-For-Layout-Testing"
    if index % 89 == 0:
        name = f"सिंथेटिक कर्मचारी {index}"
    scale = Decimal(1) + Decimal(index % 9) / Decimal(100)
    lines = [
        replace(line, amount=(line.amount * scale / 100).quantize(Decimal(1), ROUND_HALF_UP) * 100)
        if line.component_code == BASIC_CODE
        else line
        for line in template.lines
    ]
    return replace(
        template,
        fixture_id=number,
        name=name,
        sevarth_id=f"SYNS{index:06d}",
        pan=f"ZZZPZ{index:04d}Z",
        bank_account=f"{900000000000 + index:014d}",
        ifsc=f"SYNT{index % 1000000:07d}",
        gpf_account=(
            f"SYNGPF/{template.gpf_account.split('/')[1]}/{index:05d}"
            if template.gpf_account
            else None
        ),
        pran=f"9{index:011d}" if template.pran else None,
        epf_number=f"SYNTEPF/{index:05d}/UAN" if template.epf_number else None,
        lines=lines,
    )


def _seed_employees(
    client: httpx.Client,
    *,
    count: int,
    office_ids: dict[str, UUID],
    post_ids: list[UUID],
    component_ids: dict[str, UUID],
) -> list[UUID]:
    templates = load_june_fixture().employees
    employee_ids: list[UUID] = []
    started = time.monotonic()
    for index in range(1, count + 1):
        employee = _clone(templates[(index - 1) % len(templates)], index)
        employee_id = _create_employee(
            client,
            employee,
            office_ids=office_ids,
            post_id=post_ids[index % len(post_ids)],
        )
        _seed_employee_amounts(
            client, employee, employee_id=employee_id, component_ids=component_ids
        )
        employee_ids.append(employee_id)
        if index % 50 == 0:
            print(f"  {index}/{count} employees ({time.monotonic() - started:.0f}s)")
    return employee_ids


def _create_runs(client: httpx.Client, employee_ids: list[UUID]) -> dict[str, dict[str, str]]:
    runs: dict[str, dict[str, str]] = {}
    for year, month, target in PERIOD_PLAN:
        period = _require(
            client.post("/api/payroll-periods", json={"period_year": year, "period_month": month}),
            context=f"create period {year}-{month:02d}",
        )
        assert isinstance(period, dict)
        run = _require(
            client.post("/api/payroll-runs", json={"period_id": period["id"]}),
            context=f"create run {year}-{month:02d}",
        )
        assert isinstance(run, dict)
        runs[f"{year}-{month:02d}"] = {
            "run_id": run["id"],
            "period_id": period["id"],
            "target": target,
        }
    return runs


def _prepare_runs(
    client: httpx.Client, runs: dict[str, dict[str, str]], employee_ids: list[UUID]
) -> None:
    for key, run in runs.items():
        run_id = run["run_id"]
        roster = []
        for i, employee_id in enumerate(employee_ids):
            entry: dict[str, Any] = {"employee_id": str(employee_id), "payable_days": "30.00"}
            if key == "2026-09" and i % 40 == 0:
                entry["payable_days"] = "15.00"
            roster.append(entry)
        _require(
            client.put(f"/api/payroll-runs/{run_id}/roster", json={"employees": roster}),
            context=f"roster {key}",
        )
        if key == "2026-09":
            # ``one_time`` and ``exception`` must target a component absent from
            # the employee's instructions (they add a line; a second source for
            # one code duplicates); ``override`` must target a component already
            # calculated (it replaces it). employee_ids are seeded in template
            # order, so an override goes on OTHER_ALLOWANCE only for employees
            # whose template has that line.
            templates = load_june_fixture().employees
            override_pool = [
                eid
                for i, eid in enumerate(employee_ids)
                if any(
                    line.component_code == "OTHER_ALLOWANCE"
                    for line in templates[i % len(templates)].lines
                )
            ]
            for i, employee_id in enumerate(employee_ids[:12]):
                kind, code, amount = (
                    ("one_time", "WASH_ALLOWANCE", "2500.00"),
                    ("exception", "CLA", "750.00"),
                    ("override", "OTHER_ALLOWANCE", "1500.00"),
                )[i % 3]
                if kind == "override":
                    if not override_pool:
                        break
                    employee_id = override_pool.pop(0)
                _require(
                    client.put(
                        f"/api/payroll-runs/{run_id}/inputs/{employee_id}/{code}",
                        json={
                            "input_kind": kind,
                            "amount": amount,
                            "reason": f"UAT seed {kind} input",
                        },
                    ),
                    context=f"input {key} {employee_id}",
                )
        started = time.monotonic()
        calc = _require(
            client.post(
                f"/api/payroll-runs/{run_id}/calculate",
                headers={"Idempotency-Key": f"seed-calc-{uuid.uuid4()}"},
            ),
            context=f"calculate {key}",
        )
        assert isinstance(calc, dict)
        totals = calc.get("totals", {})
        print(
            f"  {key} calculated in {time.monotonic() - started:.1f}s "
            f"net={totals.get('net_payable')} gross={totals.get('gross_total')}"
        )
        if run["target"] == "calculated":
            continue
        _require(client.post(f"/api/payroll-runs/{run_id}/validate"), context=f"validate {key}")
        # Posted runs freeze the report snapshot at post time, so the export
        # metadata must be written before the run leaves the preparer.
        _require(
            client.put(f"/api/payroll-runs/{run_id}/report-metadata", json=_run_metadata(key)),
            context=f"report metadata {key}",
        )
        _require(
            client.post(
                f"/api/payroll-runs/{run_id}/submit",
                json={"reason": f"{key} payroll ready for approval"},
            ),
            context=f"submit {key}",
        )


def _approve_runs(client: httpx.Client, runs: dict[str, dict[str, str]]) -> None:
    for key, run in runs.items():
        if run["target"] in {"posted_closed", "posted", "approved"}:
            _require(
                client.post(
                    f"/api/payroll-runs/{run['run_id']}/approve", json={"reason": f"{key} approved"}
                ),
                context=f"approve {key}",
            )
        elif run["target"] == "rejected":
            _require(
                client.post(
                    f"/api/payroll-runs/{run['run_id']}/reject",
                    json={"reason": f"{key} rejected: DA arrears need re-verification"},
                ),
                context=f"reject {key}",
            )


def _post_runs(client: httpx.Client, runs: dict[str, dict[str, str]]) -> None:
    for key, run in runs.items():
        if run["target"] not in {"posted_closed", "posted"}:
            continue
        _require(
            client.post(
                f"/api/payroll-runs/{run['run_id']}/post",
                headers={"Idempotency-Key": f"seed-post-{uuid.uuid4()}"},
            ),
            context=f"post {key}",
        )
        if run["target"] == "posted_closed":
            _require(
                client.post(f"/api/payroll-periods/{run['period_id']}/close"),
                context=f"close {key}",
            )
        print(f"  {key} {run['target']}")


def seed(args: argparse.Namespace) -> None:
    fixture = load_june_fixture()
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=600.0) as client:
        _login(client, args.admin_email)
        existing = _require(
            client.get("/api/employees", params={"size": 1}), context="list employees"
        )
        assert isinstance(existing, dict)
        if int(existing.get("total") or 0) > 0:
            raise SeedError(
                f"Org already has {existing['total']} employees; seed into an empty org."
            )
        print("Org structure…")
        office_ids, post_ids = _create_org_structure(client)
        _require(client.put("/api/report-profile", json=REPORT_PROFILE), context="report profile")
        print("Pay components…")
        component_ids = _create_components(client, fixture)
        print(f"Employees ({args.employees})…")
        employee_ids = _seed_employees(
            client,
            count=args.employees,
            office_ids=office_ids,
            post_ids=post_ids,
            component_ids=component_ids,
        )
        runs = _create_runs(client, employee_ids)

        _login(client, args.preparer_email)
        print("Rosters, inputs, calculate, submit…")
        _prepare_runs(client, runs, employee_ids)

        _login(client, args.approver_email)
        print("Approve / reject…")
        _approve_runs(client, runs)

        _login(client, args.releaser_email)
        print("Post / close…")
        _post_runs(client, runs)

    print("Done:")
    for key, run in runs.items():
        print(f"  {key}  {run['target']:<14} run={run['run_id']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--employees", type=int, default=480)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--preparer-email", required=True)
    parser.add_argument("--approver-email", required=True)
    parser.add_argument("--releaser-email", required=True)
    args = parser.parse_args()
    if args.employees < 1 or args.employees > 9999:
        parser.error("--employees must be between 1 and 9999")
    try:
        seed(args)
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
