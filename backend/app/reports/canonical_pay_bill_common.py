"""Shared canonical Pay Bill contract constants and DTO accessors."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from app.reports.base import ReportDTO

_ARIAL_PATH = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
_ARIAL_BOLD_PATH = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
_PDF_FONT_FAMILY = "Arial" if _ARIAL_PATH.exists() else "NotoSans"


def _text_preserving_zero(value: object) -> str:
    return "" if value is None or value == "" else str(value)


# Exact A:AB widths extracted from the accepted workbook contract.
_PAY_BILL_WIDTHS = (
    5.33203125,
    37.6640625,
    12,
    11.6640625,
    8.6640625,
    13.33203125,
    10,
    11.1640625,
    10,
    9.5,
    12,
    12,
    14.83203125,
    12.83203125,
    19.5,
    14,
    10.83203125,
    10.6640625,
    11.6640625,
    9,
    11.1640625,
    12.33203125,
    9.6640625,
    9.33203125,
    11.6640625,
    12,
    11.6640625,
    13.6640625,
)

_PAY_BILL_HEADERS = (
    "Sr. No.",
    "Employee Name",
    "Basic Pay / Dearness Pay",
    "Dearness Allowance / Difference",
    "City Compensatory Allowance",
    "House Rent Allowance",
    "Wash / Child / Other Allowances",
    "Other Reimbursement / Salary or Increment Difference",
    "Additional Conveyance / Allowance",
    "TA / PTA / Honorarium",
    "Gross Salary",
    "Employer Share",
    "Festival Advance / Other Recovery",
    "Gross Salary After Recovery",
    "Account Number",
    "Subscription / Refund / Arrears",
    "Pension Employer Share",
    "Pension Employee Share",
    "HBA / Motor / Other Advance",
    "Flood-Affected Advance",
    "Income Tax",
    "PLI / CGIS / MSI / GIS",
    "House Rent / Service Charges / Arrears",
    "Professional Tax / Difference",
    "Co-operative Recovery",
    "Total Deductions",
    "Net Amount Payable",
    "Remarks",
)


def _column_index(section, key: str) -> int:
    for index, column in enumerate(section.columns):
        if column.key == key:
            return index
    raise ValueError(f"Canonical Pay Bill DTO is missing column {key!r}.")


def _row_value(section, row, key: str):
    return row[_column_index(section, key)]


def _organization_label(dto: ReportDTO) -> str:
    profile = dto.metadata.get("report_profile", {})
    if isinstance(profile, Mapping):
        return str(profile.get("legal_name") or profile.get("office_name") or dto.organization_name)
    return dto.organization_name


def _excel_date(value: object) -> date | datetime | None:
    if isinstance(value, (date, datetime)):
        return value
    if value:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None
    return None
