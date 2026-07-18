"""FastAPI dependency injection for auth and database sessions.

WorkOS session resolution is a later-lane concern. This module keeps the
Principal-facing dependencies and a DEV_AUTH_BYPASS seam that returns a
DevTest principal without contacting an identity provider.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import AuthPrincipal
from app.auth.session import resolve_principal_from_session
from app.config import get_settings
from app.db import get_session

Session = Annotated[AsyncSession, Depends(get_session)]


async def _resolve_current_user(request: Request) -> AuthPrincipal | None:
    principal: AuthPrincipal | None = getattr(request.state, "user", None)
    if principal is not None:
        return principal
    principal = await resolve_principal_from_session(request)
    if principal is not None:
        request.state.user = principal
        return principal
    settings = get_settings()
    # Belt-and-suspenders: DevTest bypass is structurally unreachable in production
    # (Settings also rejects DEV_AUTH_BYPASS=true at load time).
    if settings.dev_auth_bypass and not settings.is_production:
        principal = AuthPrincipal.dev_test()
        request.state.user = principal
        return principal
    return None


async def get_current_user(request: Request) -> AuthPrincipal:
    """Return the authenticated AuthPrincipal or raise 401."""
    principal = await _resolve_current_user(request)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return principal


async def get_current_user_optional(request: Request) -> AuthPrincipal | None:
    """Return the AuthPrincipal from request state, or None."""
    return await _resolve_current_user(request)


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


# Convenience type aliases
CurrentUser = Annotated[AuthPrincipal, Depends(get_current_user)]
OptionalUser = Annotated[AuthPrincipal | None, Depends(get_current_user_optional)]
