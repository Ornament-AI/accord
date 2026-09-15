"""Identity session establishment and membership resolution (ADR 0011)."""

from __future__ import annotations

import hmac
from uuid import UUID

import structlog
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
from app.services.audit_events import entity_snapshot, write_mutation_event
from app.services.bootstrap import get_singleton_organization
from app.services.members import claim_pending_invitation
from app.tenancy import bind_tenant_context

logger = structlog.get_logger()


async def upsert_user(
    db: AsyncSession,
    identity: AuthenticatedIdentity,
    *,
    organization_id: UUID | None = None,
) -> User:
    """Create or update a local user keyed by WorkOS subject id.

    Audit: only real state transitions emit events — a first-seen identity
    (``user.create``) or an IdP-driven email/name change (``user.update``).
    Routine logins whose claims match the stored row write no audit noise.
    ``organization_id`` may be None pre-bootstrap; without a tenant the
    tenant-scoped audit row cannot be written, so creation is silent.
    """
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
        if organization_id is not None:
            await write_mutation_event(
                db,
                organization_id=organization_id,
                actor_user_id=user.id,
                command="user.create",
                entity_type="user",
                entity_id=user.id,
                entity_label=f"{user.name} <{user.email}>",
                before_state={},
                after_state=entity_snapshot(user),
                summary={"email": user.email, "workos_user_id": user.workos_user_id},
            )
        return user

    changed_fields: list[str] = []
    before_state = entity_snapshot(user)
    if user.email != email:
        user.email = email
        changed_fields.append("email")
    if user.name != name:
        user.name = name
        changed_fields.append("name")
    if changed_fields:
        user.updated_at = utcnow()
        await db.flush()
        if organization_id is not None:
            await write_mutation_event(
                db,
                organization_id=organization_id,
                actor_user_id=user.id,
                command="user.update",
                entity_type="user",
                entity_id=user.id,
                entity_label=f"{user.name} <{user.email}>",
                before_state=before_state,
                after_state=entity_snapshot(user),
                summary={"updated_fields": changed_fields},
            )
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
    membership = await get_active_membership_for_org(db, organization_id=org.id, user_id=user_id)
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
    org = await get_singleton_organization(db)
    if org is not None:
        # audit_events RLS (accord_app) requires app.organization_id on INSERT;
        # the login path runs without a pre-bound tenant context.
        await bind_tenant_context(db, organization_id=org.id)
    user = await upsert_user(
        db,
        identity,
        organization_id=org.id if org is not None else None,
    )
    if org is not None:
        await bind_tenant_context(db, organization_id=org.id, user_id=user.id)
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


async def session_matches_user_agent(
    db: AsyncSession,
    session_row,
    user_agent_hash: str | None,
) -> bool:
    """Enforce the session's User-Agent binding (backfill or compare).

    Mismatch rejects (a stolen cookie replayed from a different client) but
    does not revoke — a browser auto-update should not nuke the session.
    ``None`` stored hash backfills on read so pre-existing sessions bind now
    instead of logging everyone out at deploy time.
    """
    stored_ua_hash = session_row.user_agent_hash
    if stored_ua_hash is None:
        if user_agent_hash is not None:
            session_row.user_agent_hash = user_agent_hash
            await db.flush()
            await db.commit()
        return True
    if not hmac.compare_digest(stored_ua_hash, user_agent_hash or ""):
        logger.warning(
            "session_user_agent_mismatch",
            session_id=str(session_row.id),
            user_id=str(session_row.user_id),
        )
        return False
    return True


async def resolve_principal(
    db: AsyncSession,
    settings: Settings,
    cookie_value: str,
    *,
    user_agent_hash: str | None = None,
) -> AuthPrincipal | None:
    """Read session store → load user → resolve active org/role/capabilities."""
    try:
        store = DatabaseSessionStore(settings, db)
    except WeakSessionSecretError:
        return None
    session_row = await store.read_session(cookie_value)
    if session_row is None:
        return None

    if not await session_matches_user_agent(db, session_row, user_agent_hash):
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
