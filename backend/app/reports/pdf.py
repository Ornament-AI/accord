"""Minimal generic tabular PDF renderer for :class:`~app.reports.base.ReportDTO`.

Uses fpdf2 (same library as Atlas). Page header shows organization name, report
title, and period/subtitle; footer uses fpdf2 ``alias_nb_pages`` mechanics for
``Page x of y``. Money cells are right-aligned and rendered via
:func:`app.reports.formatting.format_inr`.

NotoSans embedding is parameterized by ``font_path`` (default:
``backend/app/assets/fonts/NotoSans-Regular.ttf``). If the font file is absent,
``add_font`` is skipped and fpdf2 built-in Helvetica is used.

Follow-up: copy ``NotoSans-Regular.ttf`` (+ OFL license) from Atlas into
``backend/app/assets/fonts/`` so Unicode/INR labels render with the branded face.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

from app.reports.base import CellValue, ColumnKind, ReportDTO, TableSection
from app.reports.formatting import format_inr

DEFAULT_FONT_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "NotoSans-Regular.ttf"
)
UNICODE_FONT_FAMILY = "NotoSans"
FALLBACK_FONT_FAMILY = "Helvetica"

MARGIN_MM = 12.0
ROW_H_MM = 6.0
HEADER_ROW_H_MM = 7.0
BODY_FONT_PT = 8.0
TABLE_HEADER_FONT_PT = 7.5


def _resolve_font_path(font_path: Path | None) -> tuple[str, Path | None]:
    """Return ``(font_family, path_to_add_or_None)``.

    Copying NotoSans-Regular.ttf (+ OFL license) from Atlas into
    ``app/assets/fonts/`` is a follow-up task — until then Helvetica is used.
    """
    path = DEFAULT_FONT_PATH if font_path is None else Path(font_path)
    if path.is_file():
        return UNICODE_FONT_FAMILY, path
    return FALLBACK_FONT_FAMILY, None


def _pdf_text(text: str, *, unicode_font: bool) -> str:
    """Normalize text for the active font (latin-1 replace when on Helvetica)."""
    if unicode_font:
        return text
    return text.encode("latin-1", "replace").decode("latin-1")


def _format_cell(value: CellValue, kind: ColumnKind, *, unicode_font: bool) -> str:
    if value is None:
        return ""
    if kind is ColumnKind.MONEY:
        if not isinstance(value, Decimal):
            raise TypeError(f"money column requires Decimal, got {type(value).__name__}")
        return format_inr(value)
    if kind is ColumnKind.COUNT:
        return f"{int(value):,}"
    if kind is ColumnKind.DATE:
        raw = value.isoformat() if hasattr(value, "isoformat") else str(value)
        return _pdf_text(raw, unicode_font=unicode_font)
    return _pdf_text(str(value), unicode_font=unicode_font)


class _TabularReportPDF(FPDF):
    def __init__(
        self,
        *,
        organization_name: str,
        title: str,
        subtitle: str,
        font_family: str,
    ) -> None:
        super().__init__(orientation="L", unit="mm", format="A4")
        self._organization_name = organization_name
        self._report_title = title
        self._subtitle = subtitle
        self._font_family = font_family

    @property
    def _unicode_font(self) -> bool:
        return self._font_family == UNICODE_FONT_FAMILY

    def header(self) -> None:
        unicode_font = self._unicode_font
        self.set_font(self._font_family, size=9)
        self.cell(
            0,
            5,
            _pdf_text(self._organization_name, unicode_font=unicode_font),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_font(self._font_family, style="B", size=12)
        self.cell(
            0,
            6,
            _pdf_text(self._report_title, unicode_font=unicode_font),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_font(self._font_family, size=8)
        self.cell(
            0,
            5,
            _pdf_text(self._subtitle, unicode_font=unicode_font),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(self._font_family, size=8)
        # alias_nb_pages() replaces "{nb}" with the total page count on output.
        self.cell(0, 8, f"Page {self.page_no()} of {{nb}}", align="C")


def _column_widths(pdf: FPDF, section: TableSection) -> list[float]:
    usable = pdf.w - 2 * MARGIN_MM
    count = max(len(section.columns), 1)
    return [usable / count] * count


def _draw_table_header(
    pdf: _TabularReportPDF,
    section: TableSection,
    widths: list[float],
) -> None:
    unicode_font = pdf._unicode_font
    pdf.set_font(pdf._font_family, style="B", size=TABLE_HEADER_FONT_PT)
    for column, width in zip(section.columns, widths, strict=True):
        pdf.cell(
            width,
            HEADER_ROW_H_MM,
            _pdf_text(column.header, unicode_font=unicode_font),
            border=1,
            align="C",
        )
    pdf.ln(HEADER_ROW_H_MM)


def _draw_row(
    pdf: _TabularReportPDF,
    section: TableSection,
    row: tuple[CellValue, ...],
    widths: list[float],
    *,
    bold: bool = False,
) -> None:
    style = "B" if bold else ""
    unicode_font = pdf._unicode_font
    pdf.set_font(pdf._font_family, style=style, size=BODY_FONT_PT)
    for column, value, width in zip(section.columns, row, widths, strict=True):
        text = _format_cell(value, column.kind, unicode_font=unicode_font)
        align = "R" if column.kind is ColumnKind.MONEY else "L"
        pdf.cell(width, ROW_H_MM, text, border=1, align=align)
    pdf.ln(ROW_H_MM)


def _render_section(pdf: _TabularReportPDF, section: TableSection) -> None:
    if section.title:
        pdf.set_font(pdf._font_family, style="B", size=9)
        pdf.cell(
            0,
            6,
            _pdf_text(section.title, unicode_font=pdf._unicode_font),
            new_x="LMARGIN",
            new_y="NEXT",
        )

    if not section.columns:
        return

    widths = _column_widths(pdf, section)
    _draw_table_header(pdf, section, widths)

    bottom_limit = pdf.h - MARGIN_MM - 10
    for row in section.rows:
        if pdf.get_y() + ROW_H_MM > bottom_limit:
            pdf.add_page()
            _draw_table_header(pdf, section, widths)
        _draw_row(pdf, section, row, widths)

    if section.totals is not None:
        if pdf.get_y() + ROW_H_MM > bottom_limit:
            pdf.add_page()
            _draw_table_header(pdf, section, widths)
        _draw_row(pdf, section, section.totals, bold=True)


def to_pdf(dto: ReportDTO, *, font_path: Path | None = None) -> bytes:
    """Render a tabular report DTO to paginated landscape A4 PDF bytes."""
    font_family, resolved_path = _resolve_font_path(font_path)
    doc = _TabularReportPDF(
        organization_name=dto.organization_name,
        title=dto.title,
        subtitle=dto.subtitle,
        font_family=font_family,
    )
    if resolved_path is not None:
        doc.add_font(family=UNICODE_FONT_FAMILY, fname=str(resolved_path))

    doc.set_creator("accord-backend")
    doc.set_producer("accord-fpdf2/1.0")
    doc.alias_nb_pages()
    doc.set_auto_page_break(auto=True, margin=MARGIN_MM + 8)
    doc.set_margins(MARGIN_MM, MARGIN_MM + 4, MARGIN_MM)
    doc.add_page()

    sections = dto.sections or (TableSection(title=dto.title, columns=(), rows=()),)
    for index, section in enumerate(sections):
        if index > 0:
            doc.add_page()
        _render_section(doc, section)

    return bytes(doc.output())
