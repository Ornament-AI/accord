"""Identity session establishment and membership resolution."""

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


async def list_active_memberships(
    db: AsyncSession,
    user_id: UUID,
) -> list[tuple[Organization, OrganizationMembership]]:
    """Return active memberships in active organizations for ``user_id``.

    Note: ``organization_memberships`` is forced-RLS (org-scoped). Under the
    real ``accord_app`` role, a bare cross-org SELECT returns zero rows unless
    ``app.organization_id`` is bound. Phase 2 discovers candidates by scanning
    non-RLS ``organizations`` and binding each org before the membership read.
    # TODO(Phase 3): replace with a dedicated ``user_id = app.user_id`` SELECT
    # policy (or SECURITY DEFINER helper) so /me listing does not scan orgs.
    """
    org_result = await db.execute(
        select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name)
    )
    organizations = list(org_result.scalars().all())
    found: list[tuple[Organization, OrganizationMembership]] = []
    for org in organizations:
        await _ensure_txn(db)
        await bind_tenant_context(db, organization_id=org.id, user_id=user_id)
        mem_result = await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org.id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.is_active.is_(True),
            )
        )
        membership = mem_result.scalar_one_or_none()
        if membership is not None:
            found.append((org, membership))
    return found


async def resolve_active_organization(
    db: AsyncSession,
    user: User,
    active_organization_id: UUID | None,
) -> tuple[Organization, OrganizationMembership] | None:
    """Resolve active org+membership, or None if inactive (self-heal).

    Binds tenant GUCs for the candidate org before the membership read so the
    query succeeds under forced RLS for ``accord_app``.
    """
    if active_organization_id is None:
        return None

    org = await db.get(Organization, active_organization_id)
    if org is None or not org.is_active:
        return None

    await _ensure_txn(db)
    await bind_tenant_context(
        db,
        organization_id=active_organization_id,
        user_id=user.id,
    )
    mem_result = await db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == active_organization_id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    membership = mem_result.scalar_one_or_none()
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

    upsert user → list active memberships → if exactly 1, auto-activate →
    create DB session → commit → return (user, cookie_value).
    """
    user = await upsert_user(db, identity)
    memberships = await list_active_memberships(db, user.id)
    active_organization_id = memberships[0][0].id if len(memberships) == 1 else None
    store = get_session_store(settings, db)
    cookie_value = await store.create_session(
        user_id=user.id,
        active_organization_id=active_organization_id,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    return user, cookie_value


def _org_summary(org: Organization, membership: OrganizationMembership) -> dict:
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "role": membership.role,
    }


async def build_me_payload(
    db: AsyncSession,
    user: User,
    session_row: SessionRow,
) -> dict:
    """Full ``GET /api/auth/me`` response shape."""
    memberships = await list_active_memberships(db, user.id)
    organizations = [_org_summary(org, mem) for org, mem in memberships]

    active = await resolve_active_organization(
        db,
        user,
        session_row.active_organization_id,
    )
    if active is None:
        active_organization = None
    else:
        org, membership = active
        caps = sorted(capabilities_for_role(membership.role))
        active_organization = {
            **_org_summary(org, membership),
            "capabilities": caps,
        }

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_platform_admin": bool(user.is_platform_admin),
        "active_organization": active_organization,
        "organizations": organizations,
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

    active = await resolve_active_organization(
        db,
        user,
        session_row.active_organization_id,
    )
    if active is None:
        role: str | None = None
        organization_id: str | None = None
        caps: frozenset[str] = frozenset()
    else:
        org, membership = active
        role = membership.role
        organization_id = str(org.id)
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
