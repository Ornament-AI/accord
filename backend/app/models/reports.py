"""Report configuration key/value store (non-versioned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import OrganizationOwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.identity import (
    _created_at_field,
    _id_field,
    _organization_id_field,
    _updated_at_field,
)


class ReportConfiguration(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OrganizationOwnedMixin,
    table=True,
):
    """Per-organization report configuration blob keyed by string."""

    __tablename__ = "report_configurations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "key",
            name="uq_report_configurations_organization_id_key",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    key: str = Field(sa_column=Column(Text, nullable=False))
    value: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
