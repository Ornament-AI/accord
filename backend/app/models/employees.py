"""Employee header and effective-dated version tables (ADR-0005)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint, UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.models.base import OrganizationOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.identity import (
    _created_at_field,
    _id_field,
    _organization_id_field,
    _updated_at_field,
)


class Employee(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Stable employee identity header (immutable business key: employee_number)."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "employee_number",
            name="uq_employees_organization_id_employee_number",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    employee_number: str = Field(sa_column=Column(Text, nullable=False))


employee_profile_versions = Table(
    "employee_profile_versions",
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
        "header_id",
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("name", Text, nullable=False),
    Column("sevarth_id", Text, nullable=True),
    Column("pan", Text, nullable=True),
    Column("date_of_birth", Date, nullable=True),
    Column("date_of_joining", Date, nullable=True),
    Column("retirement_regime", Text, nullable=False),
    Column("gpf_jurisdiction", Text, nullable=True),
    Column("pran", Text, nullable=True),
    Column("gpf_account_number", Text, nullable=True),
    Column("epf_number", Text, nullable=True),
    Column("pension_account", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("created_by", PG_UUID(as_uuid=True), nullable=False),
    Column("change_reason", Text, nullable=True),
    CheckConstraint(
        "NOT isempty(validity)", name="ck_employee_profile_versions_validity_not_empty"
    ),
    CheckConstraint(
        "retirement_regime IN ('gpf','nps','epf')",
        name="ck_employee_profile_versions_retirement_regime",
    ),
    CheckConstraint(
        "gpf_jurisdiction IS NULL OR gpf_jurisdiction IN ('mumbai','nagpur')",
        name="ck_employee_profile_versions_gpf_jurisdiction",
    ),
    CheckConstraint(
        "retirement_regime = 'gpf' OR gpf_jurisdiction IS NULL",
        name="ck_employee_profile_versions_gpf_jurisdiction_regime",
    ),
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_employee_profile_versions_overlap",
    ),
)


employee_posting_versions = Table(
    "employee_posting_versions",
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
        "header_id",
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column(
        "office_id",
        PG_UUID(as_uuid=True),
        ForeignKey("offices.id"),
        nullable=False,
    ),
    Column(
        "post_id",
        PG_UUID(as_uuid=True),
        ForeignKey("posts.id"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("created_by", PG_UUID(as_uuid=True), nullable=False),
    Column("change_reason", Text, nullable=True),
    CheckConstraint(
        "NOT isempty(validity)", name="ck_employee_posting_versions_validity_not_empty"
    ),
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_employee_posting_versions_overlap",
    ),
)


employee_pay_versions = Table(
    "employee_pay_versions",
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
        "header_id",
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("pay_matrix_level", Text, nullable=True),
    Column("basic_pay", Numeric(12, 2), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("created_by", PG_UUID(as_uuid=True), nullable=False),
    Column("change_reason", Text, nullable=True),
    CheckConstraint("NOT isempty(validity)", name="ck_employee_pay_versions_validity_not_empty"),
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_employee_pay_versions_overlap",
    ),
)


employee_bank_account_versions = Table(
    "employee_bank_account_versions",
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
        "header_id",
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("account_number", Text, nullable=False),
    Column("ifsc", Text, nullable=False),
    Column("bank_name", Text, nullable=False),
    Column("branch", Text, nullable=True),
    Column(
        "is_primary_salary",
        Boolean,
        nullable=False,
        server_default=text("true"),
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("created_by", PG_UUID(as_uuid=True), nullable=False),
    Column("change_reason", Text, nullable=True),
    CheckConstraint(
        "NOT isempty(validity)",
        name="ck_employee_bank_account_versions_validity_not_empty",
    ),
    # Partial exclude: at most one primary salary account per employee per date.
    # Non-primary accounts may overlap freely with each other and with primary.
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        where=text("is_primary_salary"),
        name="ex_employee_bank_account_versions_primary_overlap",
    ),
)
