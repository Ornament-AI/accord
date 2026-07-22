"""Canonical v3 Pay Bill PDF renderer."""

from __future__ import annotations

from fpdf import FPDF

from app.reports.base import ReportDTO
from app.reports.canonical_pay_bill_common import (
    _ARIAL_BOLD_PATH,
    _ARIAL_PATH,
    _PDF_FONT_FAMILY,
    _PAY_BILL_WIDTHS,
    _organization_label,
    _row_value,
    _text_preserving_zero,
)
from app.reports.pdf import DEFAULT_FONT_PATH


class _CanonicalPayBillPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-7)
        self.set_font(_PDF_FONT_FAMILY, size=5)
        self.cell(0, 4, f"Page {self.page_no()} of {{nb}}", align="R")


def _pdf_money(value) -> str:
    if value is None:
        return ""
    return f"{int(round(value)):,}"


def _pdf_wrap_lines(pdf: _CanonicalPayBillPDF, value: str, width: float) -> list[str]:
    """Wrap text without invoking fpdf's page-breaking ``multi_cell`` dry run."""
    if not value:
        return []
    wrapped: list[str] = []
    for paragraph in value.splitlines() or [""]:
        if not paragraph:
            wrapped.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = word if not current else f"{current} {word}"
            if pdf.get_string_width(candidate) <= width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
                current = ""
            chunk = ""
            for character in word:
                candidate_chunk = f"{chunk}{character}"
                if chunk and pdf.get_string_width(candidate_chunk) > width:
                    wrapped.append(chunk)
                    chunk = character
                else:
                    chunk = candidate_chunk
            current = chunk
        if current:
            wrapped.append(current)
    return wrapped


