"""Add canonical pay-bill export metadata.

Revision ID: a7d3e5f9b102
Revises: f2a7c9d4e601
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d3e5f9b102"
down_revision: str | None = "f2a7c9d4e601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGISTER_COLUMNS = (
    "'basic_pay','dearness_allowance','city_compensatory_allowance',"
    "'house_rent_allowance','wash_child_other_charges',"
    "'other_reimbursement_salary_increment_difference',"
    "'additional_conveyance_transport_allowance','transport_pta_honorarium',"
    "'employer_share','festival_advance_other_recovery',"
    "'gpf_subscription_refund_arrears','pension_employer_share',"
    "'pension_employee_share','advances','flood_affected','income_tax',"
    "'insurance','house_rent_service_charge_arrears','professional_tax',"
    "'cooperative_recovery'"
)


def upgrade() -> None:
    op.add_column(
        "employee_profile_versions",
        sa.Column("payroll_export_remark", sa.Text(), nullable=True),
    )
    op.add_column("posts", sa.Column("sanctioned_strength", sa.Integer(), nullable=True))
    op.add_column("posts", sa.Column("vacant_count", sa.Integer(), nullable=True))
    op.add_column("posts", sa.Column("pay_scale", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("display_order", sa.Integer(), nullable=True))
    op.add_column("posts", sa.Column("pay_bill_heading", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_posts_organization_id_id",
        "posts",
        ["organization_id", "id"],
    )
    op.add_column(
        "employee_posting_versions",
        sa.Column("pay_bill_post_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE employee_posting_versions SET pay_bill_post_id = post_id "
        "WHERE pay_bill_post_id IS NULL"
    )
    op.create_foreign_key(
        "fk_employee_posting_versions_org_pay_bill_post",
        "employee_posting_versions",
        "posts",
        ["organization_id", "pay_bill_post_id"],
        ["organization_id", "id"],
    )
    op.create_index(
        "ix_employee_posting_versions_org_pay_bill_post_id",
        "employee_posting_versions",
        ["organization_id", "pay_bill_post_id"],
    )
    op.create_check_constraint(
        "ck_posts_sanctioned_strength_nonnegative",
        "posts",
        "sanctioned_strength IS NULL OR sanctioned_strength >= 0",
    )
    op.create_check_constraint(
        "ck_posts_vacant_count_nonnegative",
        "posts",
        "vacant_count IS NULL OR vacant_count >= 0",
    )
    op.create_check_constraint(
        "ck_posts_vacant_not_above_sanctioned",
        "posts",
        "vacant_count IS NULL OR (sanctioned_strength IS NOT NULL "
        "AND vacant_count <= sanctioned_strength)",
    )
    op.create_check_constraint(
        "ck_posts_display_order_nonnegative",
        "posts",
        "display_order IS NULL OR display_order >= 0",
    )

    op.add_column("pay_components", sa.Column("register_column", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_pay_components_register_column",
        "pay_components",
        f"register_column IS NULL OR register_column IN ({_REGISTER_COLUMNS})",
    )
    op.execute(
        sa.text(
            """
            INSERT INTO pay_components (
              organization_id, code, name, classification, display_order,
              is_active, is_standard, register_column
            )
            SELECT id, 'ADDITIONAL_ALLOWANCE', 'Additional Conveyance / Allowance',
              'earning', 65, true, true, 'additional_conveyance_transport_allowance'
            FROM organizations
            ON CONFLICT (organization_id, code) DO UPDATE SET
              is_standard = true,
              is_active = true,
              register_column = COALESCE(
                pay_components.register_column,
                EXCLUDED.register_column
              )
            WHERE pay_components.classification = EXCLUDED.classification
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE pay_components
            SET register_column = CASE code
              WHEN 'BASIC' THEN 'basic_pay'
              WHEN 'DA' THEN 'dearness_allowance'
              WHEN 'CLA' THEN 'city_compensatory_allowance'
              WHEN 'HRA' THEN 'house_rent_allowance'
              WHEN 'WASH_ALLOWANCE' THEN 'wash_child_other_charges'
              WHEN 'OTHER_ALLOWANCE' THEN 'other_reimbursement_salary_increment_difference'
              WHEN 'ADDITIONAL_ALLOWANCE' THEN 'additional_conveyance_transport_allowance'
              WHEN 'TRANSPORT' THEN 'transport_pta_honorarium'
              WHEN 'EPF_EMPLOYER' THEN 'employer_share'
              WHEN 'DA_DIFFERENCE' THEN 'dearness_allowance'
              WHEN 'GPF_SUBSCRIPTION' THEN 'gpf_subscription_refund_arrears'
              WHEN 'NPS_EMPLOYEE' THEN 'pension_employee_share'
              WHEN 'NPS_EMPLOYER_TRANSFER' THEN 'pension_employer_share'
              WHEN 'EPF_EMPLOYEE' THEN 'pension_employee_share'
              WHEN 'EPF_EMPLOYER_TRANSFER' THEN 'pension_employer_share'
              WHEN 'INCOME_TAX' THEN 'income_tax'
              WHEN 'PROFESSIONAL_TAX' THEN 'professional_tax'
              WHEN 'GIS' THEN 'insurance'
              WHEN 'FESTIVAL_ADVANCE_INSTALLMENT' THEN 'festival_advance_other_recovery'
              WHEN 'ACCOMMODATION_LICENSE_FEE' THEN 'house_rent_service_charge_arrears'
              ELSE 'advances'
            END
            WHERE register_column IS NULL
              AND code IN (
                'BASIC','DA','CLA','HRA','WASH_ALLOWANCE','OTHER_ALLOWANCE',
                'ADDITIONAL_ALLOWANCE','TRANSPORT',
                'EPF_EMPLOYER','DA_DIFFERENCE','GPF_SUBSCRIPTION','NPS_EMPLOYEE',
                'NPS_EMPLOYER_TRANSFER','EPF_EMPLOYEE','EPF_EMPLOYER_TRANSFER','INCOME_TAX',
                'PROFESSIONAL_TAX','GIS','HBA_INSTALLMENT','GPF_ADVANCE_INSTALLMENT',
                'FESTIVAL_ADVANCE_INSTALLMENT','MOTOR_CAR_ADVANCE_INSTALLMENT',
                'MOTORCYCLE_ADVANCE_INSTALLMENT','OTHER_ADVANCE_INSTALLMENT',
                'ACCOMMODATION_LICENSE_FEE'
              )
            """
        )
    )
    op.add_column(
        "accommodation_assignments",
        sa.Column("quarters_address", sa.Text(), nullable=True),
    )
    op.add_column(
        "accommodation_charge_versions",
        sa.Column("house_rent", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "accommodation_charge_versions",
        sa.Column("service_charge", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "accommodation_charge_versions",
        sa.Column("parking_charge", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "accommodation_charge_versions",
        sa.Column("additional_parking_charge", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accommodation_charge_versions", "additional_parking_charge")
    op.drop_column("accommodation_charge_versions", "parking_charge")
    op.drop_column("accommodation_charge_versions", "service_charge")
    op.drop_column("accommodation_charge_versions", "house_rent")
    op.drop_column("accommodation_assignments", "quarters_address")
    op.drop_constraint("ck_pay_components_register_column", "pay_components", type_="check")
    op.drop_column("pay_components", "register_column")

    op.drop_index(
        "ix_employee_posting_versions_org_pay_bill_post_id",
        table_name="employee_posting_versions",
    )
    op.drop_constraint(
        "fk_employee_posting_versions_org_pay_bill_post",
        "employee_posting_versions",
        type_="foreignkey",
    )
    op.drop_column("employee_posting_versions", "pay_bill_post_id")
    op.drop_constraint("uq_posts_organization_id_id", "posts", type_="unique")
    op.drop_column("posts", "pay_bill_heading")

    op.drop_constraint("ck_posts_display_order_nonnegative", "posts", type_="check")
    op.drop_constraint("ck_posts_vacant_not_above_sanctioned", "posts", type_="check")
    op.drop_constraint("ck_posts_vacant_count_nonnegative", "posts", type_="check")
    op.drop_constraint("ck_posts_sanctioned_strength_nonnegative", "posts", type_="check")
    op.drop_column("posts", "display_order")
    op.drop_column("posts", "pay_scale")
    op.drop_column("posts", "vacant_count")
    op.drop_column("posts", "sanctioned_strength")
    op.drop_column("employee_profile_versions", "payroll_export_remark")
