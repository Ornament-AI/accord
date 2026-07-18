"""Font registration tests for the tabular PDF renderer."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.reports.base import ColumnKind, ReportColumn, ReportDTO, TableSection
from app.reports.pdf import (
    DEFAULT_FONT_PATH,
    DEVANAGARI_FONT_PATH,
    UNICODE_FALLBACK_FONT_FAMILY,
    UNICODE_FONT_FAMILY,
    to_pdf,
)

_FONTS_PRESENT = DEFAULT_FONT_PATH.is_file() and DEVANAGARI_FONT_PATH.is_file()


@pytest.mark.skipif(not _FONTS_PRESENT, reason="NotoSans font files not present under assets/fonts")
def test_devanagari_string_renders_with_noto_fallback() -> None:
    dto = ReportDTO(
        report_type="pay_bill",
        template_version="v1",
        title="Font Smoke",
        organization_name="Accord Demo Org",
        subtitle="June 2026",
        sections=(
            TableSection(
                title="Names",
                columns=(
                    ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
                    ReportColumn(key="amount", header="Amount", kind=ColumnKind.MONEY),
                ),
                rows=(("नमस्ते", Decimal("100.00")),),
            ),
        ),
    )
    raw = to_pdf(dto)
    assert raw.startswith(b"%PDF")
    # Rendering must succeed; embedded glyph extraction is font-dependent.
    reader = PdfReader(BytesIO(raw))
    assert len(reader.pages) >= 1


@pytest.mark.skipif(not _FONTS_PRESENT, reason="NotoSans font files not present under assets/fonts")
def test_unicode_and_devanagari_fonts_are_registered() -> None:
    from fpdf import FPDF

    from app.reports.pdf import _resolve_font_path

    font_family, resolved = _resolve_font_path(None)
    assert font_family == UNICODE_FONT_FAMILY
    assert resolved == DEFAULT_FONT_PATH
    assert Path(DEVANAGARI_FONT_PATH).is_file()

    doc = FPDF()
    doc.add_font(family=UNICODE_FONT_FAMILY, fname=str(DEFAULT_FONT_PATH))
    doc.add_font(family=UNICODE_FALLBACK_FONT_FAMILY, fname=str(DEVANAGARI_FONT_PATH))
    doc.set_fallback_fonts([UNICODE_FALLBACK_FONT_FAMILY], exact_match=False)
    doc.add_page()
    doc.set_font(UNICODE_FONT_FAMILY, size=12)
    doc.cell(0, 10, "नमस्ते")
    assert bytes(doc.output()).startswith(b"%PDF")
