"""Canonical v3 report readiness from calculated or immutable posted facts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.export_metadata import pay_bill_bucket_key
from app.exceptions import ConflictError, NotFoundError
from app.models.payroll_runs import (
    PayrollRun,
    payroll_employee_results,
    payroll_report_snapshots,
    payroll_result_lines,
    payroll_run_versions,
)
from app.schemas.payroll_runs import PayrollRunReportMetadata

_COMMON_REPORT_TYPE = "canonical_export"
_ALLOCATION_REPORT_TYPE = "canonical_pay_bill_allocation"
_REPORT_TYPE_DEPENDENCIES: dict[str, frozenset[str]] = {
    # The Pay Bill header carries the same bill identity and head-of-account
    # facts as Treasury Face, so individual v3 Pay Bill exports need both.
    "pay_bill": frozenset({_ALLOCATION_REPORT_TYPE, "treasury_face"}),
    "treasury_face": frozenset({_ALLOCATION_REPORT_TYPE}),
}


def _issue(
    report_type: str,
    code: str,
    message: str,
    *,
    owner: str,
    href: str,
    entity_id: str | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "report_type": report_type,
        "code": code,
        "message": message,
        "owner": owner,
        "href": href,
    }
    if entity_id is not None:
        issue["entity_id"] = entity_id
    return issue


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def _gpf_readiness_report_types(jurisdiction: str) -> tuple[str, ...]:
    """Return every individual GPF export that must be blocked for this value."""

    if jurisdiction in {"mumbai", "nagpur"}:
        return (f"gpf_{jurisdiction}_schedule",)
    return ("gpf_mumbai_schedule", "gpf_nagpur_schedule")


def _issues_for_report(
    issues: list[dict[str, Any]], report_type: str | None
) -> list[dict[str, Any]]:
    """Keep common issues plus the selected report's builder dependencies."""

    if report_type is None:
        return issues
    relevant_types = {
        _COMMON_REPORT_TYPE,
        report_type,
        *_REPORT_TYPE_DEPENDENCIES.get(report_type, frozenset()),
    }
    return [issue for issue in issues if issue["report_type"] in relevant_types]


def _payslip_bucket_overflows(rows: list[Any]) -> list[dict[str, Any]]:
    """Return employee buckets that exceed the canonical nine-line capacity."""

    counts: dict[tuple[str, str], int] = {}
    employee_numbers: dict[str, str] = {}
    for row in rows:
        employee_id = str(row["employee_id"])
        employee_numbers[employee_id] = str(row["employee_number"])
        trace = row.get("trace") or {}
        code = str(row["component_code"])
        classification = str(trace.get("classification") or row["classification"])
        if (
            code == "FOREGONE_HRA"
            or classification == "informational"
            or trace.get("employer_transfer")
        ):
            continue
        if classification in {"earning", "gross_adjustment"}:
            bucket = "earnings"
        elif classification in {"ag_deduction", "AG_deduction", "treasury_deduction"}:
            bucket = "government recoveries"
        elif classification == "external_recovery":
            bucket = "non-government recoveries"
        else:
            continue
        key = (employee_id, bucket)
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "employee_id": employee_id,
            "employee_number": employee_numbers[employee_id],
            "bucket": bucket,
            "count": count,
        }
        for (employee_id, bucket), count in sorted(counts.items())
        if count > 9
    ]


