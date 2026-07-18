"""SQLModel mixins and RLS helpers for Accord tenant-owned tables.

Phase 1 defines reusable mixins only — no concrete tenant tables yet.
Organizations, users, and domain tables land in Phase 2.

Phase 2 contract for the first tenant-owned table
-------------------------------------------------
1. Inherit the mixins::

       class Employee(
           UUIDPrimaryKeyMixin,
           TimestampMixin,
           OrganizationOwnedMixin,
           table=True,
       ):
           ...

2. In the Alembic migration that ``CREATE TABLE``s the model, immediately
   enable forced RLS via::

       from app.models.base import rls_policy_sql
       op.execute(rls_policy_sql("employees"))
       # Optionally also: op.execute(rls_policy_sql("employees", role="accord_worker"))

3. ``OrganizationOwnedMixin.organization_id`` is intentionally **not** a
   ForeignKey in Phase 1 (the ``organizations`` table does not exist yet).
   When ``organizations`` lands, Phase 2 must add the FK constraint, e.g.::

       op.create_foreign_key(
           "fk_<table>_organization_id",
           "<table>",
           "organizations",
           ["organization_id"],
           ["id"],
       )

   Prefer adding the FK in the same migration that creates ``organizations``
   (or immediately after) for every tenant-owned table that already exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp for Python-side defaults / onupdate."""
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin(SQLModel):
    """Primary key ``id`` with Postgres ``gen_random_uuid()`` server default.

    PostgreSQL 13+ (including 18.4) provides ``gen_random_uuid()`` in core;
    no ``pgcrypto`` extension is required for this default.
    """

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )


class TimestampMixin(SQLModel):
    """``created_at`` / ``updated_at`` as ``TIMESTAMP WITH TIME ZONE``."""

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
            onupdate=utcnow,
        ),
    )


class OrganizationOwnedMixin(SQLModel):
    """Tenant scope column for organization-owned rows.

    No ForeignKey here — ``organizations`` is created in Phase 2. Phase 2 must
    ``ALTER TABLE … ADD CONSTRAINT`` (or ``op.create_foreign_key``) linking
    ``organization_id`` → ``organizations.id`` once that table exists.
    """

    organization_id: uuid.UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), nullable=False),
    )


def rls_policy_sql(
    table_name: str,
    *,
    role: str = "accord_app",
    policy_name: str = "tenant_isolation",
) -> str:
    """Return ADR-0001 forced-RLS + tenant_isolation policy DDL for ``table_name``.

    Intended for use inside Alembic ``upgrade()`` via ``op.execute(...)``.
    Call once per runtime role that needs the policy (default ``accord_app``;
    also call with ``role="accord_worker"`` when worker access is required).
    """
    predicate = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
    return (
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;\n"
        f"\n"
        f"CREATE POLICY {policy_name} ON {table_name}\n"
        f"  FOR ALL\n"
        f"  TO {role}\n"
        f"  USING (\n"
        f"    {predicate}\n"
        f"  )\n"
        f"  WITH CHECK (\n"
        f"    {predicate}\n"
        f"  );\n"
    )
