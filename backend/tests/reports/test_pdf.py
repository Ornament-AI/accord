"""Tests for the generic tabular PDF report formatter."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.reports.base import ColumnKind, ReportColumn, ReportDTO, TableSection
from app.reports.pdf import to_pdf


def _sample_register_dto() -> ReportDTO:
    return ReportDTO(
        report_type="pay_bill",
        template_version="v1",
        title="Payroll Register — Pay Bill",
        organization_name="Accord Demo Org",
        subtitle="June 2026",
        sections=(
            TableSection(
                title="Register",
                columns=(
                    ReportColumn(key="employee", header="Employee", kind=ColumnKind.TEXT),
                    ReportColumn(key="gross", header="Gross", kind=ColumnKind.MONEY),
                ),
                rows=(("Ada Lovelace", Decimal("5102985.00")),),
            ),
        ),
    )


def test_to_pdf_bytes_are_pdf_with_title_money_and_footer() -> None:
    raw = to_pdf(_sample_register_dto())
    assert isinstance(raw, (bytes, bytearray))
    assert raw.startswith(b"%PDF")

    reader = PdfReader(BytesIO(raw))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Payroll Register" in text
    assert "51,02,985.00" in text
    assert "Page 1 of 1" in text
