"""Typed presentation metadata for canonical payroll exports."""

from __future__ import annotations

from enum import StrEnum


class RegisterColumn(StrEnum):
    """Canonical Pay Bill column buckets available to pay components."""

    BASIC_PAY = "basic_pay"
    DEARNESS_ALLOWANCE = "dearness_allowance"
    CITY_COMPENSATORY_ALLOWANCE = "city_compensatory_allowance"
    HOUSE_RENT_ALLOWANCE = "house_rent_allowance"
    WASH_CHILD_OTHER_CHARGES = "wash_child_other_charges"
    OTHER_REIMBURSEMENT_SALARY_INCREMENT_DIFFERENCE = (
        "other_reimbursement_salary_increment_difference"
    )
    ADDITIONAL_CONVEYANCE_TRANSPORT_ALLOWANCE = "additional_conveyance_transport_allowance"
    TRANSPORT_PTA_HONORARIUM = "transport_pta_honorarium"
    EMPLOYER_SHARE = "employer_share"
    FESTIVAL_ADVANCE_OTHER_RECOVERY = "festival_advance_other_recovery"
    GPF_SUBSCRIPTION_REFUND_ARREARS = "gpf_subscription_refund_arrears"
    PENSION_EMPLOYER_SHARE = "pension_employer_share"
    PENSION_EMPLOYEE_SHARE = "pension_employee_share"
    ADVANCES = "advances"
    FLOOD_AFFECTED = "flood_affected"
    INCOME_TAX = "income_tax"
    INSURANCE = "insurance"
    HOUSE_RENT_SERVICE_CHARGE_ARREARS = "house_rent_service_charge_arrears"
    PROFESSIONAL_TAX = "professional_tax"
    COOPERATIVE_RECOVERY = "cooperative_recovery"


_EARNING_COLUMNS = frozenset(
    {
        RegisterColumn.BASIC_PAY,
        RegisterColumn.DEARNESS_ALLOWANCE,
        RegisterColumn.CITY_COMPENSATORY_ALLOWANCE,
        RegisterColumn.HOUSE_RENT_ALLOWANCE,
        RegisterColumn.WASH_CHILD_OTHER_CHARGES,
        RegisterColumn.OTHER_REIMBURSEMENT_SALARY_INCREMENT_DIFFERENCE,
        RegisterColumn.ADDITIONAL_CONVEYANCE_TRANSPORT_ALLOWANCE,
        RegisterColumn.TRANSPORT_PTA_HONORARIUM,
    }
)

REGISTER_COLUMNS_BY_CLASSIFICATION: dict[str, frozenset[RegisterColumn]] = {
    "earning": _EARNING_COLUMNS,
    "employer_contribution": frozenset({RegisterColumn.EMPLOYER_SHARE}),
    # A signed DA/salary correction belongs beside the corresponding canonical
    # earning column even though it remains a gross adjustment for calculation.
    "gross_adjustment": frozenset(
        {
            RegisterColumn.DEARNESS_ALLOWANCE,
            RegisterColumn.OTHER_REIMBURSEMENT_SALARY_INCREMENT_DIFFERENCE,
        }
    ),
    "ag_deduction": frozenset(
        {
            RegisterColumn.GPF_SUBSCRIPTION_REFUND_ARREARS,
            RegisterColumn.PENSION_EMPLOYER_SHARE,
            RegisterColumn.PENSION_EMPLOYEE_SHARE,
        }
    ),
    "treasury_deduction": frozenset(
        {
            RegisterColumn.FLOOD_AFFECTED,
            RegisterColumn.INCOME_TAX,
            RegisterColumn.INSURANCE,
            RegisterColumn.HOUSE_RENT_SERVICE_CHARGE_ARREARS,
            RegisterColumn.PROFESSIONAL_TAX,
            RegisterColumn.COOPERATIVE_RECOVERY,
        }
    ),
    "external_recovery": frozenset(
        {
            RegisterColumn.FESTIVAL_ADVANCE_OTHER_RECOVERY,
            RegisterColumn.ADVANCES,
            RegisterColumn.HOUSE_RENT_SERVICE_CHARGE_ARREARS,
            RegisterColumn.COOPERATIVE_RECOVERY,
        }
    ),
    "informational": frozenset(),
}


# The v3 Pay Bill DTO uses compact renderer keys internally. Keep this mapping
# beside the typed catalog values so readiness and rendering resolve a component
# to the same physical column.
PAY_BILL_BUCKET_BY_REGISTER_COLUMN: dict[RegisterColumn, str] = {
    RegisterColumn.BASIC_PAY: "c_basic",
    RegisterColumn.DEARNESS_ALLOWANCE: "d_da",
    RegisterColumn.CITY_COMPENSATORY_ALLOWANCE: "e_cla",
    RegisterColumn.HOUSE_RENT_ALLOWANCE: "f_hra",
    RegisterColumn.WASH_CHILD_OTHER_CHARGES: "g_wash_other",
    RegisterColumn.OTHER_REIMBURSEMENT_SALARY_INCREMENT_DIFFERENCE: ("h_other_reimbursement"),
    RegisterColumn.ADDITIONAL_CONVEYANCE_TRANSPORT_ALLOWANCE: "i_additional_allowance",
    RegisterColumn.TRANSPORT_PTA_HONORARIUM: "j_ta",
    RegisterColumn.EMPLOYER_SHARE: "l_employer_share",
    RegisterColumn.FESTIVAL_ADVANCE_OTHER_RECOVERY: "m_recovery",
    RegisterColumn.GPF_SUBSCRIPTION_REFUND_ARREARS: "p_gpf",
    RegisterColumn.PENSION_EMPLOYER_SHARE: "q_pension_employer",
    RegisterColumn.PENSION_EMPLOYEE_SHARE: "r_pension_employee",
    RegisterColumn.ADVANCES: "s_advance",
    RegisterColumn.FLOOD_AFFECTED: "t_flood",
    RegisterColumn.INCOME_TAX: "u_income_tax",
    RegisterColumn.INSURANCE: "v_insurance_gis",
    RegisterColumn.HOUSE_RENT_SERVICE_CHARGE_ARREARS: "w_hrr",
    RegisterColumn.PROFESSIONAL_TAX: "x_professional_tax",
    RegisterColumn.COOPERATIVE_RECOVERY: "y_co_op",
}


def pay_bill_bucket_key(register_column: RegisterColumn | str | None) -> str | None:
    """Resolve a typed catalog column to its physical v3 Pay Bill bucket."""

    if register_column is None:
        return None
    try:
        column = RegisterColumn(register_column)
    except ValueError:
        return None
    return PAY_BILL_BUCKET_BY_REGISTER_COLUMN[column]


def register_column_matches_classification(
    classification: str,
    register_column: RegisterColumn | str | None,
) -> bool:
    """Return whether a canonical bucket is compatible with a component class."""

    if register_column is None:
        return True
    try:
        column = RegisterColumn(register_column)
    except ValueError:
        return False
    return column in REGISTER_COLUMNS_BY_CLASSIFICATION.get(classification, frozenset())
