"""Singleton-organization membership and invitation helpers (ADR 0011).

In-app member management was removed; access changes go through
``scripts/provision_member.py``. Pending invitations are still claimed on login.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.capabilities import MEMBERSHIP_ROLES
from app.exceptions import ConflictError, ValidationError
from app.models.base import utcnow
from app.models.identity import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)
from app.services.bootstrap import get_singleton_organization
from app.tenancy import bind_tenant_context

ADMIN_ROLE = "organization_administrator"


def validate_membership_role(role: str) -> str:
    if role not in MEMBERSHIP_ROLES:
        raise ValidationError(
            f"Invalid role '{role}'. Expected one of: {', '.join(sorted(MEMBERSHIP_ROLES))}."
        )
    return role


async def _count_active_admins(db: AsyncSession, organization_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.role == ADMIN_ROLE,
            OrganizationMembership.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def ensure_not_last_admin(
    db: AsyncSession,
    *,
    organization_id: UUID,
    target_membership: OrganizationMembership,
    next_role: str | None = None,
    next_active: bool | None = None,
) -> None:
    """Refuse mutations that would leave zero active organization administrators."""
    if target_membership.role != ADMIN_ROLE or not target_membership.is_active:
        return
    becoming_non_admin = next_role is not None and next_role != ADMIN_ROLE
    becoming_inactive = next_active is False
    if not becoming_non_admin and not becoming_inactive:
        return
    if await _count_active_admins(db, organization_id) <= 1:
        raise ConflictError(
            "Cannot demote or deactivate the last active organization administrator."
        )


async def provision_member(
    db: AsyncSession,
    *,
    organization_id: UUID,
    email: str,
    role: str,
    invited_by_user_id: UUID | None = None,
) -> tuple[str, str]:
    """Create membership or pending invitation. Returns (kind, id) kind in {membership, invitation}."""
    role = validate_membership_role(role)
    cleaned_email = email.strip()
    if not cleaned_email or "@" not in cleaned_email:
        raise ValidationError("A valid email is required.")

    await bind_tenant_context(db, organization_id=organization_id)
    user = (
        await db.execute(select(User).where(User.email == cleaned_email))
    ).scalar_one_or_none()

    if user is not None:
        existing = (
            await db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.is_active and existing.role == role:
                return "membership", str(existing.id)
            # Reactivate / role change — respect last-admin if demoting self-path later
            if existing.is_active and existing.role == ADMIN_ROLE and role != ADMIN_ROLE:
                await ensure_not_last_admin(
                    db,
                    organization_id=organization_id,
                    target_membership=existing,
                    next_role=role,
                )
            existing.role = role
            existing.is_active = True
            existing.updated_at = utcnow()
            await db.flush()
            return "membership", str(existing.id)

        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=user.id,
            role=role,
            is_active=True,
        )
        db.add(membership)
        await db.flush()
        return "membership", str(membership.id)

    existing_invite = (
        await db.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == cleaned_email,
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_invite is not None:
        existing_invite.role = role
        existing_invite.updated_at = utcnow()
        await db.flush()
        return "invitation", str(existing_invite.id)

    invite = OrganizationInvitation(
        organization_id=organization_id,
        email=cleaned_email,
        role=role,
        invited_by_user_id=invited_by_user_id,
    )
    db.add(invite)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A pending invitation for this email already exists.") from exc
    return "invitation", str(invite.id)


async def claim_pending_invitation(
    db: AsyncSession,
    user: User,
    org: Organization,
) -> OrganizationMembership | None:
    """Atomically accept a pending invitation for ``user.email`` in ``org``.

    Concurrent claims: only one UPDATE … WHERE accepted_at IS NULL wins;
    the loser finds an existing membership or returns None.
    """
    await bind_tenant_context(db, organization_id=org.id, user_id=user.id)

    existing = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org.id,
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    now = utcnow()
    claim = await db.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.organization_id == org.id,
            OrganizationInvitation.email == user.email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        .values(accepted_at=now, updated_at=now)
        .returning(OrganizationInvitation.id, OrganizationInvitation.role)
    )
    claimed = claim.first()
    if claimed is None:
        return None

    # begin_nested() flushes pending state before opening the SAVEPOINT, so
    # the membership must be added inside the nested block or a uniqueness race
    # aborts the outer transaction and the recovery SELECT cannot run.
    membership = OrganizationMembership(
        organization_id=org.id,
        user_id=user.id,
        role=claimed.role,
        is_active=True,
    )
    try:
        async with db.begin_nested():
            db.add(membership)
            await db.flush()
    except IntegrityError:
        # Parallel claim created membership first — load it without aborting
        # the outer transaction (invite accept UPDATE must stay visible).
        return (
            await db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org.id,
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
    return membership


async def require_singleton_org_id(db: AsyncSession) -> UUID:
    org = await get_singleton_organization(db)
    if org is None:
        raise ConflictError("Deployment is not bootstrapped. Run provision_organization.py.")
    return org.id
