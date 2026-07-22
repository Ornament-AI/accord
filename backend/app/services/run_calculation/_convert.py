"""Pure converters between DB rows, domain values, and snapshot payloads.

No database access. Everything here is deterministic serialization or
classification mapping between the persistence layer and the payroll
domain engine.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any


from app.domain.payroll.inputs import ComponentInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.results import CalculationTrace, RunResult
from app.models.pay_components import PayComponent


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def to_domain_classification(db_classification: str) -> str:
    if db_classification == "ag_deduction":
        return "AG_deduction"
    return db_classification


def to_db_classification(domain_classification: str) -> str:
    if domain_classification == "AG_deduction":
        return "ag_deduction"
    # Informational lines remain explicitly classified in their immutable
    # trace payload but use the legacy result-line bucket for DB compatibility.
    if domain_classification == "informational":
        return "earning"
    return domain_classification


def money_or_none(value: Decimal | None) -> Money | None:
    if value is None:
        return None
    return Money.from_decimal(Decimal(value))


def rate_or_none(value: Decimal | None) -> Rate | None:
    if value is None:
        return None
    return Rate(amount=Decimal(value))


def basis_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _serialize_component_input(comp: ComponentInput) -> dict[str, Any]:
    return {
        "component_code": comp.component_code,
        "classification": comp.classification,
        "calc_kind": comp.calc_kind,
        "amount": None if comp.amount is None else comp.amount.to_canonical_str(),
        "rate": None if comp.rate is None else comp.rate.to_canonical_str(),
        "basis": list(comp.basis),
        "rounding_rule": comp.rounding_rule,
        "source_version_ids": list(comp.source_version_ids),
        "informational": comp.informational,
        "excluded_from_totals": comp.excluded_from_totals,
        "gpf_jurisdiction": comp.gpf_jurisdiction,
        "accommodation_location": comp.accommodation_location,
        "employer_transfer": comp.employer_transfer,
        "transfer_of": comp.transfer_of,
        "service_period": comp.service_period,
        "reason": comp.reason,
    }


def serialize_run_calc_input(run_input: RunCalcInput) -> dict[str, Any]:
    employees: list[dict[str, Any]] = []
    for emp in sorted(run_input.employees, key=lambda e: e.employee_ref):
        employees.append(
            {
                "employee_ref": emp.employee_ref,
                "retirement_regime": emp.retirement_regime,
                "gpf_jurisdiction": emp.gpf_jurisdiction,
                "components": [_serialize_component_input(c) for c in emp.components],
            }
        )
    return {
        "period": run_input.period,
        "org_ref": run_input.org_ref,
        "employees": employees,
    }


def serialize_catalog(catalog: Mapping[str, PayComponent]) -> list[dict[str, Any]]:
    return [
        {
            "code": row.code,
            "name": row.name,
            "classification": row.classification,
            "display_order": row.display_order,
            "is_standard": row.is_standard,
            "schedule_kind": row.schedule_kind,
            "schedule_title": row.schedule_title,
            "schedule_account_head": row.schedule_account_head,
            "register_column": row.register_column,
        }
        for row in sorted(catalog.values(), key=lambda item: (item.display_order, item.code))
        if row.is_standard or row.is_active
    ]


def totals_payload(result: RunResult) -> dict[str, str]:
    return {
        "earnings_total": result.earnings_total.to_canonical_str(),
        "employer_contribution_total": result.employer_contribution_total.to_canonical_str(),
        "gross_adjustment_total": result.gross_adjustment_total.to_canonical_str(),
        "gross_total": result.gross_total.to_canonical_str(),
        "ag_deduction_total": result.ag_deduction_total.to_canonical_str(),
        "treasury_deduction_total": result.treasury_deduction_total.to_canonical_str(),
        "external_recovery_total": result.external_recovery_total.to_canonical_str(),
        "deductions_total": result.deductions_total.to_canonical_str(),
        "net_payable": result.net_payable.to_canonical_str(),
        # Employee disbursement is reconciled separately from treasury-face
        # net payable (docs/payroll-domain.md "Resolved").
        "offbill_employer_remittance": result.offbill_employer_remittance.to_canonical_str(),
        "disbursement": result.disbursement.to_canonical_str(),
    }


def trace_payload(trace: CalculationTrace) -> dict[str, Any]:
    return {
        "component": trace.component,
        "classification": trace.classification,
        "basis": list(trace.basis),
        "basis_total": (
            None if trace.basis_total is None else trace.basis_total.to_canonical_str()
        ),
        "rate": None if trace.rate is None else trace.rate.to_canonical_str(),
        "unrounded_value": trace.unrounded_value,
        "rounding_rule": trace.rounding_rule,
        "rounded_value": trace.rounded_value.to_canonical_str(),
        "source_version_ids": list(trace.source_version_ids),
        "calculator_kind": trace.calculator_kind,
        "engine_version": trace.engine_version,
        "employer_transfer": trace.employer_transfer,
        "transfer_of": trace.transfer_of,
        "service_period": trace.service_period,
        "reason": trace.reason,
    }