def _pay_bill_bucket_overflows(
    rows: list[Any], catalog_by_code: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return employee columns that exceed the canonical five-line block."""

    counts: dict[tuple[str, str], int] = {}
    employee_numbers: dict[str, str] = {}
    register_columns: dict[tuple[str, str], str] = {}
    for row in rows:
        amount = Decimal(str(row.get("amount", "0")))
        if amount == Decimal("0"):
            continue
        trace = row.get("trace") or {}
        code = str(row["component_code"])
        classification = str(trace.get("classification") or row["classification"])
        if code == "FOREGONE_HRA" or classification == "informational":
            continue
        raw_register_column = (catalog_by_code.get(code) or {}).get("register_column")
        bucket = pay_bill_bucket_key(raw_register_column)
        if bucket is None:
            continue
        employee_id = str(row["employee_id"])
        employee_numbers[employee_id] = str(row["employee_number"])
        key = (employee_id, bucket)
        counts[key] = counts.get(key, 0) + 1
        register_columns[key] = str(raw_register_column)
    return [
        {
            "employee_id": employee_id,
            "employee_number": employee_numbers[employee_id],
            "register_column": register_columns[(employee_id, bucket)],
            "count": count,
        }
        for (employee_id, bucket), count in sorted(counts.items())
        if count > 5
    ]


def _epf_identifier_issues(
    rows: list[Any], identities: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return one actionable issue per employee with unidentified EPF activity."""

    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if str(row["component_code"]) not in {
            "EPF_EMPLOYEE",
            "EPF_EMPLOYER",
            "EPF_EMPLOYER_TRANSFER",
        }:
            continue
        employee_id = str(row["employee_id"])
        if employee_id in seen or not _missing(
            (identities.get(employee_id) or {}).get("epf_number")
        ):
            continue
        seen.add(employee_id)
        employee_number = str(row["employee_number"])
        issues.append(
            _issue(
                _ALLOCATION_REPORT_TYPE,
                "employee_epf_identifier_missing",
                f"Employee {employee_number} has EPF activity without an EPF number.",
                owner="employee",
                href=f"/employees/{employee_id}",
                entity_id=employee_id,
            )
        )
    return issues


async def v3_report_readiness_issues(
    db: AsyncSession,
    *,
    organization_id: UUID,
    posted_run_id: UUID,
) -> list[dict[str, Any]]:
    """Inspect calculated inputs or the immutable posted report snapshot."""

    run = await db.get(PayrollRun, posted_run_id)
    if run is None or run.organization_id != organization_id:
        raise NotFoundError("Payroll run not found.")
    if run.status not in {"calculated", "submitted", "approved", "posted", "reversed"}:
        raise ConflictError("Canonical readiness requires a calculated payroll run.")
    if run.current_version_id is None:
        raise ConflictError("Canonical readiness requires a calculated payroll run.")

    if run.status in {"posted", "reversed"}:
        snapshot = (
            await db.execute(
                sa.select(payroll_report_snapshots.c.snapshot).where(
                    payroll_report_snapshots.c.organization_id == organization_id,
                    payroll_report_snapshots.c.run_version_id == run.current_version_id,
                )
            )
        ).scalar_one_or_none()
    else:
        snapshot = (
            await db.execute(
                sa.select(payroll_run_versions.c.inputs_snapshot).where(
                    payroll_run_versions.c.organization_id == organization_id,
                    payroll_run_versions.c.id == run.current_version_id,
                )
            )
        ).scalar_one_or_none()
    if not isinstance(snapshot, dict):
        return [
            _issue(
                _COMMON_REPORT_TYPE,
                "report_snapshot_missing",
                "Recalculate and post the run again to capture canonical report facts.",
                owner="run_report_details",
                href=f"/pay-runs/{posted_run_id}",
                entity_id=str(posted_run_id),
            )
        ]

    profile = snapshot.get("report_profile") or {}
    identities = snapshot.get("employee_identity") or {}
    catalog = snapshot.get("component_catalog") or []
    metadata = PayrollRunReportMetadata.model_validate(
        snapshot.get("run_metadata") or run.report_metadata or {}
    )
    from app.services.payroll_runs import report_readiness_issues

    issues = report_readiness_issues(
        metadata=metadata,
        profile=profile,
        run_id=posted_run_id,
    )
    profile_href = "/pay-components?reportDefaults=1"

    for field, label in (
        ("legal_name", "Legal name"),
        ("office_name", "Office name"),
        ("address_lines", "Office address"),
        ("cin", "CIN"),
        ("phone", "Phone"),
        ("website", "Website"),
        ("ddo_name", "DDO name"),
        ("ddo_code", "DDO code"),
        ("administrative_department", "Administrative department"),
        ("department_code", "Department code"),
        ("treasury_code", "Treasury code"),
        ("salary_reference_prefix", "Salary reference prefix"),
        ("fund_source", "Fund source"),
        ("plan_status", "Plan status"),
    ):
        if _missing(profile.get(field)):
            issues.append(
                _issue(
                    _COMMON_REPORT_TYPE,
                    f"profile_{field}_missing",
                    f"{label} is required for canonical exports.",
                    owner="organization_export_settings",
                    href=profile_href,
                )
            )

    line_rows = (
        (
            await db.execute(
                sa.select(
                    payroll_result_lines.c.component_code,
                    payroll_result_lines.c.classification,
                    payroll_result_lines.c.amount,
                    payroll_result_lines.c.trace,
                    payroll_employee_results.c.employee_id,
                    payroll_employee_results.c.employee_number,
                )
                .select_from(
                    payroll_result_lines.join(
                        payroll_employee_results,
                        payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                    )
                )
                .where(
                    payroll_result_lines.c.organization_id == organization_id,
                    payroll_employee_results.c.organization_id == organization_id,
                    payroll_employee_results.c.run_version_id == run.current_version_id,
                )
            )
        )
        .mappings()
        .all()
    )

    all_line_rows = line_rows
    line_rows = [row for row in all_line_rows if Decimal(str(row["amount"])) != Decimal("0")]

    catalog_by_code = {
        str(item.get("code")): item
        for item in catalog
        if isinstance(item, dict) and item.get("code")
    }
    for code in sorted({str(row["component_code"]) for row in line_rows}):
        item = catalog_by_code.get(code) or {}
        if item.get("classification") == "informational" or code == "FOREGONE_HRA":
            continue
        if pay_bill_bucket_key(item.get("register_column")) is None:
            issues.append(
                _issue(
                    _ALLOCATION_REPORT_TYPE,
                    "component_register_column_missing",
                    f"Nonzero component {code} has no valid canonical Pay Bill column.",
                    owner="pay_component_catalog",
                    href="/pay-components",
                    entity_id=code,
                )
            )

    for overflow in _pay_bill_bucket_overflows(all_line_rows, catalog_by_code):
        employee_id = str(overflow["employee_id"])
        issues.append(
            _issue(
                "pay_bill",
                "employee_pay_bill_column_overflow",
                f"Employee {overflow['employee_number']} has {overflow['count']} detail lines "
                f"in Pay Bill column {overflow['register_column']}; the canonical block "
                "supports at most 5.",
                owner="pay_component_catalog",
                href="/pay-components",
                entity_id=employee_id,
            )
        )

    for overflow in _payslip_bucket_overflows(all_line_rows):
        employee_id = str(overflow["employee_id"])
        issues.append(
            _issue(
                "payslips",
                "employee_payslip_bucket_overflow",
                f"Employee {overflow['employee_number']} has {overflow['count']} "
                f"{overflow['bucket']} lines; canonical payslips support at most 9.",
                owner="employee",
                href=f"/employees/{employee_id}",
                entity_id=employee_id,
            )
        )

    checked_posts: set[str] = set()
    for employee_id, identity_value in identities.items():
        identity = identity_value if isinstance(identity_value, dict) else {}
        post = identity.get("pay_bill_post") or identity.get("post") or {}
        post_key = str(
            post.get("id")
            or post.get("heading")
            or post.get("designation")
            or identity.get("designation")
            or employee_id
        )
        if post_key in checked_posts:
            continue
        checked_posts.add(post_key)
        for value, field, label in (
            (post.get("heading") or post.get("designation"), "heading", "heading"),
            (post.get("display_order"), "display_order", "export order"),
        ):
            if _missing(value):
                issues.append(
                    _issue(
                        "pay_bill",
                        f"post_{field}_missing",
                        f"Pay Bill group {post_key!r} is missing {label}.",
                        owner="post_catalog",
                        href="/organization/posts",
                        entity_id=(None if _missing(post.get("id")) else str(post["id"])),
                    )
                )

    result_rows = (
        (
            await db.execute(
                sa.select(
                    payroll_employee_results.c.employee_id,
                    payroll_employee_results.c.employee_number,
                    payroll_employee_results.c.disbursement,
                ).where(
                    payroll_employee_results.c.organization_id == organization_id,
                    payroll_employee_results.c.run_version_id == run.current_version_id,
                )
            )
        )
        .mappings()
        .all()
    )
    for result in result_rows:
        if Decimal(str(result["disbursement"])) <= 0:
            continue
        employee_id = str(result["employee_id"])
        identity = identities.get(employee_id) or {}
        missing_bank = [
            label
            for field, label in (
                ("bank_account_number", "account number"),
                ("bank_ifsc", "IFSC"),
                ("bank_name", "bank name"),
            )
            if _missing(identity.get(field))
        ]
        if missing_bank:
            issues.append(
                _issue(
                    "bank_rtgs_advice",
                    "employee_bank_details_missing",
                    f"Employee {result['employee_number']} is missing {', '.join(missing_bank)}.",
                    owner="employee",
                    href=f"/employees/{employee_id}",
                    entity_id=employee_id,
                )
            )

    issues.extend(_epf_identifier_issues(line_rows, identities))
    for row in line_rows:
        code = str(row["component_code"])
        employee_id = str(row["employee_id"])
        employee_number = str(row["employee_number"])
        identity = identities.get(employee_id) or {}
        if code == "INCOME_TAX" and _missing(identity.get("pan")):
            issues.append(
                _issue(
                    "income_tax_schedule",
                    "employee_pan_missing",
                    f"Employee {employee_number} has Income Tax but no PAN.",
                    owner="employee",
                    href=f"/employees/{employee_id}",
                    entity_id=employee_id,
                )
            )
        if code in {"GPF_SUBSCRIPTION", "GPF_ADVANCE_INSTALLMENT"}:
            jurisdiction = str(identity.get("gpf_jurisdiction") or "")
            if jurisdiction not in {"mumbai", "nagpur"}:
                for report_type in _gpf_readiness_report_types(jurisdiction):
                    issues.append(
                        _issue(
                            report_type,
                            "employee_gpf_jurisdiction_missing",
                            f"Employee {employee_number} has GPF activity without a valid jurisdiction.",
                            owner="employee",
                            href=f"/employees/{employee_id}",
                            entity_id=employee_id,
                        )
                    )
            elif _missing(identity.get("gpf_account_number")):
                issues.append(
                    _issue(
                        f"gpf_{jurisdiction}_schedule",
                        "employee_gpf_identifier_missing",
                        f"Employee {employee_number} has GPF activity without an account number.",
                        owner="employee",
                        href=f"/employees/{employee_id}",
                        entity_id=employee_id,
                    )
                )

        if code == "ACCOMMODATION_LICENSE_FEE":
            source_ids = list((row.get("trace") or {}).get("source_version_ids") or [])
            accommodation_sources = (snapshot.get("recovery_sources") or {}).get(
                "accommodation_charges"
            ) or {}
            assignment = next(
                (
                    accommodation_sources.get(str(source_id))
                    for source_id in source_ids
                    if isinstance(accommodation_sources.get(str(source_id)), dict)
                ),
                None,
            )
            report_type = (
                f"accommodation_{assignment.get('quarters_location')}_schedule"
                if isinstance(assignment, dict)
                and assignment.get("quarters_location") in {"mumbai", "worli"}
                else _COMMON_REPORT_TYPE
            )
            if not isinstance(assignment, dict) or _missing(assignment.get("quarters_address")):
                issues.append(
                    _issue(
                        report_type,
                        "employee_accommodation_address_missing",
                        f"Employee {employee_number} has accommodation recovery without a quarters address.",
                        owner="employee",
                        href=f"/employees/{employee_id}",
                        entity_id=employee_id,
                    )
                )
            bucket_fields = (
                ("house_rent", "service_charge")
                if isinstance(assignment, dict) and assignment.get("quarters_location") == "worli"
                else (
                    "house_rent",
                    "service_charge",
                    "parking_charge",
                    "additional_parking_charge",
                )
            )
            if not isinstance(assignment, dict) or any(
                assignment.get(field) is None for field in bucket_fields
            ):
                issues.append(
                    _issue(
                        report_type,
                        "employee_accommodation_breakdown_incomplete",
                        f"Employee {employee_number} has accommodation recovery without all charge buckets.",
                        owner="employee",
                        href=f"/employees/{employee_id}",
                        entity_id=employee_id,
                    )
                )
            elif sum(Decimal(str(assignment[field])) for field in bucket_fields) != Decimal(
                str(row["amount"])
            ):
                issues.append(
                    _issue(
                        report_type,
                        "employee_accommodation_breakdown_mismatch",
                        f"Employee {employee_number} accommodation buckets do not equal the posted recovery.",
                        owner="employee",
                        href=f"/employees/{employee_id}",
                        entity_id=employee_id,
                    )
                )
        if code in {"NPS_EMPLOYEE", "NPS_EMPLOYER_TRANSFER"}:
            missing_ids = [
                label
                for field, label in (
                    ("pension_account", "pension account"),
                    ("sevarth_id", "Sevarth ID"),
                    ("pran", "PRAN"),
                )
                if _missing(identity.get(field))
            ]
            if missing_ids:
                issues.append(
                    _issue(
                        "nps_contribution_schedule",
                        "employee_nps_identifier_missing",
                        f"Employee {employee_number} is missing {', '.join(missing_ids)}.",
                        owner="employee",
                        href=f"/employees/{employee_id}",
                        entity_id=employee_id,
                    )
                )

        service_period = (row.get("trace") or {}).get("service_period")
        if isinstance(service_period, (list, tuple)) and len(service_period) == 2:
            if (service_period[0] is None) != (service_period[1] is None):
                issues.append(
                    _issue(
                        "pay_bill",
                        "service_period_incomplete",
                        f"Employee {employee_number} component {code} has an incomplete service period.",
                        owner="run_report_details",
                        href=f"/pay-runs/{posted_run_id}",
                        entity_id=str(posted_run_id),
                    )
                )

    if any(
        str(row["component_code"]) in {"NPS_EMPLOYEE", "NPS_EMPLOYER_TRANSFER"} for row in line_rows
    ):
        for field, label in (
            ("nps_employee_account_head", "NPS employee account-head narrative"),
            ("nps_employer_account_head", "NPS employer account-head narrative"),
        ):
            if _missing(profile.get(field)):
                issues.append(
                    _issue(
                        "nps_contribution_schedule",
                        f"profile_{field}_missing",
                        f"{label} is required for the canonical NPS schedule.",
                        owner="organization_export_settings",
                        href=profile_href,
                    )
                )

    for number, event_date, code, label, report_type in (
        (metadata.token_number, metadata.token_date, "token", "Treasury token", "treasury_face"),
        (
            metadata.voucher_number,
            metadata.voucher_date,
            "voucher",
            "Voucher",
            "treasury_face",
        ),
        (
            metadata.bank_advice_number,
            metadata.bank_advice_date,
            "bank_advice",
            "Bank advice",
            "bank_rtgs_advice",
        ),
        (
            metadata.approval_note_number,
            metadata.approval_note_date,
            "approval_note",
            "Approval note",
            "approval_note",
        ),
    ):
        if _missing(number) != _missing(event_date):
            issues.append(
                _issue(
                    report_type,
                    f"{code}_pair_incomplete",
                    f"{label} number and date must be entered together.",
                    owner="run_report_details",
                    href=f"/pay-runs/{posted_run_id}",
                    entity_id=str(posted_run_id),
                )
            )

    active_gpf_jurisdictions = {
        str((identities.get(str(row["employee_id"])) or {}).get("gpf_jurisdiction") or "")
        for row in line_rows
        if str(row["component_code"]) in {"GPF_SUBSCRIPTION", "GPF_ADVANCE_INSTALLMENT"}
    }
    remittance_profiles = profile.get("gpf_remittance_profiles") or {}
    for jurisdiction in sorted(active_gpf_jurisdictions & {"mumbai", "nagpur"}):
        remittance = remittance_profiles.get(jurisdiction) or {}
        for field, label in (
            ("office_name", "destination office"),
            ("address_lines", "destination address"),
            ("account_code", "account code"),
            ("authority_text", "authority text"),
        ):
            if _missing(remittance.get(field)):
                issues.append(
                    _issue(
                        f"gpf_{jurisdiction}_schedule",
                        f"gpf_{jurisdiction}_{field}_missing",
                        f"GPF {jurisdiction.title()} {label} is required.",
                        owner="organization_export_settings",
                        href=profile_href,
                    )
                )
    return issues


async def require_v3_report_readiness(
    db: AsyncSession,
    *,
    organization_id: UUID,
    posted_run_id: UUID,
    report_type: str | None = None,
) -> None:
    """Reject a v3 request when relevant canonical facts are unresolved."""

    issues = await v3_report_readiness_issues(
        db,
        organization_id=organization_id,
        posted_run_id=posted_run_id,
    )
    issues = _issues_for_report(issues, report_type)
    if issues:
        raise ConflictError(
            "Canonical v3 report data is incomplete.",
            details={"error_code": "v3_report_not_ready", "issues": issues},
        )
