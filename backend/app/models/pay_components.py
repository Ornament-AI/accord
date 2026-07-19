"""Pay component catalog header and rate version tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint, JSONB, UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.models.base import OrganizationOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.identity import (
    _created_at_field,
    _id_field,
    _organization_id_field,
    _updated_at_field,
)


class PayComponent(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Stable pay-component catalog header (immutable business key: code)."""

    __tablename__ = "pay_components"
    __table_args__ = (
        CheckConstraint(
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
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_pay_components_organization_id_code",
        ),
        CheckConstraint(
            "transfer_of IS NULL OR employer_transfer",
            name="ck_pay_components_transfer_of_requires_employer_transfer",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    code: str = Field(sa_column=Column(Text, nullable=False))
    name: str = Field(sa_column=Column(Text, nullable=False))
    classification: str = Field(sa_column=Column(Text, nullable=False))
    # Employer-transfer pairing drives off-bill remittance and therefore
    # disbursement (docs/payroll-domain.md "Resolved"). ``transfer_of`` is the
    # employer_contribution code this line reverses; NULL on an employer_transfer
    # line means there is no gross-bill addition, i.e. off-bill (NPS employer).
    employer_transfer: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    transfer_of: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("true"),
        ),
    )
    display_order: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
        ),
    )


component_rate_versions = Table(
    "component_rate_versions",
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
        ForeignKey("pay_components.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("rate", Numeric(9, 4), nullable=True),
    Column("amount", Numeric(12, 2), nullable=True),
    Column("calc_kind", Text, nullable=False),
    Column("basis", JSONB, nullable=True),
    Column(
        "rounding_rule",
        Text,
        nullable=False,
        server_default=text("'ROUND_HALF_UP_RUPEE'"),
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("created_by", PG_UUID(as_uuid=True), nullable=False),
    Column("change_reason", Text, nullable=True),
    CheckConstraint("NOT isempty(validity)", name="ck_component_rate_versions_validity_not_empty"),
    CheckConstraint(
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
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_component_rate_versions_overlap",
    ),
)
