"""AuthPrincipal — immutable identity object attached to authenticated requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.auth.capabilities import capabilities_for_role


class PrincipalResolver(Protocol):
    """Seam for resolving an authenticated principal (WorkOS / DevTest)."""

    async def resolve(self) -> AuthPrincipal | None: ...


@dataclass(frozen=True, slots=True)
class OrganizationSummary:
    """Membership row summary for /me-style payloads."""

    id: str
    name: str
    slug: str
    role: str


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

    @classmethod
    def dev_test(
        cls,
        *,
        email: str = "dev@accord.local",
        role: str = "organization_administrator",
    ) -> AuthPrincipal:
        """Build a deterministic principal for DEV_AUTH_BYPASS / unit helpers."""
        return cls(
            user_id="00000000-0000-4000-8000-000000000001",
            subject_id="dev-test-subject",
            email=email,
            role=role,
            is_active=True,
            display_name="Dev Test User",
            organization_id=None,
            is_platform_admin=False,
            capabilities=capabilities_for_role(role),
            session_id=None,
        )

    @property
    def is_admin(self) -> bool:
        # Keep platform_support_administrator for existing middleware/unit tests.
        # is_platform_admin is display-only this phase (no capability bypass).
        return self.role in {
            "organization_administrator",
            "platform_support_administrator",
        }
