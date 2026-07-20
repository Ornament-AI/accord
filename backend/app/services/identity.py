"""Identity session establishment and membership resolution (ADR 0011)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.adapters import AuthenticatedIdentity
from app.auth.capabilities import capabilities_for_role
from app.auth.errors import WeakSessionSecretError
from app.auth.principal import AuthPrincipal
from app.auth.session import DatabaseSessionStore, get_session_store
from app.config import Settings
from app.models.base import utcnow
from app.models.identity import Organization, OrganizationMembership, User
from app.models.identity import Session as SessionRow
from app.services.bootstrap import get_singleton_organization
from app.services.members import claim_pending_invitation
from app.tenancy import bind_tenant_context


async def upsert_user(db: AsyncSession, identity: AuthenticatedIdentity) -> User:
    """Create or update a local user keyed by WorkOS subject id."""
    result = await db.execute(select(User).where(User.workos_user_id == identity.subject_id))
    user = result.scalar_one_or_none()
    name = (identity.name or "").strip() or identity.email
    email = identity.email.strip()
    if user is None:
        user = User(
            workos_user_id=identity.subject_id,
            email=email,
            name=name,
        )
        db.add(user)
        await db.flush()
        return user

    changed = False
    if user.email != email:
        user.email = email
        changed = True
    if user.name != name:
        user.name = name
        changed = True
    if changed:
        user.updated_at = utcnow()
        await db.flush()
    return user


async def _ensure_txn(db: AsyncSession) -> None:
    if not db.in_transaction():
        await db.begin()


async def get_active_membership_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationMembership | None:
    await _ensure_txn(db)
    await bind_tenant_context(db, organization_id=organization_id, user_id=user_id)
    result = await db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_active_memberships(
    db: AsyncSession,
    user_id: UUID,
) -> list[tuple[Organization, OrganizationMembership]]:
    """Return active memberships for ``user_id`` (singleton org only under ADR 0011)."""
    org = await get_singleton_organization(db)
    if org is None:
        return []
    membership = await get_active_membership_for_org(
        db, organization_id=org.id, user_id=user_id
    )
    if membership is None:
        return []
    return [(org, membership)]


async def resolve_active_organization(
    db: AsyncSession,
    user: User,
    active_organization_id: UUID | None,
) -> tuple[Organization, OrganizationMembership] | None:
    """Resolve active org+membership, or None if missing/inactive membership.

    Organization ``is_active`` is ignored for product access (ADR 0011); any
    singleton row is treated as the deployment organization.
    """
    if active_organization_id is None:
        return None

    org = await db.get(Organization, active_organization_id)
    if org is None:
        return None

    membership = await get_active_membership_for_org(
        db, organization_id=active_organization_id, user_id=user.id
    )
    if membership is None:
        return None
    return org, membership


async def establish_session_for_identity(
    db: AsyncSession,
    settings: Settings,
    identity: AuthenticatedIdentity,
    *,
    user_agent_hash: str | None = None,
) -> tuple[User, str]:
    """Shared by login dev-bypass and callback.

    upsert user → claim invite → auto-bind singleton membership → create session.
    """
    user = await upsert_user(db, identity)
    org = await get_singleton_organization(db)
    active_organization_id = None
    if org is not None:
        membership = await claim_pending_invitation(db, user, org)
        if membership is None:
            membership = await get_active_membership_for_org(
                db, organization_id=org.id, user_id=user.id
            )
        if membership is not None:
            active_organization_id = org.id

    store = get_session_store(settings, db)
    cookie_value = await store.create_session(
        user_id=user.id,
        active_organization_id=active_organization_id,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    return user, cookie_value


async def build_me_payload(
    db: AsyncSession,
    user: User,
    session_row: SessionRow,
) -> dict:
    """Full ``GET /api/auth/me`` singular-organization response (ADR 0011)."""
    org = await get_singleton_organization(db)
    if org is None:
        return {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "is_platform_admin": bool(user.is_platform_admin),
            "access_state": "unbootstrapped",
            "organization": None,
            "membership": None,
        }

    organization = {"id": str(org.id), "name": org.name, "slug": org.slug}

    # Prefer session-bound membership; fall back to direct lookup (self-heal).
    active = await resolve_active_organization(
        db,
        user,
        session_row.active_organization_id or org.id,
    )
    if active is None:
        membership_row = await get_active_membership_for_org(
            db, organization_id=org.id, user_id=user.id
        )
        if membership_row is None:
            return {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "is_platform_admin": bool(user.is_platform_admin),
                "access_state": "unprovisioned",
                "organization": organization,
                "membership": None,
            }
        role = membership_row.role
    else:
        _, membership_row = active
        role = membership_row.role

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_platform_admin": bool(user.is_platform_admin),
        "access_state": "active",
        "organization": organization,
        "membership": {
            "role": role,
            "capabilities": sorted(capabilities_for_role(role)),
        },
    }


async def resolve_principal(
    db: AsyncSession,
    settings: Settings,
    cookie_value: str,
) -> AuthPrincipal | None:
    """Read session store → load user → resolve active org/role/capabilities."""
    try:
        store = DatabaseSessionStore(settings, db)
    except WeakSessionSecretError:
        return None
    session_row = await store.read_session(cookie_value)
    if session_row is None:
        return None

    user = await db.get(User, session_row.user_id)
    if user is None:
        return None

    org = await get_singleton_organization(db)
    active_org_id = session_row.active_organization_id
    if active_org_id is None and org is not None:
        # Self-heal: bind singleton when membership exists but session lacks it.
        membership = await get_active_membership_for_org(
            db, organization_id=org.id, user_id=user.id
        )
        if membership is not None:
            active_org_id = org.id

    active = await resolve_active_organization(db, user, active_org_id)
    if active is None:
        role: str | None = None
        organization_id: str | None = None
        caps: frozenset[str] = frozenset()
    else:
        resolved_org, membership = active
        role = membership.role
        organization_id = str(resolved_org.id)
        caps = capabilities_for_role(role)

    return AuthPrincipal(
        user_id=str(user.id),
        subject_id=user.workos_user_id,
        email=user.email,
        role=role,
        is_active=True,
        display_name=user.name,
        organization_id=organization_id,
        is_platform_admin=bool(user.is_platform_admin),
        capabilities=caps,
        session_id=str(session_row.id),
    )
