"""Accord SQLModel package.

Phase 1 exports shared mixins and the RLS policy helper. Phase 2 adds identity
and tenancy tables (users, organizations, memberships, settings, idempotency
keys, sessions). Importing this package populates ``SQLModel.metadata`` for
Alembic.
"""

from app.models.base import (
    OrganizationOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    rls_policy_sql,
    utcnow,
)
from app.models.identity import (
    IdempotencyKey,
    Organization,
    OrganizationMembership,
    OrganizationSettings,
    Session,
    User,
)

__all__ = [
    "IdempotencyKey",
    "Organization",
    "OrganizationMembership",
    "OrganizationOwnedMixin",
    "OrganizationSettings",
    "Session",
    "TimestampMixin",
    "User",
    "UUIDPrimaryKeyMixin",
    "rls_policy_sql",
    "utcnow",
]