def _pdf_cells(
    pdf: _CanonicalPayBillPDF,
    values: list[str],
    widths: list[float],
    *,
    height: float,
    font_size: float,
    bold: bool = False,
    alignments: list[str] | None = None,
) -> None:
    start_x = pdf.get_x()
    start_y = pdf.get_y()
    x = start_x
    style = "B" if bold else ""
    for index, (value, width) in enumerate(zip(values, widths, strict=True)):
        pdf.rect(x, start_y, width, height)
        pdf.set_xy(x + 0.35, start_y + 0.3)
        alignment = "L" if alignments is None else alignments[index]
        text_width = max(width - 0.7, 0.5)
        available_height = max(height - 0.6, 1.15)
        fitted_size = font_size
        lines: list[str] = []
        while fitted_size >= 2.4:
            pdf.set_font(_PDF_FONT_FAMILY, style=style, size=fitted_size)
            line_height = max(min(fitted_size * 0.38, 2.1), 1.15)
            lines = _pdf_wrap_lines(pdf, value, text_width)
            if len(lines) * line_height <= available_height:
                break
            fitted_size -= 0.2
        pdf.set_font(_PDF_FONT_FAMILY, style=style, size=max(fitted_size, 2.4))
        line_height = max(min(max(fitted_size, 2.4) * 0.38, 2.1), 1.15)
        max_lines = max(1, int(available_height // line_height))
        visible_lines = lines[:max_lines]
        if len(lines) > max_lines and visible_lines:
            last_line = visible_lines[-1].rstrip()
            visible_lines[-1] = f"{last_line[:-3]}..." if len(last_line) > 3 else "..."
        page_before = pdf.page_no()
        pdf.multi_cell(
            text_width,
            line_height,
            "\n".join(visible_lines),
            border=0,
            align=alignment,
        )
        if pdf.page_no() != page_before:  # pragma: no cover - defensive invariant
            raise AssertionError("A canonical Pay Bill cell crossed a PDF page boundary.")
        x += width
    pdf.set_xy(start_x, start_y + height)


def _pdf_table_header(pdf: _CanonicalPayBillPDF, widths: list[float]) -> None:
    blanks_left = sum(widths[:14])
    deductions = sum(widths[14:26])
    blanks_right = sum(widths[26:])
    _pdf_cells(
        pdf,
        ["", "Deductions", ""],
        [blanks_left, deductions, blanks_right],
        height=3.2,
        font_size=4.2,
        bold=True,
        alignments=["C", "C", "C"],
    )
    _pdf_cells(
        pdf,
        [
            "",
            "Adjustable by Accountant General",
            "Adjustable by Treasury",
            "",
        ],
        [sum(widths[:14]), sum(widths[14:20]), sum(widths[20:26]), sum(widths[26:])],
        height=3.8,
        font_size=3.8,
        bold=True,
        alignments=["C", "C", "C", "C"],
    )
    short_headers = [
        "Sr. No.",
        "Employee Name",
        "Basic Pay",
        "DA / Difference",
        "CLA",
        "HRA",
        "Wash / Child / Other",
        "Other Reimbursement / Difference",
        "Additional Allowance",
        "TA / PTA / Honorarium",
        "Gross Salary",
        "Employer Share",
        "Festival / Other Recovery",
        "Gross After Recovery",
        "Account Number",
        "GPF Subscription / Arrears",
        "Pension Employer",
        "Pension Employee",
        "HBA / Motor / Other Advance",
        "Flood Advance",
        "Income Tax",
        "PLI / CGIS / MSI / GIS",
        "House Rent / Service Charges",
        "Professional Tax",
        "Co-op Recovery",
        "Total Deductions",
        "Net Payable",
        "Remarks",
    ]
    _pdf_cells(
        pdf,
        short_headers,
        widths,
        height=13.5,
        font_size=3.45,
        bold=True,
        alignments=["C"] * 28,
    )


def _pdf_page_header(
    pdf: _CanonicalPayBillPDF,
    dto: ReportDTO,
    widths: list[float],
) -> None:
    pdf.add_page()
    pdf.set_font(_PDF_FONT_FAMILY, style="B", size=7)
    pdf.cell(0, 3.5, _organization_label(dto), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font(_PDF_FONT_FAMILY, style="B", size=8)
    pdf.cell(0, 4, "Payroll Register - Pay Bill", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font(_PDF_FONT_FAMILY, size=6)
    pdf.cell(0, 3.5, dto.subtitle, new_x="LMARGIN", new_y="NEXT", align="C")
    _pdf_table_header(pdf, widths)


def pay_bill_v3_to_pdf(dto: ReportDTO) -> bytes:
    """Render the canonical Pay Bill as repeated-header landscape Letter pages."""
    if not dto.sections:
        raise ValueError("Canonical Pay Bill requires a register section.")
    section = dto.sections[0]
    detail_section = next(
        (item for item in dto.sections if item.title == "Component detail lines"), None
    )
    detail_lines: dict[tuple[str, str], list[dict[str, object]]] = {}
    if detail_section is not None:
        detail_keys = [column.key for column in detail_section.columns]
        for detail_row in detail_section.rows:
            detail = dict(zip(detail_keys, detail_row, strict=True))
            detail_lines.setdefault(
                (str(detail["employee_number"]), str(detail["register_column"])), []
            ).append(detail)
    pdf = _CanonicalPayBillPDF(orientation="L", unit="mm", format="Letter")
    regular_font = _ARIAL_PATH if _ARIAL_PATH.exists() else DEFAULT_FONT_PATH
    bold_font = _ARIAL_BOLD_PATH if _ARIAL_BOLD_PATH.exists() else DEFAULT_FONT_PATH
    pdf.add_font(family=_PDF_FONT_FAMILY, fname=str(regular_font))
    pdf.add_font(family=_PDF_FONT_FAMILY, style="B", fname=str(bold_font))
    pdf.alias_nb_pages()
    pdf.set_margins(4.5, 4.5, 4.5)
    pdf.set_auto_page_break(False)
    usable_width = pdf.w - 9
    width_total = sum(_PAY_BILL_WIDTHS)
    widths = [usable_width * width / width_total for width in _PAY_BILL_WIDTHS]
    _pdf_page_header(pdf, dto, widths)

    current_group: tuple[str, str, str, str, str] | None = None
    group_label = ""
    bottom_limit = pdf.h - 9
    for serial, item in enumerate(section.rows, start=1):
        group = (
            str(_row_value(section, item, "post_group_key") or ""),
            str(_row_value(section, item, "post_title") or "Unassigned Post"),
            _text_preserving_zero(_row_value(section, item, "sanctioned_posts")),
            _text_preserving_zero(_row_value(section, item, "vacant_posts")),
            str(_row_value(section, item, "pay_scale") or ""),
        )
        group_changed = group != current_group
        required_height = 24.5 if group_changed else 20.5
        if pdf.get_y() + required_height > bottom_limit:
            _pdf_page_header(pdf, dto, widths)
            current_group = None
            group_changed = True
        if group_changed:
            group_label = f"Post of {group[1]}"
            if group[2] or group[3]:
                group_label += f" (Total Posts {group[2] or '-'}; Vacant {group[3] or '-'})"
            if group[4]:
                group_label += f" - Scale {group[4]}"
            _pdf_cells(
                pdf,
                ["", group_label],
                [widths[0], sum(widths[1:])],
                height=4,
                font_size=4.5,
                bold=True,
                alignments=["C", "L"],
            )
            current_group = group

        money_values = {
            2: _row_value(section, item, "c_basic"),
            3: _row_value(section, item, "d_da"),
            4: _row_value(section, item, "e_cla"),
            5: _row_value(section, item, "f_hra"),
            6: _row_value(section, item, "g_wash_other"),
            7: _row_value(section, item, "h_other_reimbursement"),
            8: _row_value(section, item, "i_additional_allowance"),
            9: _row_value(section, item, "j_ta"),
            11: _row_value(section, item, "l_employer_share"),
            12: _row_value(section, item, "m_recovery"),
            15: _row_value(section, item, "p_gpf"),
            16: _row_value(section, item, "q_pension_employer"),
            17: _row_value(section, item, "r_pension_employee"),
            18: _row_value(section, item, "s_advance"),
            19: _row_value(section, item, "t_flood"),
            20: _row_value(section, item, "u_income_tax"),
            21: _row_value(section, item, "v_insurance_gis"),
            22: _row_value(section, item, "w_hrr"),
            23: _row_value(section, item, "x_professional_tax"),
            24: _row_value(section, item, "y_co_op"),
        }
        gross = sum((money_values[index] or 0) for index in range(2, 10))
        gross_after = gross + (money_values[11] or 0) - (money_values[12] or 0)
        deductions = sum((money_values[index] or 0) for index in range(15, 25))
        net = gross_after - deductions
        money_values.update({10: gross, 13: gross_after, 25: deductions, 26: net})

        employee_number = str(_row_value(section, item, "employee_number") or "")
        primary = [""] * 28
        primary[0] = str(serial)
        primary[1] = str(_row_value(section, item, "name") or "")
        primary[14] = str(_row_value(section, item, "account_label") or "")
        primary[27] = str(_row_value(section, item, "remarks") or "")
        for index, value in money_values.items():
            key = {
                2: "c_basic",
                3: "d_da",
                4: "e_cla",
                5: "f_hra",
                6: "g_wash_other",
                7: "h_other_reimbursement",
                8: "i_additional_allowance",
                9: "j_ta",
                11: "l_employer_share",
                12: "m_recovery",
                15: "p_gpf",
                16: "q_pension_employer",
                17: "r_pension_employee",
                18: "s_advance",
                19: "t_flood",
                20: "u_income_tax",
                21: "v_insurance_gis",
                22: "w_hrr",
                23: "x_professional_tax",
                24: "y_co_op",
            }.get(index)
            if key is None or not detail_lines.get((employee_number, key)):
                primary[index] = _pdf_money(value)
        alignments = ["R" if index in money_values else "L" for index in range(28)]
        secondary = [""] * 28
        secondary[1] = str(_row_value(section, item, "designation") or "")
        secondary[14] = str(_row_value(section, item, "gpf_account_number") or "")
        basic_line = [""] * 28
        basic = _row_value(section, item, "c_basic")
        basic_line[1] = "" if basic is None else f"Basic @ Rs.{int(basic)}/-"
        reason_line = [""] * 28
        pan_line = [""] * 28
        pan_line[1] = str(_row_value(section, item, "pan") or "")
        display_rows = [primary, secondary, basic_line, reason_line, pan_line]
        column_by_key = {
            "c_basic": 2,
            "d_da": 3,
            "e_cla": 4,
            "f_hra": 5,
            "g_wash_other": 6,
            "h_other_reimbursement": 7,
            "i_additional_allowance": 8,
            "j_ta": 9,
            "l_employer_share": 11,
            "m_recovery": 12,
            "p_gpf": 15,
            "q_pension_employer": 16,
            "r_pension_employee": 17,
            "s_advance": 18,
            "t_flood": 19,
            "u_income_tax": 20,
            "v_insurance_gis": 21,
            "w_hrr": 22,
            "x_professional_tax": 23,
            "y_co_op": 24,
        }
        reasons: list[str] = []
        for key, column in column_by_key.items():
            for offset, line in enumerate(detail_lines.get((employee_number, key), [])):
                display_rows[offset][column] = _pdf_money(line["amount"])
                reason = " ".join(
                    filter(
                        None,
                        (str(line.get("reason") or ""), str(line.get("service_period") or "")),
                    )
                )
                if reason and reason not in reasons:
                    reasons.append(reason)
        if reasons:
            reason_line[1] = "; ".join(reasons)
        for offset, values in enumerate(display_rows):
            _pdf_cells(
                pdf,
                values,
                widths,
                height=4.5 if offset == 0 else 3,
                font_size=3.8 if offset == 0 else 3.6,
                bold=offset == 0,
                alignments=alignments,
            )
        total = [""] * 28
        total[1] = "Total Rs."
        for index, value in money_values.items():
            total[index] = _pdf_money(value)
        _pdf_cells(
            pdf,
            total,
            widths,
            height=4,
            font_size=3.8,
            bold=True,
            alignments=alignments,
        )

    pdf.set_creator("accord-backend")
    pdf.set_producer("accord-fpdf2/canonical-v3")
    return bytes(pdf.output())
