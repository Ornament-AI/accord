"""Canonical v3 Pay Bill DTO construction."""

from __future__ import annotations

from typing import Any

from app.exceptions import ConflictError
from app.models.identity import Organization
from app.models.payroll_runs import PayrollPeriod
from app.reports.base import ColumnKind, ReportColumn, ReportContext, ReportDTO, TableSection
from app.reports.posted_run import ZERO, money, period_label
from app.reports.canonical_pay_bill_allocation import (
    V3_MONEY_KEYS,
    line_classification,
    normalize_register_column,
    post_metadata,
)

REPORT_TYPE_PAY_BILL = "pay_bill"


_V3_COLUMNS = (
    ReportColumn("employee_number", "Employee No."),
    ReportColumn("name", "Name"),
    ReportColumn("designation", "Designation"),
    ReportColumn("post_group_key", "Post Group Key"),
    ReportColumn("post_title", "Post"),
    ReportColumn("sanctioned_posts", "Sanctioned Posts"),
    ReportColumn("vacant_posts", "Vacant Posts"),
    ReportColumn("pay_scale", "Pay Scale"),
    ReportColumn("post_display_order", "Post Display Order", ColumnKind.COUNT),
    ReportColumn("pan", "PAN"),
    ReportColumn("account_label", "Account Label"),
    ReportColumn("gpf_account_number", "Account Number"),
    ReportColumn("remarks", "Remarks"),
    *(ReportColumn(key, key, ColumnKind.MONEY) for key in V3_MONEY_KEYS),
)


