"""Shared canonical Pay Bill allocation and post-normalization policy."""

from __future__ import annotations

from typing import Any

from app.domain.payroll.export_metadata import pay_bill_bucket_key


def line_classification(line: Any) -> str:
    trace = line["trace"] or {}
    value = str(trace.get("classification") or line["classification"])
    return "ag_deduction" if value == "AG_deduction" else value


V3_MONEY_KEYS = (
    "c_basic",
    "d_da",
    "e_cla",
    "f_hra",
    "g_wash_other",
    "h_other_reimbursement",
    "i_additional_allowance",
    "j_ta",
    "l_employer_share",
    "m_recovery",
    "p_gpf",
    "q_pension_employer",
    "r_pension_employee",
    "s_advance",
    "t_flood",
    "u_income_tax",
    "v_insurance_gis",
    "w_hrr",
    "x_professional_tax",
    "y_co_op",
)

REGISTER_COLUMN_ALIASES: dict[str, str] = {
    "3": "c_basic",
    "C": "c_basic",
    "BASIC": "c_basic",
    "BASIC_PAY": "c_basic",
    "4": "d_da",
    "D": "d_da",
    "DA": "d_da",
    "DEARNESS_ALLOWANCE": "d_da",
    "5": "e_cla",
    "E": "e_cla",
    "CLA": "e_cla",
    "CITY_COMPENSATORY_ALLOWANCE": "e_cla",
    "6": "f_hra",
    "F": "f_hra",
    "HRA": "f_hra",
    "HOUSE_RENT_ALLOWANCE": "f_hra",
    "7": "g_wash_other",
    "G": "g_wash_other",
    "WASH_OTHER": "g_wash_other",
    "WASH_CHILD_OTHER": "g_wash_other",
    "WASH_CHILD_OTHER_CHARGES": "g_wash_other",
    "8": "h_other_reimbursement",
    "H": "h_other_reimbursement",
    "OTHER_REIMBURSEMENT": "h_other_reimbursement",
    "SALARY_DIFFERENCE": "h_other_reimbursement",
    "OTHER_REIMBURSEMENT_SALARY_INCREMENT_DIFFERENCE": "h_other_reimbursement",
    "9": "i_additional_allowance",
    "I": "i_additional_allowance",
    "ADDITIONAL_ALLOWANCE": "i_additional_allowance",
    "ADDITIONAL_CONVEYANCE_TRANSPORT_ALLOWANCE": "i_additional_allowance",
    "10": "j_ta",
    "J": "j_ta",
    "TA": "j_ta",
    "TRANSPORT": "j_ta",
    "TRANSPORT_PTA_HONORARIUM": "j_ta",
    "12": "l_employer_share",
    "L": "l_employer_share",
    "EMPLOYER_SHARE": "l_employer_share",
    "13": "m_recovery",
    "M": "m_recovery",
    "RECOVERY": "m_recovery",
    "FESTIVAL_ADVANCE_OTHER_RECOVERY": "m_recovery",
    "16": "p_gpf",
    "P": "p_gpf",
    "GPF": "p_gpf",
    "GPF_SUBSCRIPTION": "p_gpf",
    "GPF_SUBSCRIPTION_REFUND_ARREARS": "p_gpf",
    "17": "q_pension_employer",
    "Q": "q_pension_employer",
    "PENSION_EMPLOYER": "q_pension_employer",
    "PENSION_EMPLOYER_SHARE": "q_pension_employer",
    "18": "r_pension_employee",
    "R": "r_pension_employee",
    "PENSION_EMPLOYEE": "r_pension_employee",
    "PENSION_EMPLOYEE_SHARE": "r_pension_employee",
    "19": "s_advance",
    "S": "s_advance",
    "ADVANCE": "s_advance",
    "ADVANCES": "s_advance",
    "20": "t_flood",
    "T": "t_flood",
    "FLOOD": "t_flood",
    "FLOOD_AFFECTED": "t_flood",
    "21": "u_income_tax",
    "U": "u_income_tax",
    "INCOME_TAX": "u_income_tax",
    "22": "v_insurance_gis",
    "V": "v_insurance_gis",
    "GIS": "v_insurance_gis",
    "INSURANCE_GIS": "v_insurance_gis",
    "INSURANCE": "v_insurance_gis",
    "23": "w_hrr",
    "W": "w_hrr",
    "HRR": "w_hrr",
    "ACCOMMODATION": "w_hrr",
    "HOUSE_RENT_SERVICE_CHARGE_ARREARS": "w_hrr",
    "24": "x_professional_tax",
    "X": "x_professional_tax",
    "PROFESSIONAL_TAX": "x_professional_tax",
    "25": "y_co_op",
    "Y": "y_co_op",
    "CO_OP": "y_co_op",
    "COOPERATIVE_RECOVERY": "y_co_op",
}


def normalize_register_column(value: Any) -> str | None:
    if value is None:
        return None
    canonical_bucket = pay_bill_bucket_key(value)
    if canonical_bucket is not None:
        return canonical_bucket
    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    return REGISTER_COLUMN_ALIASES.get(normalized)


def post_metadata(identity: dict[str, Any]) -> tuple[str, str, Any, Any, str, int, str]:
    nested = (
        identity.get("pay_bill_post") or identity.get("post_metadata") or identity.get("post") or {}
    )
    if not isinstance(nested, dict):
        nested = {}

    def first(*keys: str):
        for key in keys:
            value = nested.get(key, identity.get(key))
            if value is not None and value != "":
                return value
        return None

    title = str(
        first("heading", "title", "post_title", "designation") or identity.get("designation") or ""
    )
    sanctioned = first("sanctioned_posts", "sanctioned_strength", "total_posts")
    vacant = first("vacant_posts", "vacant_count", "vacancy_count", "vacancies")
    pay_scale = str(first("pay_scale", "pay_scale_label", "scale") or "")
    display_order_value = first("display_order", "post_display_order")
    display_order = 1_000_000 if display_order_value is None else int(display_order_value)
    remarks = str(first("payroll_export_remark", "remarks", "pay_bill_remarks") or "")
    group_id = first("id", "post_id", "group_id", "key")
    group_key = str(
        group_id
        or "|".join(
            (
                str(display_order),
                title,
                "" if sanctioned is None else str(sanctioned),
                "" if vacant is None else str(vacant),
                pay_scale,
            )
        )
    )
    return group_key, title, sanctioned, vacant, pay_scale, display_order, remarks
