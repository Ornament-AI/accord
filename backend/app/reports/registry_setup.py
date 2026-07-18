"""Central assembly of the report registry (Lane 1 integration point).

Every report family registers here exactly once; API and worker processes
share this single construction path so the catalog can never diverge
between them.
"""

from __future__ import annotations

from app.reports.base import ReportRegistry
from app.reports.families import payroll_register
from app.reports.families.approval_note import register as register_approval_note
from app.reports.families.payments import register_payment_reports
from app.reports.families.recovery import register_recovery_reports
from app.reports.families.retirement import register_retirement_reports
from app.reports.families.statutory import register as register_statutory


def _register_payroll_register(registry: ReportRegistry) -> None:
    registry.register(
        payroll_register.REPORT_TYPE_PAY_BILL,
        builder=payroll_register.pay_bill_builder,
        to_json=payroll_register.pay_bill_to_json,
        to_excel=payroll_register.pay_bill_to_excel,
        to_pdf=payroll_register.pay_bill_to_pdf,
        content_types=payroll_register.DEFAULT_CONTENT_TYPES,
        filename_pattern=payroll_register.PAY_BILL_FILENAME_PATTERN,
    )
    registry.register(
        payroll_register.REPORT_TYPE_TREASURY_FACE,
        builder=payroll_register.treasury_face_builder,
        to_json=payroll_register.treasury_face_to_json,
        to_excel=payroll_register.treasury_face_to_excel,
        to_pdf=payroll_register.treasury_face_to_pdf,
        content_types=payroll_register.DEFAULT_CONTENT_TYPES,
        filename_pattern=payroll_register.TREASURY_FACE_FILENAME_PATTERN,
    )


def build_report_registry() -> ReportRegistry:
    """Build the full first-release report registry (all June families)."""
    registry = ReportRegistry()
    _register_payroll_register(registry)
    register_payment_reports(registry)
    register_retirement_reports(registry)
    register_statutory(registry)
    register_recovery_reports(registry)
    register_approval_note(registry)
    return registry
