"""Unit tests for auth adapter selection and fail-closed production behavior."""

from __future__ import annotations

import pytest

from app.auth.adapters import DevAuthAdapter, WorkOSAuthAdapter, get_auth_adapter
from app.auth.errors import AuthMisconfiguredError
from app.config import Settings


def _settings(**overrides) -> Settings:
    """Build Settings without env file / production validators when needed."""
    base = dict(
        database_url="postgresql+asyncpg://accord@localhost/accord_test",
        migrations_database_url="",
        environment="development",
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="http://localhost:8000/api/auth/callback",
        workos_webhook_secret="",
        session_secret_key="test-session-secret-key",
        session_cookie_name="accord_session",
        dev_auth_bypass=False,
        dev_auth_email="dev@accord.local",
        dev_auth_name="Dev Test User",
        accord_allow_weak_secrets=True,
        base_url="http://localhost:5173",
        public_app_url="",
    )
    base.update(overrides)
    return Settings.model_construct(**base)


def test_dev_adapter_selected_when_bypass_enabled_in_development():
    adapter = get_auth_adapter(_settings(dev_auth_bypass=True))
    assert isinstance(adapter, DevAuthAdapter)


def test_dev_adapter_unreachable_in_production_even_if_bypass_forced():
    """Belt-and-suspenders: DevAuth must not win in production."""
    settings = _settings(
        environment="production",
        dev_auth_bypass=True,  # forced past Settings validation
        workos_client_id="client_prod",
        workos_api_key="key_prod",
        workos_redirect_uri="https://example.com/api/auth/callback",
        workos_webhook_secret="whsec",
        migrations_database_url="postgresql+asyncpg://migrator@localhost/accord",
    )
    adapter = get_auth_adapter(settings)
    assert isinstance(adapter, WorkOSAuthAdapter)
    assert not isinstance(adapter, DevAuthAdapter)


def test_production_missing_workos_raises_auth_misconfigured_not_dev():
    settings = _settings(
        environment="production",
        dev_auth_bypass=True,  # still must not fall back to Dev
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="",
    )
    with pytest.raises(AuthMisconfiguredError, match="WorkOS"):
        get_auth_adapter(settings)


@pytest.mark.asyncio
async def test_dev_adapter_exchange_returns_configured_identity():
    adapter = DevAuthAdapter(_settings(dev_auth_email="alice@accord.local", dev_auth_name="Alice"))
    identity = await adapter.exchange_code(code="anything")
    assert identity.subject_id == DevAuthAdapter.DEV_SUBJECT_ID
    assert identity.email == "alice@accord.local"
    assert identity.name == "Alice"
