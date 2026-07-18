"""Direct tests for require_capability / OrganizationContextRequired."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.deps import require_capability
from app.auth.errors import CapabilityDeniedError, OrganizationContextRequiredError
from app.auth.principal import AuthPrincipal


def _principal(**overrides) -> AuthPrincipal:
    base = dict(
        user_id=str(uuid4()),
        subject_id="subj",
        email="u@example.com",
        role="payroll_preparer",
        is_active=True,
        organization_id=str(uuid4()),
        capabilities=frozenset({"create_run"}),
        session_id=str(uuid4()),
    )
    base.update(overrides)
    return AuthPrincipal(**base)


@pytest.mark.asyncio
async def test_require_capability_409_without_active_org():
    dep = require_capability("manage_organization")
    principal = _principal(organization_id=None, capabilities=frozenset())
    with pytest.raises(OrganizationContextRequiredError) as exc:
        await dep(principal)
    assert exc.value.error == "OrganizationContextRequired"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_require_capability_403_missing_capability():
    dep = require_capability("manage_organization")
    principal = _principal(
        organization_id=str(uuid4()),
        capabilities=frozenset({"create_run"}),
    )
    with pytest.raises(CapabilityDeniedError) as exc:
        await dep(principal)
    assert exc.value.error == "urn:accord:capability:manage_organization"
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_capability_passes_when_present():
    dep = require_capability("manage_organization")
    principal = _principal(
        organization_id=str(uuid4()),
        capabilities=frozenset({"manage_organization", "view_audit"}),
    )
    result = await dep(principal)
    assert result is principal
