"""Accord's standard payroll component catalog.

The catalog is installed per organization so names and ordering can be
customized while the stable codes/classifications remain application-owned.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.pay_components import PayComponent


@dataclass(frozen=True, slots=True)
class StandardComponent:
    code: str
    name: str
    classification: str
    display_order: int
    employer_transfer: bool = False
    transfer_of: str | None = None
    schedule_kind: str | None = None
    schedule_title: str | None = None
    register_column: str | None = None


STANDARD_COMPONENTS: tuple[StandardComponent, ...] = (
    StandardComponent("BASIC", "Basic Pay", "earning", 10, register_column="basic_pay"),
    StandardComponent(
        "DA", "Dearness Allowance", "earning", 20, register_column="dearness_allowance"
    ),
    StandardComponent(
        "CLA",
        "City Compensatory Allowance",
        "earning",
        30,
        register_column="city_compensatory_allowance",
    ),
    StandardComponent(
        "HRA", "House Rent Allowance", "earning", 40, register_column="house_rent_allowance"
    ),
    StandardComponent(
        "WASH_ALLOWANCE",
        "Wash Allowance",
        "earning",
        50,
        register_column="wash_child_other_charges",
    ),
    StandardComponent(
        "OTHER_ALLOWANCE",
        "Other Allowance",
        "earning",
        60,
        register_column="other_reimbursement_salary_increment_difference",
    ),
    StandardComponent(
        "ADDITIONAL_ALLOWANCE",
        "Additional Conveyance / Allowance",
        "earning",
        65,
        register_column="additional_conveyance_transport_allowance",
    ),
    StandardComponent(
        "TRANSPORT",
        "Transport Allowance",
        "earning",
        70,
        register_column="transport_pta_honorarium",
    ),
    StandardComponent(
        "EPF_EMPLOYER",
        "EPF Employer Contribution",
        "employer_contribution",
        80,
        register_column="employer_share",
    ),
    StandardComponent(
        "DA_DIFFERENCE",
        "DA Difference",
        "gross_adjustment",
        90,
        register_column="dearness_allowance",
    ),
    StandardComponent(
        "GPF_SUBSCRIPTION",
        "GPF Subscription",
        "ag_deduction",
        100,
        register_column="gpf_subscription_refund_arrears",
    ),
    StandardComponent(
        "NPS_EMPLOYEE",
        "NPS Employee Contribution",
        "ag_deduction",
        110,
        register_column="pension_employee_share",
    ),
    StandardComponent(
        "NPS_EMPLOYER_TRANSFER",
        "NPS Employer Transfer",
        "ag_deduction",
        120,
        employer_transfer=True,
        register_column="pension_employer_share",
    ),
    StandardComponent(
        "EPF_EMPLOYEE",
        "EPF Employee Contribution",
        "ag_deduction",
        130,
        register_column="pension_employee_share",
    ),
    StandardComponent(
        "EPF_EMPLOYER_TRANSFER",
        "EPF Employer Transfer",
        "ag_deduction",
        140,
        employer_transfer=True,
        transfer_of="EPF_EMPLOYER",
        register_column="pension_employer_share",
    ),
    StandardComponent(
        "INCOME_TAX", "Income Tax", "treasury_deduction", 150, register_column="income_tax"
    ),
    StandardComponent(
        "PROFESSIONAL_TAX",
        "Professional Tax",
        "treasury_deduction",
        160,
        register_column="professional_tax",
    ),
    StandardComponent(
        "GIS", "Group Insurance Scheme", "treasury_deduction", 170, register_column="insurance"
    ),
    StandardComponent(
        "HBA_INSTALLMENT",
        "House Building Advance",
        "external_recovery",
        180,
        schedule_kind="loan_installment",
        schedule_title="House Building Advance Recovery",
        register_column="advances",
    ),
    StandardComponent(
        "GPF_ADVANCE_INSTALLMENT",
        "GPF Advance",
        "external_recovery",
        190,
        schedule_kind="loan_installment",
        schedule_title="GPF Advance Recovery",
        register_column="advances",
    ),
    StandardComponent(
        "FESTIVAL_ADVANCE_INSTALLMENT",
        "Festival Advance",
        "external_recovery",
        200,
        schedule_kind="loan_installment",
        schedule_title="Festival Advance Recovery",
        register_column="festival_advance_other_recovery",
    ),
    StandardComponent(
        "MOTOR_CAR_ADVANCE_INSTALLMENT",
        "Motor Car Advance",
        "external_recovery",
        210,
        schedule_kind="loan_installment",
        schedule_title="Motor Car Advance Recovery",
        register_column="advances",
    ),
    StandardComponent(
        "MOTORCYCLE_ADVANCE_INSTALLMENT",
        "Motorcycle Advance",
        "external_recovery",
        220,
        schedule_kind="loan_installment",
        schedule_title="Motorcycle Advance Recovery",
        register_column="advances",
    ),
    StandardComponent(
        "OTHER_ADVANCE_INSTALLMENT",
        "Other Advance",
        "external_recovery",
        230,
        schedule_kind="loan_installment",
        schedule_title="Other Advance Recovery",
        register_column="advances",
    ),
    StandardComponent(
        "ACCOMMODATION_LICENSE_FEE",
        "Accommodation License Fee",
        "external_recovery",
        240,
        register_column="house_rent_service_charge_arrears",
    ),
    StandardComponent("FOREGONE_HRA", "Foregone HRA", "informational", 250),
)


async def ensure_standard_components(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> None:
    codes = [item.code for item in STANDARD_COMPONENTS]
    rows = (
        await db.execute(
            sa.select(PayComponent).where(
                PayComponent.organization_id == organization_id,
                PayComponent.code.in_(codes),
            )
        )
    ).scalars()
    existing = {row.code: row for row in rows}
    for spec in STANDARD_COMPONENTS:
        row = existing.get(spec.code)
        if row is not None:
            if row.classification != spec.classification:
                raise ConflictError(
                    f"Standard component {spec.code} has classification "
                    f"{row.classification!r}; expected {spec.classification!r}."
                )
            row.is_standard = True
            row.is_active = True
            if row.schedule_kind is None:
                row.schedule_kind = spec.schedule_kind
            if row.schedule_title is None:
                row.schedule_title = spec.schedule_title
            if row.register_column is None:
                row.register_column = spec.register_column
            continue
        db.add(
            PayComponent(
                organization_id=organization_id,
                code=spec.code,
                name=spec.name,
                classification=spec.classification,
                display_order=spec.display_order,
                employer_transfer=spec.employer_transfer,
                transfer_of=spec.transfer_of,
                is_active=True,
                is_standard=True,
                schedule_kind=spec.schedule_kind,
                schedule_title=spec.schedule_title,
                register_column=spec.register_column,
            )
        )
