"""Full ROLE_CAPABILITIES × CAPABILITIES enforcement matrix via require_capability."""

from __future__ import annotations

import itertools
from uuid import uuid4

import pytest

from app.api.deps import require_capability
from app.auth.capabilities import CAPABILITIES, ROLE_CAPABILITIES, capabilities_for_role
from app.auth.errors import CapabilityDeniedError
from app.auth.principal import AuthPrincipal

_ROLES = tuple(ROLE_CAPABILITIES.keys())
_CAPS = tuple(sorted(CAPABILITIES))


def _principal(*, role: str, capabilities: frozenset[str]) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=str(uuid4()),
        subject_id="gate-d-matrix",
        email="matrix@gate-d.test",
        role=role,
        is_active=True,
        organization_id=str(uuid4()),
        capabilities=capabilities,
        session_id=str(uuid4()),
    )


@pytest.mark.parametrize(
    ("role", "capability"),
    list(itertools.product(_ROLES, _CAPS)),
    ids=[f"{role}::{cap}" for role, cap in itertools.product(_ROLES, _CAPS)],
)
@pytest.mark.asyncio
async def test_require_capability_matches_role_matrix(role: str, capability: str):
    allowed = capabilities_for_role(role)
    principal = _principal(role=role, capabilities=allowed)
    dep = require_capability(capability)

    if capability in allowed:
        result = await dep(principal)
        assert result is principal
    else:
        with pytest.raises(CapabilityDeniedError) as exc:
            await dep(principal)
        assert exc.value.status_code == 403
        assert exc.value.error == f"urn:accord:capability:{capability}"
