"""FastAPI dependency injection for auth, capabilities, and tenant context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import (
    CapabilityDeniedError,
    MembershipForbiddenError,
    OrganizationContextRequiredError,
    WeakSessionSecretError,
)
from app.auth.principal import AuthPrincipal
from app.config import get_settings
from app.db import get_session
from app.models.identity import User
from app.services.identity import resolve_active_organization, resolve_principal
from app.tenancy import bind_tenant_context

Session = Annotated[AsyncSession, Depends(get_session)]


async def _resolve_current_user(
    request: Request,
    db: Session,
) -> AuthPrincipal | None:
    principal: AuthPrincipal | None = getattr(request.state, "user", None)
    if principal is not None:
        return principal

    settings = get_settings()
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        # No silent AuthPrincipal.dev_test() fallback — login establishes real DB sessions.
        return None

    try:
        principal = await resolve_principal(db, settings, cookie_value)
    except WeakSessionSecretError:
        return None
    if principal is not None:
        request.state.user = principal
    return principal


async def get_current_user(request: Request, db: Session) -> AuthPrincipal:
    """Return the authenticated AuthPrincipal or raise 401."""
    principal = await _resolve_current_user(request, db)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return principal


async def get_current_user_optional(request: Request, db: Session) -> AuthPrincipal | None:
    """Return the AuthPrincipal from cookie/DB resolution, or None."""
    return await _resolve_current_user(request, db)


def require_admin(
    principal: Annotated[AuthPrincipal, Depends(get_current_user)],
) -> AuthPrincipal:
    """Raise 403 unless the current user is an admin-capable role."""
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return principal


def require_capability(capability: str):
    """Dependency factory: require active org + capability on the principal."""

    async def _dep(
        principal: Annotated[AuthPrincipal, Depends(get_current_user)],
    ) -> AuthPrincipal:
        if principal.organization_id is None:
            raise OrganizationContextRequiredError("An active organization context is required.")
        if capability not in principal.capabilities:
            raise CapabilityDeniedError(capability)
        return principal

    return _dep


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: str
    user_id: str
    request_id: str | None


async def require_tenant_context(
    request: Request,
    principal: Annotated[AuthPrincipal, Depends(get_current_user)],
    db: Session,
) -> TenantContext:
    """Require active org, re-validate membership, bind RLS GUCs."""
    if not principal.organization_id:
        raise OrganizationContextRequiredError("An active organization context is required.")

    user = await db.get(User, UUID(principal.user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Bind first so membership re-validation can see the row under forced RLS.
    if not db.in_transaction():
        await db.begin()

    request_id = getattr(request.state, "request_id", None)
    await bind_tenant_context(
        db,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        request_id=request_id,
    )

    active = await resolve_active_organization(
        db,
        user,
        UUID(principal.organization_id),
    )
    if active is None:
        raise MembershipForbiddenError("Active organization membership is no longer valid.")

    return TenantContext(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        request_id=request_id,
    )


# Convenience type aliases
CurrentUser = Annotated[AuthPrincipal, Depends(get_current_user)]
OptionalUser = Annotated[AuthPrincipal | None, Depends(get_current_user_optional)]
TenantCtx = Annotated[TenantContext, Depends(require_tenant_context)]
