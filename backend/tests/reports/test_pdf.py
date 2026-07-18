"""Tests for the generic tabular PDF report formatter."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.reports.base import ColumnKind, ReportColumn, ReportDTO, TableSection
from app.reports.pdf import to_pdf


def _sample_register_dto(*, with_totals: bool = False) -> ReportDTO:
    totals = ("TOTAL", Decimal("5102985.00")) if with_totals else None
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
                totals=totals,
            ),
        ),
    )


def _extract_text(raw: bytes) -> str:
    reader = PdfReader(BytesIO(raw))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_to_pdf_bytes_are_pdf_with_title_money_and_footer() -> None:
    raw = to_pdf(_sample_register_dto())
    assert isinstance(raw, (bytes, bytearray))
    assert raw.startswith(b"%PDF")

    text = _extract_text(raw)

    assert "Payroll Register" in text
    assert "51,02,985.00" in text
    assert "Page 1 of 1" in text


def test_to_pdf_section_with_totals_renders_without_error() -> None:
    raw = to_pdf(_sample_register_dto(with_totals=True))
    assert raw.startswith(b"%PDF")
    text = _extract_text(raw)
    assert "TOTAL" in text
    assert "51,02,985.00" in text


def test_to_pdf_short_totals_tuple_is_padded() -> None:
    dto = ReportDTO(
        report_type="pay_bill",
        template_version="v1",
        title="Short Totals",
        organization_name="Accord Demo Org",
        subtitle="June 2026",
        sections=(
            TableSection(
                title="Register",
                columns=(
                    ReportColumn(key="label", header="Label", kind=ColumnKind.TEXT),
                    ReportColumn(key="a", header="A", kind=ColumnKind.MONEY),
                    ReportColumn(key="b", header="B", kind=ColumnKind.MONEY),
                ),
                rows=(("Row", Decimal("10.00"), Decimal("20.00")),),
                totals=("TOTAL", Decimal("10.00")),  # shorter than columns
            ),
        ),
    )
    raw = to_pdf(dto)
    assert raw.startswith(b"%PDF")
    text = _extract_text(raw)
    assert "TOTAL" in text
    assert "10.00" in text


def test_to_pdf_long_totals_tuple_is_truncated() -> None:
    dto = ReportDTO(
        report_type="pay_bill",
        template_version="v1",
        title="Long Totals",
        organization_name="Accord Demo Org",
        subtitle="June 2026",
        sections=(
            TableSection(
                title="Register",
                columns=(
                    ReportColumn(key="label", header="Label", kind=ColumnKind.TEXT),
                    ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                ),
                rows=(("Row", Decimal("10.00")),),
                totals=("TOTAL", Decimal("10.00"), "EXTRA", Decimal("99.00")),
            ),
        ),
    )
    raw = to_pdf(dto)
    assert raw.startswith(b"%PDF")
    text = _extract_text(raw)
    assert "TOTAL" in text
    assert "10.00" in text
    assert "EXTRA" not in text
    assert "99.00" not in text
