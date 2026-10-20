"""Verify real shaped PDF glyph maps and multilingual copy/print text."""

from dataclasses import replace
from decimal import Decimal
from io import BytesIO
import shutil
import subprocess

import pytest
from pypdf import PdfReader

from app.reports.base import ColumnKind, ReportColumn, ReportDTO, TableSection
from app.reports.canonical_pay_bill_allocation import V3_MONEY_KEYS
from app.reports.canonical_pay_bill_pdf import pay_bill_v3_to_pdf
from app.reports.pdf import to_pdf


def synthetic_report() -> ReportDTO:
    return ReportDTO(
        report_type="pay_bill",
        template_version="v1",
        title="Payroll / क्षेत्रीय तपासणी",
        organization_name="चाचणी संस्था",
        subtitle="02/01/2026 / Test",
        sections=(
            TableSection(
                title="तपासणी / Checked",
                columns=(
                    ReportColumn("name", "Employee"),
                    ReportColumn("money", "Amount", ColumnKind.MONEY),
                ),
                rows=(("क्षेत्र तपासणी / Checked ₹1,234.50 & 5%", Decimal("1234.50")),),
            ),
        ),
    )


def synthetic_canonical_report() -> ReportDTO:
    text_values = {
        "post_group_key": "SYN-POST",
        "post_title": "चाचणी अधिकारी",
        "sanctioned_posts": "1",
        "vacant_posts": "0",
        "pay_scale": "SYN-SCALE",
        "employee_number": "SYN-001",
        "name": "क्षेत्र तपासणी",
        "account_label": "SYN-ACCOUNT-001",
        "remarks": "मंजूर / Checked",
        "designation": "चाचणी अधिकारी",
        "gpf_account_number": "SYN-GPF-001",
        "pan": "SYN-IDENTITY",
    }
    keys = tuple(text_values) + V3_MONEY_KEYS
    section = TableSection(
        title="Register",
        columns=tuple(ReportColumn(key, key) for key in keys),
        rows=(
            tuple(text_values.values())
            + tuple(
                Decimal("100.00") if key == "c_basic" else Decimal("0.00") for key in V3_MONEY_KEYS
            ),
        ),
    )
    return replace(synthetic_report(), template_version="v3", sections=(section,))


def assert_shaped_devanagari(raw: bytes) -> None:
    maps = []
    for page in PdfReader(BytesIO(raw)).pages:
        for reference in page["/Resources"]["/Font"].values():
            font = reference.get_object()
            if "Devanagari" in str(font.get("/BaseFont")):
                maps.append(font["/ToUnicode"].get_object().get_data().lower())
    # Bundled Noto shapes क् + ष as a conjunct glyph mapped back to its source
    # sequence. Merely embedding individual Unicode glyphs fails this check.
    assert any(b"0915094d0937" in mapping for mapping in maps)


@pytest.mark.parametrize(
    "render,make_dto",
    [(to_pdf, synthetic_report), (pay_bill_v3_to_pdf, synthetic_canonical_report)],
)
def test_exports_shape_devanagari_and_preserve_following_latin(render, make_dto, tmp_path):
    executable = shutil.which("pdftotext")
    if executable is None:
        pytest.fail("Poppler pdftotext is required; install poppler to run PDF tests")
    dto = make_dto()
    raw = render(dto)
    assert_shaped_devanagari(raw)
    path = tmp_path / "synthetic-payroll.pdf"
    path.write_bytes(raw)
    result = subprocess.run(
        [executable, "-layout", str(path), "-"], check=True, capture_output=True, text=True
    )
    assert not result.stderr, result.stderr
    assert "Checked" in result.stdout
    assert "क्षेत्र" in "".join(result.stdout.split())
    if render is to_pdf:
        assert "₹1,234.50 & 5%" in result.stdout
        assert "1,234.50" in result.stdout
    assert "Page 1 of 1" in result.stdout


def test_missing_primary_font_does_not_replace_marathi_with_question_marks(tmp_path):
    with pytest.raises(FileNotFoundError):
        to_pdf(synthetic_report(), font_path=tmp_path / "missing.ttf")


def test_canonical_wrapping_keeps_marks_and_joiners_with_their_base():
    from app.reports.canonical_pay_bill_pdf import _CanonicalPayBillPDF, _pdf_wrap_lines
    from app.reports.pdf import DEFAULT_FONT_PATH, unicode_clusters

    # Both joiner forms and canonically equivalent nukta spellings are source
    # content; wrapping must not discard either spelling or split vowel marks.
    value = "क्‍षक्‌षक़क़क‌"
    clusters = unicode_clusters(value)
    assert "".join(clusters) == value
    assert clusters[-1] == "क‌"
    pdf = _CanonicalPayBillPDF()
    pdf.add_font("Synthetic", fname=str(DEFAULT_FONT_PATH))
    from app.reports.pdf import DEVANAGARI_FONT_PATH

    pdf.add_font("Indic", fname=str(DEVANAGARI_FONT_PATH))
    pdf.set_fallback_fonts(["Indic"], exact_match=False)
    pdf.set_font("Synthetic", size=9)
    pdf.set_text_shaping(True)
    lines = _pdf_wrap_lines(pdf, value, 7)
    assert len(lines) > 1
    assert "".join(lines) == value
    assert all(not line.startswith(("्", "़", "‌", "‍")) for line in lines)
