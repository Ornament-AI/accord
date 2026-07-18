"""AuthPrincipal — immutable identity object attached to authenticated requests.

WorkOS session resolution is wired by a later auth lane. This module keeps the
Principal shape and a DevTest factory used when DEV_AUTH_BYPASS is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PrincipalResolver(Protocol):
    """Seam for resolving an authenticated principal (WorkOS / DevTest)."""

    async def resolve(self) -> AuthPrincipal | None: ...


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """Immutable snapshot of the authenticated user for the current request.

    Stored on ``request.state.user`` once an auth provider (WorkOS or DevTest)
    resolves identity. ``subject_id`` is the stable external identity key
    (WorkOS user id in production).
    """

    user_id: str
    subject_id: str
    email: str
    role: str
    is_active: bool
    display_name: str | None = None
    organization_id: str | None = None

    @classmethod
    def dev_test(
        cls,
        *,
        email: str = "dev@accord.local",
        role: str = "organization_administrator",
    ) -> AuthPrincipal:
        """Build a deterministic principal for DEV_AUTH_BYPASS."""
        return cls(
            user_id="00000000-0000-4000-8000-000000000001",
            subject_id="dev-test-subject",
            email=email,
            role=role,
            is_active=True,
            display_name="Dev Test User",
            organization_id=None,
        )

    @property
    def is_admin(self) -> bool:
        return self.role in {"organization_administrator", "platform_support_administrator"}
