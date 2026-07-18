"""Phase 3 effective-dated master data tables.

Revision ID: 2f397740f38a
Revises: c8d4e2f1a9b7
Create Date: 2026-07-17

Creates org-structure, employee header + version tables, pay components,
recurring instructions, advances, accommodation, and report configurations.
Applies forced RLS (accord_app + accord_worker) on every new tenant-owned
table, and adds SELECT-only ``self_membership_read`` policies on the existing
``organization_memberships`` table so a user can list their own memberships
without scanning organizations.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

# revision identifiers, used by Alembic.
revision: str = "2f397740f38a"
down_revision: Union[str, None] = "c8d4e2f1a9b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _apply_forced_rls(table_name: str) -> None:
    """Enable forced RLS for ``accord_app`` and ``accord_worker``.

    ``rls_policy_sql`` returns multiple statements; asyncpg rejects multi-command
    prepared statements, so each statement is executed separately.
    """
    for role, policy_name in (
        ("accord_app", "tenant_isolation"),
        ("accord_worker", "tenant_isolation_worker"),
    ):
        sql = rls_policy_sql(table_name, role=role, policy_name=policy_name)
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                op.execute(statement)


def _apply_self_membership_read() -> None:
    """SELECT-only self-read policies on organization_memberships (OR-widening)."""
    predicate = "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
    for role, policy_name in (
        ("accord_app", "self_membership_read"),
        ("accord_worker", "self_membership_read_worker"),
    ):
        op.execute(
            f"CREATE POLICY {policy_name} ON organization_memberships\n"
            f"  FOR SELECT\n"
            f"  TO {role}\n"
            f"  USING (\n"
            f"    {predicate}\n"
            f"  )"
        )


def upgrade() -> None:
    op.create_table(
        "employee_groups",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_employee_groups_organization_id_code",
        ),
    )
    _apply_forced_rls("employee_groups")

    op.create_table(
        "employees",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("employee_number", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "employee_number",
            name="uq_employees_organization_id_employee_number",
        ),
    )
    _apply_forced_rls("employees")

    op.create_table(
        "offices",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "jurisdiction IN ('mumbai','nagpur','worli','other')",
            name="ck_offices_jurisdiction",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_offices_organization_id_code",
        ),
    )
    _apply_forced_rls("offices")

    op.create_table(
        "pay_components",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "classification IN ("
            "'earning',"
            "'employer_contribution',"
            "'ag_deduction',"
            "'treasury_deduction',"
            "'gross_adjustment',"
            "'external_recovery'"
            ")",
            name="ck_pay_components_classification",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_pay_components_organization_id_code",
        ),
    )
    _apply_forced_rls("pay_components")

    op.create_table(
        "payroll_units",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "code",
            name="uq_payroll_units_organization_id_code",
        ),
    )
    _apply_forced_rls("payroll_units")

    op.create_table(
        "posts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("class", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "designation",
            name="uq_posts_organization_id_designation",
        ),
    )
    _apply_forced_rls("posts")

    op.create_table(
        "report_configurations",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "key",
            name="uq_report_configurations_organization_id_key",
        ),
    )
    _apply_forced_rls("report_configurations")

    op.create_table(
        "accommodation_assignments",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("quarters_location", sa.Text(), nullable=False),
        sa.Column("quarters_identifier", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "quarters_location IN ('mumbai','worli','other')",
            name="ck_accommodation_assignments_quarters_location",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("accommodation_assignments")

    op.create_table(
        "advance_accounts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("advance_type", sa.Text(), nullable=False),
        sa.Column("principal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("sanctioned_on", sa.Date(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "advance_type IN ('hba','gpf_advance','festival','motor_car','motorcycle','other')",
            name="ck_advance_accounts_advance_type",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("advance_accounts")

    op.create_table(
        "component_rate_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=9, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("calc_kind", sa.Text(), nullable=False),
        sa.Column("basis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "rounding_rule",
            sa.Text(),
            server_default=sa.text("'ROUND_HALF_UP_RUPEE'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_component_rate_versions_overlap",
        ),
        sa.CheckConstraint(
            "calc_kind IN ("
            "'fixed_recurring_amount',"
            "'direct_monthly_amount',"
            "'percentage_of_component_bases',"
            "'employer_employee_contribution',"
            "'loan_installment_recovery',"
            "'accommodation_charge',"
            "'one_time_adjustment'"
            ")",
            name="ck_component_rate_versions_calc_kind",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_component_rate_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["pay_components.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("component_rate_versions")

    op.create_table(
        "employee_bank_account_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("ifsc", sa.Text(), nullable=False),
        sa.Column("bank_name", sa.Text(), nullable=False),
        sa.Column("branch", sa.Text(), nullable=False),
        sa.Column(
            "is_primary_salary",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            where=sa.text("is_primary_salary"),
            using="gist",
            name="ex_employee_bank_account_versions_primary_overlap",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_employee_bank_account_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("employee_bank_account_versions")

    op.create_table(
        "employee_pay_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("pay_matrix_level", sa.Text(), nullable=False),
        sa.Column("basic_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_employee_pay_versions_overlap",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_employee_pay_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("employee_pay_versions")

    op.create_table(
        "employee_posting_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("payroll_unit_id", sa.UUID(), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("employee_group_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_employee_posting_versions_overlap",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_employee_posting_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["employee_group_id"], ["employee_groups.id"]),
        sa.ForeignKeyConstraint(["header_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["payroll_unit_id"], ["payroll_units.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("employee_posting_versions")

    op.create_table(
        "employee_profile_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sevarth_id", sa.Text(), nullable=False),
        sa.Column("pan", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("date_of_joining", sa.Date(), nullable=False),
        sa.Column("retirement_regime", sa.Text(), nullable=False),
        sa.Column("gpf_jurisdiction", sa.Text(), nullable=True),
        sa.Column("pran", sa.Text(), nullable=True),
        sa.Column("gpf_account_number", sa.Text(), nullable=True),
        sa.Column("epf_number", sa.Text(), nullable=True),
        sa.Column("pension_account", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_employee_profile_versions_overlap",
        ),
        sa.CheckConstraint(
            "(retirement_regime = 'gpf' AND gpf_jurisdiction IS NOT NULL) OR "
            "(retirement_regime <> 'gpf' AND gpf_jurisdiction IS NULL)",
            name="ck_employee_profile_versions_gpf_jurisdiction_regime",
        ),
        sa.CheckConstraint(
            "gpf_jurisdiction IS NULL OR gpf_jurisdiction IN ('mumbai','nagpur')",
            name="ck_employee_profile_versions_gpf_jurisdiction",
        ),
        sa.CheckConstraint(
            "retirement_regime IN ('gpf','nps','epf')",
            name="ck_employee_profile_versions_retirement_regime",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_employee_profile_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("employee_profile_versions")

    op.create_table(
        "recurring_instructions",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("component_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["component_id"], ["pay_components.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("recurring_instructions")

    op.create_table(
        "accommodation_charge_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("license_fee", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "informational_hra_foregone",
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_accommodation_charge_versions_overlap",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_accommodation_charge_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["accommodation_assignments.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("accommodation_charge_versions")

    op.create_table(
        "advance_installment_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column(
            "installment_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column("installments_total", sa.Integer(), nullable=False),
        sa.Column("installments_recovered_opening", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_advance_installment_versions_overlap",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_advance_installment_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["advance_accounts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("advance_installment_versions")

    op.create_table(
        "recurring_instruction_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("header_id", sa.UUID(), nullable=False),
        sa.Column("validity", postgresql.DATERANGE(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rate", sa.Numeric(precision=9, scale=4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        postgresql.ExcludeConstraint(
            (sa.column("organization_id"), "="),
            (sa.column("header_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_recurring_instruction_versions_overlap",
        ),
        sa.CheckConstraint(
            "NOT isempty(validity)",
            name="ck_recurring_instruction_versions_validity_not_empty",
        ),
        sa.ForeignKeyConstraint(["header_id"], ["recurring_instructions.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("recurring_instruction_versions")

    _apply_self_membership_read()


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS self_membership_read_worker ON organization_memberships")
    op.execute("DROP POLICY IF EXISTS self_membership_read ON organization_memberships")

    op.drop_table("recurring_instruction_versions")
    op.drop_table("advance_installment_versions")
    op.drop_table("accommodation_charge_versions")
    op.drop_table("recurring_instructions")
    op.drop_table("employee_profile_versions")
    op.drop_table("employee_posting_versions")
    op.drop_table("employee_pay_versions")
    op.drop_table("employee_bank_account_versions")
    op.drop_table("component_rate_versions")
    op.drop_table("advance_accounts")
    op.drop_table("accommodation_assignments")
    op.drop_table("report_configurations")
    op.drop_table("posts")
    op.drop_table("payroll_units")
    op.drop_table("pay_components")
    op.drop_table("offices")
    op.drop_table("employees")
    op.drop_table("employee_groups")
