"""Compatibility facade for canonical v3 workbook renderers."""

from app.reports.canonical_pay_bill_common import _text_preserving_zero
from app.reports.canonical_pay_bill_excel import pay_bill_v3_to_excel
from app.reports.canonical_pay_bill_pdf import pay_bill_v3_to_pdf
from app.reports.canonical_workbook import CANONICAL_PRODUCT_SHEETS, consolidate_v3_workbooks

__all__ = (
    "CANONICAL_PRODUCT_SHEETS",
    "consolidate_v3_workbooks",
    "pay_bill_v3_to_excel",
    "pay_bill_v3_to_pdf",
    "_text_preserving_zero",
)
