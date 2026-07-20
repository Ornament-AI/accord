"""Add catalog-driven report export persistence.

Revision ID: f2a7c9d4e601
Revises: c9f2e4a8b013
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

revision: str = "f2a7c9d4e601"
down_revision: str | None = "c9f2e4a8b013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STANDARD_COMPONENTS: tuple[
    tuple[str, str, str, int, bool, str | None, str | None, str | None], ...
] = (
    ("BASIC", "Basic Pay", "earning", 10, False, None, None, None),
    ("DA", "Dearness Allowance", "earning", 20, False, None, None, None),
    ("CLA", "City Compensatory Allowance", "earning", 30, False, None, None, None),
    ("HRA", "House Rent Allowance", "earning", 40, False, None, None, None),
    ("WASH_ALLOWANCE", "Wash Allowance", "earning", 50, False, None, None, None),
    ("OTHER_ALLOWANCE", "Other Allowance", "earning", 60, False, None, None, None),
    ("TRANSPORT", "Transport Allowance", "earning", 70, False, None, None, None),
    (
        "EPF_EMPLOYER",
        "EPF Employer Contribution",
        "employer_contribution",
        80,
        False,
        None,
        None,
        None,
    ),
    ("DA_DIFFERENCE", "DA Difference", "gross_adjustment", 90, False, None, None, None),
    ("GPF_SUBSCRIPTION", "GPF Subscription", "ag_deduction", 100, False, None, None, None),
    ("NPS_EMPLOYEE", "NPS Employee Contribution", "ag_deduction", 110, False, None, None, None),
    (
        "NPS_EMPLOYER_TRANSFER",
        "NPS Employer Transfer",
        "ag_deduction",
        120,
        True,
        None,
        None,
        None,
    ),
    ("EPF_EMPLOYEE", "EPF Employee Contribution", "ag_deduction", 130, False, None, None, None),
    (
        "EPF_EMPLOYER_TRANSFER",
        "EPF Employer Transfer",
        "ag_deduction",
        140,
        True,
        "EPF_EMPLOYER",
        None,
        None,
    ),
    ("INCOME_TAX", "Income Tax", "treasury_deduction", 150, False, None, None, None),
    (
        "PROFESSIONAL_TAX",
        "Professional Tax",
        "treasury_deduction",
        160,
        False,
        None,
        None,
        None,
    ),
    ("GIS", "Group Insurance Scheme", "treasury_deduction", 170, False, None, None, None),
    (
        "HBA_INSTALLMENT",
        "House Building Advance",
        "external_recovery",
        180,
        False,
        None,
        "loan_installment",
        "House Building Advance Recovery",
    ),
    (
        "GPF_ADVANCE_INSTALLMENT",
        "GPF Advance",
        "external_recovery",
        190,
        False,
        None,
        "loan_installment",
        "GPF Advance Recovery",
    ),
    (
        "FESTIVAL_ADVANCE_INSTALLMENT",
        "Festival Advance",
        "external_recovery",
        200,
        False,
        None,
        "loan_installment",
        "Festival Advance Recovery",
    ),
    (
        "MOTOR_CAR_ADVANCE_INSTALLMENT",
        "Motor Car Advance",
        "external_recovery",
        210,
        False,
        None,
        "loan_installment",
        "Motor Car Advance Recovery",
    ),
    (
        "MOTORCYCLE_ADVANCE_INSTALLMENT",
        "Motorcycle Advance",
        "external_recovery",
        220,
        False,
        None,
        "loan_installment",
        "Motorcycle Advance Recovery",
    ),
    (
        "OTHER_ADVANCE_INSTALLMENT",
        "Other Advance",
        "external_recovery",
        230,
        False,
        None,
        "loan_installment",
        "Other Advance Recovery",
    ),
    (
        "ACCOMMODATION_LICENSE_FEE",
        "Accommodation License Fee",
        "external_recovery",
        240,
        False,
        None,
        None,
        None,
    ),
    ("FOREGONE_HRA", "Foregone HRA", "informational", 250, False, None, None, None),
)


def _apply_forced_rls(table_name: str) -> None:
    for role, policy_name in (
        ("accord_app", "tenant_isolation"),
        ("accord_worker", "tenant_isolation_worker"),
    ):
        sql = rls_policy_sql(table_name, role=role, policy_name=policy_name)
        for statement in sql.split(";"):
            if statement.strip():
                op.execute(statement.strip())


def upgrade() -> None:
    op.drop_constraint("ck_pay_components_classification", "pay_components", type_="check")
    op.create_check_constraint(
        "ck_pay_components_classification",
        "pay_components",
        "classification IN ('earning','employer_contribution','ag_deduction',"
        "'treasury_deduction','gross_adjustment','external_recovery','informational')",
    )
    op.add_column(
        "pay_components",
        sa.Column("is_standard", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("pay_components", sa.Column("schedule_kind", sa.Text(), nullable=True))
    op.add_column("pay_components", sa.Column("schedule_title", sa.Text(), nullable=True))
    op.add_column("pay_components", sa.Column("schedule_account_head", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_pay_components_schedule_kind",
        "pay_components",
        "schedule_kind IS NULL OR schedule_kind IN ('simple_component','loan_installment')",
    )
    bind = op.get_bind()
    organization_ids = bind.execute(sa.text("SELECT id FROM organizations")).scalars().all()
    insert_standard = sa.text(
        """
        INSERT INTO pay_components (
          organization_id, code, name, classification, display_order,
          employer_transfer, transfer_of, is_active, is_standard,
          schedule_kind, schedule_title
        ) VALUES (
          :organization_id, :code, :name, :classification, :display_order,
          :employer_transfer, :transfer_of, true, true,
          :schedule_kind, :schedule_title
        )
        ON CONFLICT (organization_id, code) DO UPDATE SET
          is_standard = true,
          is_active = true,
          employer_transfer = EXCLUDED.employer_transfer,
          transfer_of = EXCLUDED.transfer_of,
          schedule_kind = COALESCE(pay_components.schedule_kind, EXCLUDED.schedule_kind),
          schedule_title = COALESCE(pay_components.schedule_title, EXCLUDED.schedule_title)
        WHERE pay_components.classification = EXCLUDED.classification
        """
    )
    for organization_id in organization_ids:
        bind.execute(
            insert_standard,
            [
                {
                    "organization_id": organization_id,
                    "code": code,
                    "name": name,
                    "classification": classification,
                    "display_order": display_order,
                    "employer_transfer": employer_transfer,
                    "transfer_of": transfer_of,
                    "schedule_kind": schedule_kind,
                    "schedule_title": schedule_title,
                }
                for (
                    code,
                    name,
                    classification,
                    display_order,
                    employer_transfer,
                    transfer_of,
                    schedule_kind,
                    schedule_title,
                ) in _STANDARD_COMPONENTS
            ],
        )
    op.add_column(
        "payroll_runs",
        sa.Column(
            "report_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("export_artifacts", sa.Column("variant_key", sa.Text(), nullable=True))

    op.create_table(
        "payroll_report_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_version_id", sa.UUID(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("source_checksum", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provenance IN ('posting','workbook_backfill','current_master_backfill')",
            name="ck_payroll_report_snapshots_provenance",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_version_id"], ["payroll_run_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "run_version_id",
            name="uq_payroll_report_snapshots_org_run_version",
        ),
    )
    _apply_forced_rls("payroll_report_snapshots")
    op.execute(
        """
        CREATE TRIGGER trg_payroll_report_snapshots_forbid_update_delete
          BEFORE UPDATE OR DELETE ON payroll_report_snapshots
          FOR EACH ROW
          EXECUTE FUNCTION accord_forbid_update_delete();
        """
    )
    # ADR-0009 grant/revoke backstop (see b33a3a7b5f84): the append-only trigger
    # alone is bypassable via SET LOCAL accord.allow_immutable_ddl, so revoke
    # UPDATE/DELETE/TRUNCATE from runtime roles. These frozen snapshots carry
    # payroll identity and bank data; INSERT + SELECT remain (insert-then-immutable).
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE payroll_report_snapshots "
        "FROM accord_app, accord_worker"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payroll_report_snapshots_forbid_update_delete "
        "ON payroll_report_snapshots"
    )
    op.drop_table("payroll_report_snapshots")
    op.drop_column("export_artifacts", "variant_key")
    op.drop_column("payroll_runs", "report_metadata")
    op.drop_constraint("ck_pay_components_schedule_kind", "pay_components", type_="check")
    op.drop_column("pay_components", "schedule_account_head")
    op.drop_column("pay_components", "schedule_title")
    op.drop_column("pay_components", "schedule_kind")
    op.drop_column("pay_components", "is_standard")
    op.execute(
        "UPDATE pay_components SET classification = 'earning' "
        "WHERE classification = 'informational'"
    )
    op.drop_constraint("ck_pay_components_classification", "pay_components", type_="check")
    op.create_check_constraint(
        "ck_pay_components_classification",
        "pay_components",
        "classification IN ('earning','employer_contribution','ag_deduction',"
        "'treasury_deduction','gross_adjustment','external_recovery')",
    )
