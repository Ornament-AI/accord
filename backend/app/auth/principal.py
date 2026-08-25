"""AuthPrincipal — immutable identity object attached to authenticated requests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """Immutable snapshot of the authenticated user for the current request.

    Stored on ``request.state.user`` once session + membership resolution
    completes. ``subject_id`` is the stable external identity key (WorkOS user
    id). ``user_id`` is the local ``users.id`` UUID string.
    """

    user_id: str
    subject_id: str
    email: str
    role: str | None
    is_active: bool
    display_name: str | None = None
    organization_id: str | None = None
    is_platform_admin: bool = False
    capabilities: frozenset[str] = frozenset()
    session_id: str | None = None
