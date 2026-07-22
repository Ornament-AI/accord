#!/usr/bin/env python3
"""Extract a PII-free structural contract from the canonical payroll workbook.

The source workbook contains real employee data and broken cached formulas. This
script records layout and workbook topology only. It never copies employee cell
values into the checked-in contract. Known source defects and finance-approved
June totals are documented as explicit normalization rules below.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": REL_NS, "pr": PACKAGE_REL_NS}

CANONICAL_SHEET_NAMES = (
    "office tip",
    "Bank Tip",
    "PaySlip",
    " Face ",
    "Pay Bill",
    "Income Tax",
    "GPF-Nagpur",
    "P.T.",
    "GPF-Mumbai",
    "GPF-IV",
    "GIS",
    "HBA Ad",
    "Motor car Ad",
    "Motor cycale Ad (2)",
    "Pension Sub (2)",
    "Festival",
    "WORLI",
    "Mumbai",
)

PAY_BILL_COLUMNS = (
    "Sr. No.",
    "Employee name",
    "Basic / DP / grade pay",
    "DA / DA difference",
    "CLA",
    "HRA",
    "Wash / child / other allowance",
    "Reimbursement / salary or increment difference",
    "Additional conveyance / allowance",
    "TA / PTA / honorarium",
    "Gross salary",
    "Employer share",
    "Festival / overpayment recovery",
    "Gross after recovery",
    "GPF account number",
    "GPF subscription / refund / arrears",
    "Pension employer share",
    "Pension employee share",
    "Advance recovery",
    "Flood-affected advance",
    "Income tax",
    "PLI / CGIS / MSI / GIS",
    "HRR / service charge / arrears",
    "Professional tax / difference",
    "Co-operative recovery",
    "Total deductions",
    "Net amount payable",
    "Remarks",
)

PAY_BILL_FORMULA_ROLES = {
    "gross_salary": "sum(columns 3 through 10)",
    "gross_after_recovery": "gross_salary + employer_share - gross_recovery",
    "total_deductions": "sum(columns 16 through 25)",
    "net_amount_payable": "gross_after_recovery - total_deductions",
    "page_and_grand_totals": "sum each visible money column",
}

JUNE_2026_NORMALIZED_TOTALS = {
    "employee_count": 28,
    "salary_earnings": "5073200.00",
    "employer_share": "29785.00",
    "gross_bill": "5102985.00",
    "total_deductions": "1264890.00",
    "net_payable": "3838095.00",
}

# Aggregate-only semantic roles from the canonical workbook.  Coordinates are
# safe to check in because they describe the form, never an employee value.
CANONICAL_SEMANTICS = {
    "front_sheets": {
        "office tip": {
            "body": {
                "rows": [8, 35],
                "serial_column": "B",
                "required_columns": ["C", "D"],
                "expected_count": 28,
            },
            "totals": [{"cell": "E36", "sum_range": "E8:E35", "expected": "3838095.00"}],
        },
        "Bank Tip": {
            "body": {
                "rows": [14, 41],
                "serial_column": "B",
                "required_columns": ["C", "D", "E", "F"],
                "expected_count": 28,
            },
            "totals": [{"cell": "G42", "sum_range": "G14:G41", "expected": "3991038.00"}],
        },
        "PaySlip": {
            "block_starts": [2 + 19 * index for index in range(28)],
            "expected_total": "3991038.00",
            "normalized_structure": {
                "used_range": "A2:X531",
                "print_area": "A1:X531",
                "stride": 19,
                "block_height": 17,
                "default_row_height": 24,
                "start_row_height": 47.25,
                "total_row_height": 36,
                "net_row_height": 54,
                "column_widths": [
                    5.1640625,
                    16.6640625,
                    4.33203125,
                    5.33203125,
                    9.5,
                    15.6640625,
                    23,
                    6.6640625,
                    3.83203125,
                    6.6640625,
                    8.1640625,
                    27.1640625,
                    12.33203125,
                    17.5,
                    10.6640625,
                    2.6640625,
                    6.33203125,
                    2.6640625,
                    16.6640625,
                    5,
                    10.6640625,
                    10.5,
                    17.6640625,
                    9.83203125,
                ],
                "page_setup": {"orientation": "landscape", "scale": 52},
            },
        },
        " Face ": {
            "formula_roles": {
                "I22": "=I18-I19+I20",
                "I36": "=SUM(I25:I35)",
                "I49": "=SUM(I37:I48)",
                "I51": "=I36+I49",
                "I52": "=I22-I51",
                "G67": "=I22",
                "G69": "=I52",
                "D76": "=I36",
                "D77": "=I49",
                "D78": "=SUM(D76:D77)",
            },
            "totals": [
                {"cell": "I22", "expected": "5102985.00"},
                {"cell": "I51", "expected": "1264890.00"},
                {"cell": "I52", "expected": "3838095.00"},
            ],
        },
    },
    "schedules": {
        "Income Tax": {
            "body": {
                "rows": [5, 29],
                "serial_column": "A",
                "required_columns": ["B", "C", "D"],
                "expected_count": 25,
            },
            "totals": [{"cell": "F30", "sum_range": "F5:F29", "expected": "550700.00"}],
        },
        "GPF-Nagpur": {
            "body": {
                "rows": [36, 40],
                "serial_column": "A",
                "required_columns": ["B", "C", "D"],
                "expected_count": 5,
            },
            "destination": {
                "cell": "B20",
                "jurisdiction": "nagpur",
                "required_cells": ["B20", "A23", "A27"],
            },
            "row_formula": {"target_column": "I", "source_columns": ["F", "G"]},
            "totals": [{"cell": "I41", "sum_range": "I36:I40", "expected": "115000.00"}],
        },
        "P.T.": {
            "body": {
                "rows": [5, 32],
                "serial_column": "B",
                "required_columns": ["C", "D"],
                "expected_count": 28,
            },
            "totals": [{"cell": "E33", "sum_range": "E5:E32", "expected": "5600.00"}],
        },
        "GPF-Mumbai": {
            "body": {
                "rows": [36, 45],
                "serial_column": "A",
                "required_columns": ["B", "C", "D"],
                "expected_count": 10,
            },
            "destination": {
                "cell": "B20",
                "jurisdiction": "mumbai",
                "required_cells": ["B20", "A23", "A27"],
            },
            "row_formula": {"target_column": "I", "source_columns": ["F", "G"]},
            "totals": [{"cell": "I46", "sum_range": "I36:I45", "expected": "165000.00"}],
        },
        "GPF-IV": {
            "body": {
                "rows": [11, 22],
                "serial_column": "A",
                "required_columns": ["B", "C"],
                "amount_columns": ["D", "E", "G"],
                "expected_count": 0,
            },
            "totals": [
                {"cell": "D23", "sum_range": "D11:D22", "expected": "0.00"},
                {"cell": "E23", "sum_range": "E11:E22", "expected": "0.00"},
                {"cell": "G23", "sum_range": "G11:G22", "expected": "0.00"},
            ],
        },
        "GIS": {
            "body": {
                "rows": [7, 32],
                "serial_column": "B",
                "required_columns": ["C", "D"],
                "expected_count": 26,
            },
            "totals": [{"cell": "E33", "sum_range": "E7:E32", "expected": "22440.00"}],
        },
        "HBA Ad": {
            "body": {
                "rows": [5, 10],
                "serial_column": "A",
                "required_columns": ["B", "C", "D"],
                "expected_count": 6,
            },
            "totals": [{"cell": "E12", "sum_range": "E5:E11", "expected": "72723.00"}],
        },
        "Motor car Ad": {
            "body": {
                "rows": [6, 6],
                "serial_column": "A",
                "required_columns": ["B", "C"],
                "amount_columns": ["E"],
                "expected_count": 0,
            },
            "totals": [{"cell": "E7", "sum_range": "E6:E6", "expected": "0.00"}],
        },
        "Motor cycale Ad (2)": {
            "body": {
                "rows": [6, 6],
                "serial_column": "A",
                "required_columns": ["B", "C"],
                "amount_columns": ["E"],
                "expected_count": 0,
            },
            "totals": [{"cell": "E7", "sum_range": "E6:E6", "expected": "0.00"}],
        },
        "Pension Sub (2)": {
            "block_starts": [11 + 3 * index for index in range(10)],
            "formula_roles": {
                "H41": "=SUM(H11:H40)",
                "I41": "=SUM(I11:I40)",
                "I44": "=H41",
                "I45": "=I41",
                "I46": "=SUM(I42:I45)",
                "C47": "=I46",
            },
            "required_cells": ["B42", "B43", "B44", "B45"],
            "totals": [{"cell": "I46", "expected": "262188.00"}],
        },
        "Festival": {
            "body": {
                "rows": [5, 29],
                "serial_column": "A",
                "required_columns": ["B", "C"],
                "amount_columns": ["E"],
                "expected_count": 0,
            },
            "totals": [{"cell": "E30", "sum_range": "E5:E29", "expected": "0.00"}],
        },
        "WORLI": {
            "body": {
                "rows": [8, 8],
                "serial_column": "A",
                "required_columns": ["B", "C", "D"],
                "expected_count": 1,
            },
            "row_formula": {"target_column": "H", "source_columns": ["F", "G"]},
            "totals": [{"cell": "H8", "expected": "1250.00"}],
        },
        "Mumbai": {
            "body": {
                "rows": [8, 10],
                "serial_column": "A",
                "required_columns": ["B", "C", "D"],
                "expected_count": 3,
            },
            "row_formula": {"target_column": "J", "source_columns": ["F", "G", "H", "I"]},
            "totals": [{"cell": "J11", "sum_range": "J8:J10", "expected": "10419.00"}],
        },
    },
    "reconciliations": [
        {
            "name": "net payable",
            "members": ["office tip!E36", " Face !I52", "Pay Bill!AA208"],
            "expected": "3838095.00",
            "operation": "equal",
        },
        {
            "name": "GPF recovery",
            "members": ["GPF-Nagpur!I41", "GPF-Mumbai!I46"],
            "target": "Pay Bill!P208",
            "expected": "280000.00",
            "operation": "sum",
        },
        {
            "name": "NPS contribution",
            "members": ["Pension Sub (2)!I46"],
            "target_members": [
                "Pay Bill!Q122",
                "Pay Bill!R122",
                "Pay Bill!Q128",
                "Pay Bill!R128",
                "Pay Bill!Q140",
                "Pay Bill!R140",
                "Pay Bill!Q146",
                "Pay Bill!R146",
                "Pay Bill!Q152",
                "Pay Bill!R152",
                "Pay Bill!Q158",
                "Pay Bill!R158",
                "Pay Bill!Q164",
                "Pay Bill!R164",
                "Pay Bill!Q170",
                "Pay Bill!R170",
                "Pay Bill!Q177",
                "Pay Bill!R177",
                "Pay Bill!Q184",
                "Pay Bill!R184",
            ],
            "expected": "262188.00",
            "operation": "sum",
        },
        {
            "name": "payslip disbursement",
            "members": [f"PaySlip!F{2 + 19 * index + 14}" for index in range(28)],
            "target": "Bank Tip!G42",
            "expected": "3991038.00",
            "operation": "sum",
        },
        {
            "name": "bank disbursement",
            "members": ["Pay Bill!AA208", "Pension Sub (2)!I41"],
            "target": "Bank Tip!G42",
            "expected": "3991038.00",
            "operation": "sum",
        },
        {
            "name": "accommodation recovery",
            "members": ["WORLI!H8", "Mumbai!J11"],
            "target": "Pay Bill!W208",
            "expected": "11669.00",
            "operation": "sum",
        },
        {
            "name": "income tax",
            "members": ["Income Tax!F30", "Pay Bill!U208"],
            "expected": "550700.00",
            "operation": "equal",
        },
        {
            "name": "professional tax",
            "members": ["P.T.!E33", "Pay Bill!X208"],
            "expected": "5600.00",
            "operation": "equal",
        },
        {
            "name": "GIS",
            "members": ["GIS!E33", "Pay Bill!V208"],
            "expected": "22440.00",
            "operation": "equal",
        },
        {
            "name": "advance recovery",
            "members": ["HBA Ad!E12", "Pay Bill!S208"],
            "expected": "72723.00",
            "operation": "equal",
        },
    ],
}

KNOWN_SOURCE_NORMALIZATIONS = (
    {
        "cell": "Pay Bill!C172",
        "source_problem": "non-numeric text in the basic-pay cell",
        "rule": "recover basic pay 66000 from the employee block's Basic @ Rs. line",
    },
    {
        "range": "PaySlip",
        "source_problem": "deleted references produce cached #REF! values",
        "rule": "rebuild all 28 payslip blocks from posted facts; never copy broken references",
    },
    {
        "range": "formula-dependent totals",
        "source_problem": "employee 25 propagates cached #VALUE! values",
        "rule": "recalculate from normalized numeric facts and assert the approved June totals",
    },
    {
        "range": "WORLI!H8 and Mumbai!J8:J10",
        "source_problem": "row totals include informational foregone HRA",
        "rule": "exclude column E and recover only the actual accommodation charge buckets",
    },
    {
        "range": "Bank Tip!G42 and PaySlip disbursements",
        "source_problem": "the disbursement total is not the Pay Bill net total",
        "rule": "include off-bill NPS employer contribution and assert 3991038",
    },
    {
        "range": "Pension Sub (2)!I46",
        "source_problem": "the source amount-in-words total is stale",
        "rule": "recalculate employee 109245 plus employer 152943 contributions as 262188",
    },
)


def _qualified(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _target_path(target: str) -> str:
    normalized = PurePosixPath("xl") / target if not target.startswith("/xl/") else target[1:]
    return str(PurePosixPath(normalized))


def _workbook_parts(
    archive: zipfile.ZipFile,
) -> tuple[ET.Element, list[dict[str, Any]], dict[int, dict[str, str]]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall("pr:Relationship", NS)
    }

    sheets: list[dict[str, Any]] = []
    for index, sheet in enumerate(workbook.findall("m:sheets/m:sheet", NS)):
        relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
        sheets.append(
            {
                "index": index,
                "name": sheet.attrib["name"],
                "state": sheet.attrib.get("state", "visible"),
                "path": _target_path(rel_targets[relationship_id]),
            }
        )

    defined_names: dict[int, dict[str, str]] = {}
    for item in workbook.findall("m:definedNames/m:definedName", NS):
        local_sheet_id = item.attrib.get("localSheetId")
        if local_sheet_id is None or item.text is None:
            continue
        bucket = defined_names.setdefault(int(local_sheet_id), {})
        name = item.attrib.get("name")
        if name == "_xlnm.Print_Area":
            bucket["print_area"] = item.text
        elif name == "_xlnm.Print_Titles":
            bucket["print_titles"] = item.text
    return workbook, sheets, defined_names


def _integer(value: str | None) -> int | None:
    return None if value is None else int(value)


def _sheet_contract(
    archive: zipfile.ZipFile,
    sheet: dict[str, Any],
    defined_names: dict[int, dict[str, str]],
) -> dict[str, Any]:
    root = ET.fromstring(archive.read(sheet["path"]))
    dimension = root.find("m:dimension", NS)
    page_setup = root.find("m:pageSetup", NS)
    page_margins = root.find("m:pageMargins", NS)
    print_options = root.find("m:printOptions", NS)

    formula_count = 0
    cached_errors: dict[str, int] = {}
    for cell in root.findall("m:sheetData/m:row/m:c", NS):
        if cell.find("m:f", NS) is not None:
            formula_count += 1
        if cell.attrib.get("t") == "e":
            error = cell.findtext("m:v", default="", namespaces=NS)
            cached_errors[error] = cached_errors.get(error, 0) + 1

    columns = []
    hidden_columns = []
    for column in root.findall("m:cols/m:col", NS):
        item: dict[str, Any] = {
            "min": int(column.attrib["min"]),
            "max": int(column.attrib["max"]),
        }
        if "width" in column.attrib:
            item["width"] = column.attrib["width"]
        if column.attrib.get("hidden") == "1":
            item["hidden"] = True
            hidden_columns.append([item["min"], item["max"]])
        columns.append(item)

    rows = []
    hidden_rows = []
    for row in root.findall("m:sheetData/m:row", NS):
        if "ht" not in row.attrib and row.attrib.get("hidden") != "1":
            continue
        item: dict[str, Any] = {"row": int(row.attrib["r"])}
        if "ht" in row.attrib:
            item["height"] = row.attrib["ht"]
        if row.attrib.get("hidden") == "1":
            item["hidden"] = True
            hidden_rows.append(item["row"])
        rows.append(item)

    def breaks(kind: str) -> list[int]:
        return [
            int(item.attrib["id"])
            for item in root.findall(f"m:{kind}/m:brk", NS)
            if item.attrib.get("man") == "1"
        ]

    contract: dict[str, Any] = {
        "name": sheet["name"],
        "state": sheet["state"],
        "used_range": None if dimension is None else dimension.attrib.get("ref"),
        **defined_names.get(sheet["index"], {}),
        "formula_count": formula_count,
        "cached_formula_errors": dict(sorted(cached_errors.items())),
        "merged_cells": [
            item.attrib["ref"] for item in root.findall("m:mergeCells/m:mergeCell", NS)
        ],
        "column_dimensions": columns,
        "row_dimensions": rows,
        "hidden_rows": hidden_rows,
        "hidden_columns": hidden_columns,
        "page_setup": {}
        if page_setup is None
        else {
            key.split("}")[-1]: value
            for key, value in page_setup.attrib.items()
            if key.split("}")[-1] != "id"
        },
        "page_margins": {} if page_margins is None else dict(page_margins.attrib),
        "print_options": {} if print_options is None else dict(print_options.attrib),
        "manual_row_breaks": breaks("rowBreaks"),
        "manual_column_breaks": breaks("colBreaks"),
    }
    return contract


def extract_contract(workbook_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(workbook_path) as archive:
        _workbook, sheets, defined_names = _workbook_parts(archive)
        names = tuple(item["name"] for item in sheets)
        if names != CANONICAL_SHEET_NAMES:
            raise ValueError(
                "Workbook sheet order does not match the canonical contract: "
                f"expected={CANONICAL_SHEET_NAMES!r}, actual={names!r}"
            )
        sheet_contracts = [_sheet_contract(archive, sheet, defined_names) for sheet in sheets]

    return {
        "contract_version": 1,
        "source_kind": "normalized MSIDC June 2026 payroll workbook",
        "pii_policy": "structure and approved totals only; no employee cell values",
        "sheets": sheet_contracts,
        "pay_bill": {
            "columns": list(PAY_BILL_COLUMNS),
            "header_groups": {
                "deductions": "O2:Z2",
                "adjustable_by_ag": "O3:T3",
                "adjustable_by_treasury": "U3:Z3",
            },
            "formula_roles": PAY_BILL_FORMULA_ROLES,
            "normalized_june_2026_totals": JUNE_2026_NORMALIZED_TOTALS,
        },
        "canonical_semantics": CANONICAL_SEMANTICS,
        "known_source_normalizations": list(KNOWN_SOURCE_NORMALIZATIONS),
    }


def _assert_no_pii(contract: dict[str, Any]) -> None:
    serialized = json.dumps(contract, ensure_ascii=False)
    forbidden = (
        re.compile(r"\b(?:Shri|Smt|Mr|Mrs)\.?\b", re.IGNORECASE),
        re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
        re.compile(r"\b(?:SBIN|UTIB|BARB|BKID)[A-Z0-9]{7}\b"),
    )
    for pattern in forbidden:
        if pattern.search(serialized):
            raise ValueError(f"PII-like value found in extracted contract: {pattern.pattern}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    contract = extract_contract(args.xlsx)
    _assert_no_pii(contract)
    rendered = json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
