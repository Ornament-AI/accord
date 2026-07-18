"""Phase 2 identity and tenancy SQLModel tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
    CHAR,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID as PG_UUID
from sqlmodel import Field

from app.models.base import (
    OrganizationOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)


def _id_field() -> uuid.UUID:
    return Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )


def _created_at_field() -> datetime:
    return Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )


def _updated_at_field() -> datetime:
    return Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
            onupdate=utcnow,
        ),
    )


def _organization_id_field() -> uuid.UUID:
    # FK is declared here so SQLModel.metadata matches the migration DDL for
    # ``alembic check``. OrganizationOwnedMixin intentionally omits the FK.
    return Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("organizations.id"),
            nullable=False,
        ),
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    """Global user identity (WorkOS-backed)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workos_user_id", name="uq_users_workos_user_id"),
        # Case-insensitive uniqueness is enforced by the citext column type.
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    workos_user_id: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    email: str = Field(
        sa_column=Column(CITEXT, nullable=False),
    )
    name: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    is_platform_admin: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    """Global organization (tenant root)."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        UniqueConstraint(
            "workos_organization_id",
            name="uq_organizations_workos_organization_id",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    name: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    slug: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    workos_organization_id: Optional[str] = Field(
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


class OrganizationMembership(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OrganizationOwnedMixin,
    table=True,
):
    """Tenant-scoped link between a user and an organization with a role."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ("
            "'organization_administrator',"
            "'payroll_preparer',"
            "'payroll_reviewer',"
            "'payroll_approver',"
            "'report_releaser',"
            "'auditor'"
            ")",
            name="ck_organization_memberships_role",
        ),
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_organization_id_user_id",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
        ),
    )
    role: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("true"),
        ),
    )


class OrganizationSettings(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OrganizationOwnedMixin,
    table=True,
):
    """Per-organization configuration (one row per org)."""

    __tablename__ = "organization_settings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            name="uq_organization_settings_organization_id",
        ),
        CheckConstraint(
            "financial_year_start_month BETWEEN 1 AND 12",
            name="ck_organization_settings_financial_year_start_month",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    locale: str = Field(
        default="en-IN",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'en-IN'"),
        ),
    )
    timezone: str = Field(
        default="Asia/Kolkata",
        sa_column=Column(
            Text,
            nullable=False,
            server_default=text("'Asia/Kolkata'"),
        ),
    )
    currency: str = Field(
        default="INR",
        sa_column=Column(
            CHAR(3),
            nullable=False,
            server_default=text("'INR'"),
        ),
    )
    financial_year_start_month: int = Field(
        default=4,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("4"),
        ),
    )


class IdempotencyKey(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OrganizationOwnedMixin,
    table=True,
):
    """Tenant-scoped idempotency record for safe request retries."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed')",
            name="ck_idempotency_keys_status",
        ),
        UniqueConstraint(
            "organization_id",
            "key",
            name="uq_idempotency_keys_organization_id_key",
        ),
    )

    id: uuid.UUID = _id_field()
    created_at: datetime = _created_at_field()
    updated_at: datetime = _updated_at_field()
    organization_id: uuid.UUID = _organization_id_field()
    key: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    request_hash: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    response_snapshot: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    status: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Session(UUIDPrimaryKeyMixin, table=True):
    """Authenticated user session (global, not tenant-owned)."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index(
            "ix_sessions_active_id",
            "id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: uuid.UUID = _id_field()
    user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
        ),
    )
    active_organization_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("organizations.id"),
            nullable=True,
        ),
    )
    issued_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_seen_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    revoked_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    user_agent_hash: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
