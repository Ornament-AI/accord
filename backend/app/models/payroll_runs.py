"""Payroll run persistence tables (ADR-0007 / ADR-0008).

Header-style SQLModel classes for mutable aggregates (periods, runs, draft
inputs) and plain SQLAlchemy ``Table`` objects for immutable calculation
snapshots (run versions, employee results, result lines).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.models.base import OrganizationOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.identity import (
    _created_at_field,
    _id_field,
    _organization_id_field,
    _updated_at_field,
)

_CLASSIFICATION_CHECK = (
    "classification IN ("
    "'earning',"
    "'employer_contribution',"
    "'ag_deduction',"
    "'treasury_deduction',"
    "'gross_adjustment',"
    "'external_recovery'"
    ")"
)

_CALC_KIND_CHECK = (
    "calc_kind IN ("
    "'fixed_recurring_amount',"
    "'direct_monthly_amount',"
    "'percentage_of_component_bases',"
    "'employer_employee_contribution',"
    "'loan_installment_recovery',"
    "'accommodation_charge',"
    "'one_time_adjustment'"
    ")"
)


class PayrollPeriod(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Pay calendar period (year/month) for an organization."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_payroll_periods_period_month",
        ),
        CheckConstraint(
            "status IN ('open','closed')",
            name="ck_payroll_periods_status",
        ),
        UniqueConstraint(
            "organization_id",
            "period_year",
            "period_month",
            name="uq_payroll_periods_organization_id_period_year_period_month",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    period_year: int = Field(sa_column=Column(Integer, nullable=False))
    period_month: int = Field(sa_column=Column(Integer, nullable=False))
    status: str = Field(
        default="open",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'open'"),
        ),
    )


class PayrollRun(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Payroll execution instance for a period (mutable workflow header)."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type IN ('regular','supplemental','reversal')",
            name="ck_payroll_runs_run_type",
        ),
        CheckConstraint(
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
        Index(
            "ix_payroll_runs_org_period_run_type_regular",
            "organization_id",
            "period_id",
            "run_type",
            unique=True,
            postgresql_where=text("run_type = 'regular'"),
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    period_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payroll_periods.id"),
            nullable=False,
        ),
    )
    run_type: str = Field(
        default="regular",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'regular'"),
        ),
    )
    original_run_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payroll_runs.id"),
            nullable=True,
        ),
    )
    status: str = Field(
        default="draft",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'draft'"),
        ),
    )
    current_version_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey(
                "payroll_run_versions.id",
                name="fk_payroll_runs_current_version_id",
                use_alter=True,
            ),
            nullable=True,
        ),
    )
    lock_version: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
        ),
    )


class PayrollRunInput(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Mutable draft exception / override / one-time input for a run."""

    __tablename__ = "payroll_run_inputs"
    __table_args__ = (
        CheckConstraint(
            "input_kind IN ('exception','override','one_time')",
            name="ck_payroll_run_inputs_input_kind",
        ),
        UniqueConstraint(
            "organization_id",
            "run_id",
            "employee_id",
            "component_code",
            "input_kind",
            name="uq_payroll_run_inputs_org_run_emp_comp_kind",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    run_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payroll_runs.id"),
            nullable=False,
        ),
    )
    employee_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("employees.id"),
            nullable=False,
        ),
    )
    component_code: str = Field(sa_column=Column(Text, nullable=False))
    input_kind: str = Field(sa_column=Column(Text, nullable=False))
    amount: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(12, 2), nullable=True),
    )
    rate: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(9, 4), nullable=True),
    )
    reason: str = Field(sa_column=Column(Text, nullable=False))
    service_period_start: Optional[date] = Field(
        default=None,
        sa_column=Column(Date, nullable=True),
    )
    service_period_end: Optional[date] = Field(
        default=None,
        sa_column=Column(Date, nullable=True),
    )
    version: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
        ),
    )
    created_by: uuid.UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), nullable=False),
    )
    updated_by: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(PG_UUID(as_uuid=True), nullable=True),
    )


# Immutable calculation snapshot tables (append-only; DB triggers forbid UPDATE/DELETE).

payroll_run_versions = Table(
    "payroll_run_versions",
    SQLModel.metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=text("gen_random_uuid()"),
    ),
    Column(
        "organization_id",
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "run_id",
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_runs.id"),
        nullable=False,
    ),
    Column("version_number", Integer, nullable=False),
    Column("engine_version", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("calculated_at", DateTime(timezone=True), nullable=False),
    Column("calculated_by", PG_UUID(as_uuid=True), nullable=False),
    Column("inputs_snapshot", JSONB, nullable=False),
    Column("totals", JSONB, nullable=False),
    UniqueConstraint(
        "organization_id",
        "run_id",
        "version_number",
        name="uq_payroll_run_versions_organization_id_run_id_version_number",
    ),
)

payroll_employee_results = Table(
    "payroll_employee_results",
    SQLModel.metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=text("gen_random_uuid()"),
    ),
    Column(
        "organization_id",
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "run_version_id",
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_run_versions.id"),
        nullable=False,
    ),
    Column(
        "employee_id",
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    ),
    Column("employee_number", Text, nullable=False),
    Column("earnings_total", Numeric(14, 2), nullable=False),
    Column("employer_contribution_total", Numeric(14, 2), nullable=False),
    Column("gross_total", Numeric(14, 2), nullable=False),
    Column("deductions_total", Numeric(14, 2), nullable=False),
    Column("net_payable", Numeric(14, 2), nullable=False),
    UniqueConstraint(
        "organization_id",
        "run_version_id",
        "employee_id",
        name="uq_payroll_employee_results_org_version_emp",
    ),
)

payroll_result_lines = Table(
    "payroll_result_lines",
    SQLModel.metadata,
    Column(
        "id",
        PG_UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=text("gen_random_uuid()"),
    ),
    Column(
        "organization_id",
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "employee_result_id",
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_employee_results.id"),
        nullable=False,
    ),
    Column("component_code", Text, nullable=False),
    Column("classification", Text, nullable=False),
    Column("calc_kind", Text, nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("sequence", Integer, nullable=False),
    # ADR-0007 trace payload: component, classification, source_version_ids,
    # basis, rate, unrounded_value, rounding_rule, rounded_value,
    # calculator_kind, engine_version (shape enforced in app layer, not DB).
    Column("trace", JSONB, nullable=False),
    CheckConstraint(
        _CLASSIFICATION_CHECK,
        name="ck_payroll_result_lines_classification",
    ),
    CheckConstraint(
        _CALC_KIND_CHECK,
        name="ck_payroll_result_lines_calc_kind",
    ),
    UniqueConstraint(
        "organization_id",
        "employee_result_id",
        "component_code",
        "sequence",
        name="uq_payroll_result_lines_org_result_comp_seq",
    ),
)

# Re-export typing helper for callers that annotate JSON payloads.
AnyDict = dict[str, Any]
