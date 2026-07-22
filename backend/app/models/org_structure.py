"""Org structure master data (offices, posts)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Integer, Text, UniqueConstraint
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
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    name: str = Field(sa_column=Column(Text, nullable=False))
    jurisdiction: str = Field(sa_column=Column(Text, nullable=False))


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
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_posts_organization_id_id",
        ),
        CheckConstraint(
            "sanctioned_strength IS NULL OR sanctioned_strength >= 0",
            name="ck_posts_sanctioned_strength_nonnegative",
        ),
        CheckConstraint(
            "vacant_count IS NULL OR vacant_count >= 0",
            name="ck_posts_vacant_count_nonnegative",
        ),
        CheckConstraint(
            "vacant_count IS NULL OR (sanctioned_strength IS NOT NULL "
            "AND vacant_count <= sanctioned_strength)",
            name="ck_posts_vacant_not_above_sanctioned",
        ),
        CheckConstraint(
            "display_order IS NULL OR display_order >= 0",
            name="ck_posts_display_order_nonnegative",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    designation: str = Field(sa_column=Column(Text, nullable=False))
    pay_bill_heading: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    class_: str = Field(
        sa_column=Column("class", Text, nullable=False),
    )
    sanctioned_strength: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    vacant_count: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    pay_scale: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    display_order: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
