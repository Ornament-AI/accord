"""Accord SQLModel package.

Phase 1 exports shared mixins and the RLS policy helper only. Importing this
package populates ``SQLModel.metadata`` for Alembic (currently empty of tables
until Phase 2 adds concrete models).
"""

from app.models.base import (
    OrganizationOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    rls_policy_sql,
    utcnow,
)

__all__ = [
    "OrganizationOwnedMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "rls_policy_sql",
    "utcnow",
]
