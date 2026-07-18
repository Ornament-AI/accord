"""Recurring instruction header and amount/rate version tables.

No uniqueness constraint on the header beyond the primary key: the same
(employee_id, component_id) pair may legitimately appear as multiple headers
over time (e.g. closed then re-opened instructions). Temporal exclusivity is
enforced on ``recurring_instruction_versions.validity`` via GiST EXCLUDE.
"""

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


class RecurringInstruction(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OrganizationOwnedMixin,
    table=True,
):
    """Header linking an employee to a pay component for recurring amounts."""

    __tablename__ = "recurring_instructions"

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
    component_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("pay_components.id"),
            nullable=False,
        ),
    )


recurring_instruction_versions = Table(
    "recurring_instruction_versions",
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
        ForeignKey("recurring_instructions.id"),
        nullable=False,
    ),
    Column("validity", DATERANGE(), nullable=False),
    Column("amount", Numeric(12, 2), nullable=True),
    Column("rate", Numeric(9, 4), nullable=True),
    Column("reason", Text, nullable=True),
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
        name="ck_recurring_instruction_versions_validity_not_empty",
    ),
    ExcludeConstraint(
        ("organization_id", "="),
        ("header_id", "="),
        ("validity", "&&"),
        using="gist",
        name="ex_recurring_instruction_versions_overlap",
    ),
)
