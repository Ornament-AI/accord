"""Advance account header and installment version tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Table,
    Text,
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


class AdvanceAccount(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Header for an employee advance / loan recovery account."""

    __tablename__ = "advance_accounts"
    __table_args__ = (
        CheckConstraint(
            "advance_type IN ('hba','gpf_advance','festival','motor_car','motorcycle','other')",
            name="ck_advance_accounts_advance_type",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    employee_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("employees.id"),
            nullable=False,
        ),
    )
    advance_type: str = Field(sa_column=Column(Text, nullable=False))
    principal: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    sanctioned_on: date = Field(sa_column=Column(Date, nullable=False))
    reference: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )


advance_installment_versions = Table(
    "advance_installment_versions",
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
        ForeignKey("advance_accounts.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("installment_amount", Numeric(12, 2), nullable=False),
    Column("installments_total", Integer, nullable=False),
    Column("installments_recovered_opening", Integer, nullable=False),
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
        name="ck_advance_installment_versions_validity_not_empty",
    ),
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_advance_installment_versions_overlap",
    ),
)
