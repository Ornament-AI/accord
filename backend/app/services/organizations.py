"""Organization creation with correct RLS bind ordering (ADR-0001)."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import get_session_store
from app.config import Settings
from app.exceptions import ConflictError, ValidationError
from app.models.identity import Organization, OrganizationMembership, OrganizationSettings, User
from app.tenancy import bind_tenant_context

RESERVED_SLUGS = frozenset({"api", "admin", "app", "auth", "www"})
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_slug(slug: str) -> None:
    """Raise ValidationError if slug is reserved, malformed, or out of length bounds."""
    if not isinstance(slug, str) or not (2 <= len(slug) <= 50):
        raise ValidationError("Slug must be between 2 and 50 characters.")
    if not SLUG_RE.fullmatch(slug):
        raise ValidationError(
            "Slug must be lowercase kebab-case (letters, digits, and single hyphens)."
        )
    if slug in RESERVED_SLUGS:
        raise ValidationError(f"Slug '{slug}' is reserved.")


async def create_organization(
    db: AsyncSession,
    settings: Settings,
    *,
    user: User,
    name: str,
    slug: str,
    current_session_id: UUID,
    user_agent_hash: str | None = None,
) -> tuple[Organization, str]:
    """Create an organization and its admin membership; rotate the active session.

    Ordering for forced RLS under ``accord_app``:
    1. insert Organization (no RLS)
    2. flush → id
    3. bind_tenant_context(org.id, user.id)
    4. insert legacy OrganizationSettings compatibility row + membership
    5. rotate session
    6. commit
    """
    validate_slug(slug)
    org = Organization(name=name.strip(), slug=slug, is_active=True)
    db.add(org)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("An organization with this slug already exists.") from exc

    await bind_tenant_context(db, organization_id=org.id, user_id=user.id)

    db.add(OrganizationSettings(organization_id=org.id))
    db.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role="organization_administrator",
            is_active=True,
        )
    )
    await db.flush()

    store = get_session_store(settings, db)
    cookie_value = await store.rotate_session(
        old_session_id=current_session_id,
        user_id=user.id,
        active_organization_id=org.id,
        user_agent_hash=user_agent_hash,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("An organization with this slug already exists.") from exc

    await db.refresh(org)
    return org, cookie_value