def build_v3_pay_bill_dto(
    *,
    ctx: ReportContext,
    version: Any,
    period: PayrollPeriod,
    org: Organization,
    packed: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> ReportDTO:
    """Build immutable row data for the canonical 28-column formatter."""
    identities = snapshot.get("employee_identity") or {}
    if not isinstance(identities, dict):
        raise ConflictError("Immutable report snapshot employee identity is malformed.")

    catalog_by_code: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("component_catalog") or []:
        if isinstance(item, dict) and item.get("code"):
            catalog_by_code[str(item["code"])] = item

    ordered_rows: list[tuple[tuple[int, str, str], tuple[Any, ...]]] = []
    detail_by_employee: dict[str, list[tuple[Any, ...]]] = {}
    footer = {key: ZERO for key in V3_MONEY_KEYS}
    for packed_item in packed:
        result = packed_item["result"]
        identity = identities.get(str(result["employee_id"])) or {}
        if not isinstance(identity, dict):
            raise ConflictError("Immutable report snapshot contains malformed employee identity.")

        amounts = {key: ZERO for key in V3_MONEY_KEYS}
        detail_lines: list[tuple[Any, ...]] = []
        for line in packed_item["lines"]:
            code = str(line["component_code"])
            trace = line["trace"] or {}
            classification = line_classification(line)
            if classification == "informational" or code == "FOREGONE_HRA":
                continue
            amount = money(line["amount"])
            catalog_item = catalog_by_code.get(code) or {}
            raw_register_column = catalog_item.get("register_column")
            target = normalize_register_column(raw_register_column)
            if target is None:
                if amount == ZERO:
                    continue
                raise ConflictError(
                    f"Component {code!r} is not mapped to a canonical Pay Bill column.",
                    details={
                        "component_code": code,
                        "register_column": raw_register_column,
                        "employee_number": str(result["employee_number"]),
                    },
                )
            if target == "m_recovery" and amount < ZERO:
                amount = -amount
            amounts[target] = money(amounts[target] + amount)
            if amount != ZERO:
                detail_lines.append(
                    (
                        str(result["employee_number"]),
                        target,
                        code,
                        str(catalog_item.get("name") or code),
                        int(
                            line["sequence"]
                            if catalog_item.get("display_order") is None
                            else catalog_item["display_order"]
                        ),
                        str(trace.get("reason") or ""),
                        str(trace.get("service_period") or ""),
                        amount,
                    )
                )

        for bucket in V3_MONEY_KEYS:
            bucket_lines = [line for line in detail_lines if line[1] == bucket]
            if len(bucket_lines) > 5:
                raise ConflictError(
                    "Canonical Pay Bill employee block has more than five detail lines.",
                    details={
                        "employee_number": str(result["employee_number"]),
                        "register_column": bucket,
                        "line_count": len(bucket_lines),
                    },
                )
            if sum((line[7] for line in bucket_lines), ZERO) != amounts[bucket]:
                raise ConflictError(
                    "Canonical Pay Bill detail lines do not reconcile to their column total."
                )
        detail_by_employee[str(result["employee_number"])] = sorted(
            detail_lines, key=lambda line: (line[4], line[2])
        )

        (
            post_group_key,
            post_title,
            sanctioned,
            vacant,
            pay_scale,
            post_display_order,
            post_remarks,
        ) = post_metadata(identity)
        account_number = (
            identity.get("gpf_account_number")
            or identity.get("pension_account")
            or identity.get("pran")
            or identity.get("epf_number")
            or ""
        )
        regime = str(identity.get("retirement_regime") or "").casefold()
        account_label = "Pension A/C" if regime in {"nps", "epf"} else "GPF A/C"
        values: dict[str, Any] = {
            "employee_number": str(result["employee_number"]),
            "name": str(identity.get("name") or ""),
            "designation": str(identity.get("designation") or post_title),
            "post_group_key": post_group_key,
            "post_title": post_title,
            "sanctioned_posts": "" if sanctioned is None else str(sanctioned),
            "vacant_posts": "" if vacant is None else str(vacant),
            "pay_scale": pay_scale,
            "post_display_order": post_display_order,
            "pan": str(identity.get("pan") or ""),
            "account_label": account_label,
            "gpf_account_number": str(account_number),
            "remarks": post_remarks,
            **amounts,
        }
        row = tuple(values[column.key] for column in _V3_COLUMNS)
        for key in V3_MONEY_KEYS:
            footer[key] = money(footer[key] + amounts[key])
        gross_bill = money(
            sum((amounts[key] for key in V3_MONEY_KEYS[:8]), ZERO) + amounts["l_employer_share"]
        )
        all_recoveries = money(
            amounts["m_recovery"] + sum((amounts[key] for key in V3_MONEY_KEYS[10:]), ZERO)
        )
        expected = {
            "gross_bill": money(result["gross_total"]),
            "all_recoveries": money(result["deductions_total"]),
            "net": money(result["net_payable"]),
        }
        actual = {
            "gross_bill": gross_bill,
            "all_recoveries": all_recoveries,
            "net": money(gross_bill - all_recoveries),
        }
        if actual != expected:
            raise ConflictError(
                "Canonical Pay Bill columns do not reconcile to posted employee totals.",
                details={
                    "employee_number": str(result["employee_number"]),
                    "actual": {key: str(value) for key, value in actual.items()},
                    "posted": {key: str(value) for key, value in expected.items()},
                },
            )
        ordered_rows.append(
            (
                (
                    post_display_order,
                    post_group_key,
                    post_title.casefold(),
                    str(result["employee_number"]),
                ),
                row,
            )
        )

    organization = snapshot.get("organization") or {}
    organization_name = (
        str(organization.get("name") or org.name) if isinstance(organization, dict) else org.name
    )
    ordered = sorted(ordered_rows)
    totals = tuple(
        "TOTAL"
        if column.key == "employee_number"
        else footer[column.key]
        if column.key in footer
        else None
        for column in _V3_COLUMNS
    )
    return ReportDTO(
        report_type=REPORT_TYPE_PAY_BILL,
        template_version=ctx.template_version,
        title="Payroll Register - Pay Bill",
        organization_name=organization_name,
        subtitle=period_label(period.period_year, period.period_month),
        sections=(
            TableSection(
                title="Register",
                columns=_V3_COLUMNS,
                rows=tuple(row for _sort_key, row in ordered),
                totals=totals,
            ),
            TableSection(
                title="Component detail lines",
                columns=(
                    ReportColumn("employee_number", "Employee No."),
                    ReportColumn("register_column", "Register Column"),
                    ReportColumn("component_code", "Component Code"),
                    ReportColumn("component_name", "Component Name"),
                    ReportColumn("display_order", "Display Order", ColumnKind.COUNT),
                    ReportColumn("reason", "Reason"),
                    ReportColumn("service_period", "Service Period"),
                    ReportColumn("amount", "Amount", ColumnKind.MONEY),
                ),
                rows=tuple(
                    line for _sort_key, row in ordered for line in detail_by_employee[str(row[0])]
                ),
            ),
            TableSection(
                title="Rate / rule snapshot",
                columns=(ReportColumn("note", "Note"),),
                rows=(
                    (
                        f"engine_version={version['engine_version']}; "
                        f"template_version={ctx.template_version}",
                    ),
                ),
            ),
        ),
        metadata={
            "report_profile": dict(snapshot.get("report_profile") or {}),
            "run_metadata": dict(snapshot.get("run_metadata") or {}),
        },
    )
