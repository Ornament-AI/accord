"""Accommodation assignment header and charge version tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
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


class AccommodationAssignment(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OrganizationOwnedMixin,
    table=True,
):
    """Header for an employee's quarters / accommodation assignment."""

    __tablename__ = "accommodation_assignments"
    __table_args__ = (
        CheckConstraint(
            "quarters_location IN ('mumbai','worli','other')",
            name="ck_accommodation_assignments_quarters_location",
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
    quarters_location: str = Field(sa_column=Column(Text, nullable=False))
    quarters_identifier: str = Field(sa_column=Column(Text, nullable=False))
    quarters_address: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


accommodation_charge_versions = Table(
    "accommodation_charge_versions",
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
        ForeignKey("accommodation_assignments.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("license_fee", Numeric(12, 2), nullable=False),
    Column("house_rent", Numeric(12, 2), nullable=True),
    Column("service_charge", Numeric(12, 2), nullable=True),
    Column("parking_charge", Numeric(12, 2), nullable=True),
    Column("additional_parking_charge", Numeric(12, 2), nullable=True),
    Column("informational_hra_foregone", Numeric(12, 2), nullable=True),
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
        name="ck_accommodation_charge_versions_validity_not_empty",
    ),
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_accommodation_charge_versions_overlap",
    ),
)
