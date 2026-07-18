"""Phase 4 payroll run persistence tables.

Revision ID: 021faa7dd776
Revises: 2f397740f38a
Create Date: 2026-07-17

Creates payroll_periods, payroll_runs, payroll_run_inputs, payroll_run_versions,
payroll_employee_results, and payroll_result_lines (ADR-0007 aggregate model;
ADR-0008 workflow statuses for schema groundwork). Applies forced RLS
(accord_app + accord_worker) on every new tenant-owned table. Adds an
immutability trigger function ``accord_forbid_update_delete`` on the three
snapshot tables, with escape hatch GUC ``accord.allow_immutable_ddl``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.base import rls_policy_sql

# revision identifiers, used by Alembic.
revision: str = "021faa7dd776"
down_revision: Union[str, None] = "2f397740f38a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_TABLES = (
    "payroll_run_versions",
    "payroll_employee_results",
    "payroll_result_lines",
)


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


def _create_immutability_triggers() -> None:
    """Forbid UPDATE/DELETE on immutable snapshot tables unless escape GUC is on.

    Escape hatch: ``SET LOCAL accord.allow_immutable_ddl = 'on'`` inside a
    controlled transaction for reversal tooling / data migrations. Never leave
    this GUC globally on.
    """
    op.execute(
        """
        -- Escape hatch for future reversal tooling / data migrations.
        -- Must be set only via SET LOCAL accord.allow_immutable_ddl = 'on'
        -- inside a controlled transaction; never leave globally on.
        CREATE OR REPLACE FUNCTION accord_forbid_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $func$
        BEGIN
          IF current_setting('accord.allow_immutable_ddl', true) = 'on' THEN
            IF TG_OP = 'UPDATE' THEN
              RETURN NEW;
            END IF;
            RETURN OLD;
          END IF;
          RAISE EXCEPTION
            'accord: UPDATE/DELETE forbidden on immutable table %',
            TG_TABLE_NAME
            USING ERRCODE = 'integrity_constraint_violation';
        END;
        $func$;
        """
    )
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_forbid_update_delete
              BEFORE UPDATE OR DELETE ON {table_name}
              FOR EACH ROW
              EXECUTE FUNCTION accord_forbid_update_delete();
            """
        )


def upgrade() -> None:
    op.create_table(
        "payroll_periods",
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
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_payroll_periods_period_month",
        ),
        sa.CheckConstraint(
            "status IN ('open','closed')",
            name="ck_payroll_periods_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "period_year",
            "period_month",
            name="uq_payroll_periods_organization_id_period_year_period_month",
        ),
    )
    _apply_forced_rls("payroll_periods")

    op.create_table(
        "payroll_runs",
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
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column(
            "run_type",
            sa.Text(),
            server_default=sa.text("'regular'"),
            nullable=False,
        ),
        sa.Column("original_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        # FK to payroll_run_versions added after that table is created.
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "lock_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "run_type IN ('regular','supplemental','reversal')",
            name="ck_payroll_runs_run_type",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'draft',"
            "'calculating',"
            "'calculated',"
            "'submitted',"
            "'approved',"
            "'rejected',"
            "'posted',"
            "'reversed'"
            ")",
            name="ck_payroll_runs_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["period_id"], ["payroll_periods.id"]),
        sa.ForeignKeyConstraint(["original_run_id"], ["payroll_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _apply_forced_rls("payroll_runs")
    op.create_index(
        "ix_payroll_runs_org_period_run_type_regular",
        "payroll_runs",
        ["organization_id", "period_id", "run_type"],
        unique=True,
        postgresql_where=sa.text("run_type = 'regular'"),
    )

    op.create_table(
        "payroll_run_inputs",
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
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("component_code", sa.Text(), nullable=False),
        sa.Column("input_kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("rate", sa.Numeric(9, 4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("service_period_start", sa.Date(), nullable=True),
        sa.Column("service_period_end", sa.Date(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "input_kind IN ('exception','override','one_time')",
            name="ck_payroll_run_inputs_input_kind",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["payroll_runs.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "run_id",
            "employee_id",
            "component_code",
            "input_kind",
            name="uq_payroll_run_inputs_org_run_emp_comp_kind",
        ),
    )
    _apply_forced_rls("payroll_run_inputs")

    op.create_table(
        "payroll_run_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_by", sa.UUID(), nullable=False),
        sa.Column("inputs_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["payroll_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "run_id",
            "version_number",
            name="uq_payroll_run_versions_organization_id_run_id_version_number",
        ),
    )
    _apply_forced_rls("payroll_run_versions")

    op.create_table(
        "payroll_employee_results",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_version_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("employee_number", sa.Text(), nullable=False),
        sa.Column("earnings_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("employer_contribution_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("gross_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("deductions_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("net_payable", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_version_id"], ["payroll_run_versions.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "run_version_id",
            "employee_id",
            name="uq_payroll_employee_results_org_version_emp",
        ),
    )
    _apply_forced_rls("payroll_employee_results")

    op.create_table(
        "payroll_result_lines",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("employee_result_id", sa.UUID(), nullable=False),
        sa.Column("component_code", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("calc_kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        # ADR-0007 trace JSON: component, classification, source_version_ids,
        # basis, rate, unrounded_value, rounding_rule, rounded_value,
        # calculator_kind, engine_version.
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "classification IN ("
            "'earning',"
            "'employer_contribution',"
            "'ag_deduction',"
            "'treasury_deduction',"
            "'gross_adjustment',"
            "'external_recovery'"
            ")",
            name="ck_payroll_result_lines_classification",
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
            name="ck_payroll_result_lines_calc_kind",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["employee_result_id"], ["payroll_employee_results.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "employee_result_id",
            "component_code",
            "sequence",
            name="uq_payroll_result_lines_org_result_comp_seq",
        ),
    )
    _apply_forced_rls("payroll_result_lines")

    op.create_foreign_key(
        "fk_payroll_runs_current_version_id",
        "payroll_runs",
        "payroll_run_versions",
        ["current_version_id"],
        ["id"],
    )

    _create_immutability_triggers()


def downgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_forbid_update_delete ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS accord_forbid_update_delete()")

    op.drop_constraint(
        "fk_payroll_runs_current_version_id",
        "payroll_runs",
        type_="foreignkey",
    )

    op.drop_table("payroll_result_lines")
    op.drop_table("payroll_employee_results")
    op.drop_table("payroll_run_versions")
    op.drop_table("payroll_run_inputs")
    op.drop_index(
        "ix_payroll_runs_org_period_run_type_regular",
        table_name="payroll_runs",
    )
    op.drop_table("payroll_runs")
    op.drop_table("payroll_periods")
