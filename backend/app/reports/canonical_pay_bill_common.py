"""Shared canonical Pay Bill contract constants and DTO accessors."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from app.reports.base import ReportDTO
from app.reports.canonical_pay_bill_allocation import V3_MONEY_KEYS

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


def _post_group(section, row) -> tuple[str, str, str, str, str]:
    """Return the rendered post-group tuple for one register row.

    The tuple identity (``post_group_key`` first) is what the renderers split
    roster groups on; ``_matches_reference_layout`` and the readiness capacity
    check must count boundaries on exactly the same value.
    """
    return (
        str(_row_value(section, row, "post_group_key") or ""),
        str(_row_value(section, row, "post_title") or "Unassigned Post"),
        _text_preserving_zero(_row_value(section, row, "sanctioned_posts")),
        _text_preserving_zero(_row_value(section, row, "vacant_posts")),
        str(_row_value(section, row, "pay_scale") or ""),
    )


def _post_group_label(group: tuple[str, str, str, str, str]) -> str:
    """Canonical group-header text shared by the Excel and PDF renderers."""
    label = f"Post of {group[1]}"
    strength: list[str] = []
    if group[2]:
        strength.append(f"Total Posts {group[2]}")
    if group[3]:
        strength.append(f"Vacant {group[3]}")
    if strength:
        label += f" ({'. '.join(strength)})"
    if group[4]:
        label += f" - Scale {group[4]}"
    return label


# Accepted-reference roster topology: 28 employees with post-group boundaries at
# serials 1, 2, 3, 16, 25, 26 and detail blocks anchored at these fixed rows.
_REFERENCE_GROUP_STARTS = (1, 2, 3, 16, 25, 26)
_REFERENCE_DETAIL_ANCHORS = (
    10,
    18,
    25,
    31,
    37,
    43,
    49,
    55,
    68,
    74,
    80,
    86,
    92,
    98,
    104,
    111,
    117,
    123,
    135,
    141,
    147,
    153,
    159,
    165,
    172,
    179,
    185,
    191,
)

# Fixed page ends keyed by employee serial; each page reserves six trailing
# rows for the canonical subtotal block plus one "Total Rs." row.
_PAGE_END_BY_SERIAL = {8: 67, 18: 134}
_FIRST_DATA_ROW = 9
_EMPLOYEE_BLOCK_ROWS = 6
_GROUP_HEADER_ROWS = 1


def _matches_reference_layout(section) -> bool:
    """Use the source layout only for its explicit roster-group topology."""
    group_starts: list[int] = []
    current_group = None
    for serial, row in enumerate(section.rows, start=1):
        group = _post_group(section, row)
        if group != current_group:
            group_starts.append(serial)
            current_group = group
    return (
        len(section.rows) == len(_REFERENCE_DETAIL_ANCHORS)
        and tuple(group_starts) == _REFERENCE_GROUP_STARTS
    )


def pay_bill_page_capacity_errors(
    ordered_groups: list[tuple[str, str, str, str, str]],
) -> list[str]:
    """Describe where a generic roster overflows the canonical fixed pages.

    Non-reference rosters lay out employee blocks sequentially (six rows per
    employee plus one row per post-group header) and still hit the fixed page
    ends at serials 8 and 18. Return one message per overflowing page so
    readiness can surface the constraint instead of the renderer failing.
    """
    boundaries = {
        serial
        for serial, group in enumerate(ordered_groups, start=1)
        if serial == 1 or group != ordered_groups[serial - 2]
    }
    errors: list[str] = []
    page_starts = {8: _FIRST_DATA_ROW, 18: _PAGE_END_BY_SERIAL[8] + 1}
    for serial, page_end in _PAGE_END_BY_SERIAL.items():
        if len(ordered_groups) < serial:
            continue
        first_serial = 1 if serial == 8 else 9
        rows_used = (
            page_starts[serial]
            + (serial - first_serial + 1) * _EMPLOYEE_BLOCK_ROWS
            + sum(1 for boundary in boundaries if first_serial <= boundary <= serial)
            * _GROUP_HEADER_ROWS
        )
        summary_start = page_end - _EMPLOYEE_BLOCK_ROWS + 1
        if rows_used > summary_start:
            errors.append(
                f"Pay Bill page ending at row {page_end} overflows: "
                f"employees {first_serial}-{serial} occupy rows through {rows_used - 1} "
                f"(limit {summary_start}); reduce post-group boundaries early in the roster."
            )
    return errors


def _reconcile_pay_bill_totals(section) -> None:
    """Verify per-key column sums cross-foot against the DTO totals row."""
    computed_totals = {
        key: sum(
            (Decimal(str(_row_value(section, item, key) or 0)) for item in section.rows),
            Decimal("0"),
        )
        for key in V3_MONEY_KEYS
    }
    if section.totals is None:
        return
    expected = dict(zip((column.key for column in section.columns), section.totals, strict=True))
    mismatches = {
        key: (computed_totals[key], Decimal(str(expected[key] or 0)))
        for key in computed_totals
        if computed_totals[key] != Decimal(str(expected[key] or 0))
    }
    if mismatches:
        raise ValueError(f"Canonical Pay Bill grand totals do not match DTO totals: {mismatches}")
