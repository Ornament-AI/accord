"""Org structure master data (offices, payroll units, posts, employee groups)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Text, UniqueConstraint
from sqlmodel import Field

from app.models.base import OrganizationOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.identity import (
    _created_at_field,
    _id_field,
    _organization_id_field,
    _updated_at_field,
)


class Office(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Physical / administrative office within an organization."""

    __tablename__ = "offices"
    __table_args__ = (
        CheckConstraint(
            "jurisdiction IN ('mumbai','nagpur','worli','other')",
            name="ck_offices_jurisdiction",
        ),
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_offices_organization_id_code",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    name: str = Field(sa_column=Column(Text, nullable=False))
    code: str = Field(sa_column=Column(Text, nullable=False))
    jurisdiction: str = Field(sa_column=Column(Text, nullable=False))


class PayrollUnit(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Payroll processing unit within an organization."""

    __tablename__ = "payroll_units"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_payroll_units_organization_id_code",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    name: str = Field(sa_column=Column(Text, nullable=False))
    code: str = Field(sa_column=Column(Text, nullable=False))


class Post(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Designation / post catalog entry.

    Natural key: ``UNIQUE (organization_id, designation)`` — designation is the
    stable human-facing label for a post within a tenant; ``class`` is an
    attribute of that designation and may change via future modeling if needed.
    """

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "designation",
            name="uq_posts_organization_id_designation",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    designation: str = Field(sa_column=Column(Text, nullable=False))
    class_: str = Field(
        sa_column=Column("class", Text, nullable=False),
    )


class EmployeeGroup(UUIDPrimaryKeyMixin, TimestampMixin, OrganizationOwnedMixin, table=True):
    """Employee grouping used for posting / payroll classification."""

    __tablename__ = "employee_groups"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_employee_groups_organization_id_code",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    name: str = Field(sa_column=Column(Text, nullable=False))
    code: str = Field(sa_column=Column(Text, nullable=False))
