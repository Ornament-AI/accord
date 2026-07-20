"""Privileged singleton organization bootstrap (ADR 0011).

Called only from ops CLI with migrator/ops DB credentials. Not an HTTP path.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, ValidationError
from app.models.identity import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationSettings,
    User,
)
from app.services.organizations import validate_slug
from app.services.default_catalog import ensure_standard_components
from app.tenancy import bind_tenant_context


@dataclass(frozen=True)
class BootstrapResult:
    organization: Organization
    created: bool
    """True when a new organization row was inserted."""


async def _count_organizations(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(Organization))
    return int(result.scalar_one())


async def get_singleton_organization(db: AsyncSession) -> Organization | None:
    result = await db.execute(select(Organization).limit(2))
    orgs = list(result.scalars().all())
    if not orgs:
        return None
    if len(orgs) > 1:
        raise ConflictError(
            "Multiple organizations exist. Reset or prune to a single row before continuing."
        )
    return orgs[0]


async def _admin_intent_matches(
    db: AsyncSession,
    org: Organization,
    *,
    admin_email: str,
) -> bool:
    """True when admin_email already has active admin membership or pending admin invite."""
    email = admin_email.strip()
    await bind_tenant_context(db, organization_id=org.id)

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is not None:
        membership = (
            await db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org.id,
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.is_active.is_(True),
                    OrganizationMembership.role == "organization_administrator",
                )
            )
        ).scalar_one_or_none()
        if membership is not None:
            return True

    invite = (
        await db.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == org.id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.role == "organization_administrator",
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    return invite is not None


async def provision_organization(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    admin_email: str,
) -> BootstrapResult:
    """Create the singleton org or verify an identical prior bootstrap.

    Non-escalating: divergent name/slug/admin_email when an org exists raises
    ConflictError and never adds administrators.
    """
    cleaned_name = name.strip()
    cleaned_email = admin_email.strip()
    if not cleaned_name:
        raise ValidationError("Organization name is required.")
    if not cleaned_email or "@" not in cleaned_email:
        raise ValidationError("A valid admin email is required.")
    validate_slug(slug)

    existing = await get_singleton_organization(db)
    if existing is not None:
        if (
            existing.name == cleaned_name
            and existing.slug == slug
            and await _admin_intent_matches(db, existing, admin_email=cleaned_email)
        ):
            await bind_tenant_context(db, organization_id=existing.id)
            await ensure_standard_components(db, organization_id=existing.id)
            await db.commit()
            return BootstrapResult(organization=existing, created=False)
        raise ConflictError(
            "Organization already exists with different name, slug, or admin. "
            "Use provision_member.py to change access; do not re-bootstrap."
        )

    org = Organization(name=cleaned_name, slug=slug, is_active=True)
    db.add(org)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Concurrent create or slug race — surface as conflict.
        raise ConflictError(
            "Organization already exists (singleton constraint). "
            "Re-run with the same name, slug, and admin email for a no-op, "
            "or use provision_member for access changes."
        ) from exc

    await bind_tenant_context(db, organization_id=org.id)
    db.add(OrganizationSettings(organization_id=org.id))
    await ensure_standard_components(db, organization_id=org.id)

    user = (await db.execute(select(User).where(User.email == cleaned_email))).scalar_one_or_none()
    if user is not None:
        db.add(
            OrganizationMembership(
                organization_id=org.id,
                user_id=user.id,
                role="organization_administrator",
                is_active=True,
            )
        )
    else:
        db.add(
            OrganizationInvitation(
                organization_id=org.id,
                email=cleaned_email,
                role="organization_administrator",
                invited_by_user_id=None,
            )
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Organization already exists (singleton constraint).") from exc

    await db.refresh(org)
    return BootstrapResult(organization=org, created=True)


async def assert_organizations_singleton_preflight(db: AsyncSession) -> None:
    """Raise ConflictError when more than one organization row exists."""
    count = await _count_organizations(db)
    if count > 1:
        raise ConflictError(
            f"Found {count} organizations; singleton index requires at most one. "
            "For e2e: scripts/reset_e2e_db.sh --i-understand-this-deletes-data "
            "(allowlisted test DB names only). Otherwise prune to one row with ops SQL."
        )
