"""Unit tests for auth adapter selection and fail-closed production behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from workos import AuthenticationError, AuthorizationError

from app.auth.adapters import DevAuthAdapter, WorkOSAuthAdapter, get_auth_adapter
from app.auth.errors import (
    AuthChallengeRequiredError,
    AuthMisconfiguredError,
    InvalidAuthenticationError,
)
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


def _headless_adapter() -> WorkOSAuthAdapter:
    adapter = WorkOSAuthAdapter.__new__(WorkOSAuthAdapter)
    adapter._redirect_uri = "http://test/api/auth/callback"
    adapter._client = MagicMock()
    return adapter


@pytest.mark.asyncio
async def test_workos_password_auth_returns_identity_and_discards_tokens():
    adapter = _headless_adapter()
    adapter._client.user_management.authenticate_with_password.return_value = SimpleNamespace(
        user=SimpleNamespace(
            id="user_password",
            email="person@example.com",
            name=None,
            first_name="Person",
            last_name="Example",
        ),
        access_token="must-not-escape",
        refresh_token="must-not-escape",
    )

    identity = await adapter.authenticate_with_password(
        email="person@example.com",
        password="secret",
        ip_address="203.0.113.10",
        user_agent="test-agent",
    )

    assert identity.subject_id == "user_password"
    assert identity.email == "person@example.com"
    assert identity.name == "Person Example"
    assert not hasattr(identity, "access_token")


@pytest.mark.asyncio
async def test_workos_password_auth_maps_provider_rejection_to_generic_401():
    adapter = _headless_adapter()
    adapter._client.user_management.authenticate_with_password.side_effect = AuthenticationError(
        "provider detail that must not escape"
    )

    with pytest.raises(InvalidAuthenticationError, match="Invalid email or password"):
        await adapter.authenticate_with_password(
            email="person@example.com",
            password="wrong",
            ip_address=None,
            user_agent=None,
        )


@pytest.mark.asyncio
async def test_workos_password_auth_preserves_hosted_challenge_fallback():
    adapter = _headless_adapter()
    adapter._client.user_management.authenticate_with_password.side_effect = AuthorizationError(
        "mfa_challenge"
    )

    with pytest.raises(AuthChallengeRequiredError, match="Additional verification"):
        await adapter.authenticate_with_password(
            email="person@example.com",
            password="secret",
            ip_address=None,
            user_agent=None,
        )


@pytest.mark.asyncio
async def test_workos_magic_code_uses_headless_sdk_methods():
    adapter = _headless_adapter()
    adapter._client.user_management.authenticate_with_magic_auth.return_value = SimpleNamespace(
        user=SimpleNamespace(
            id="user_magic",
            email="person@example.com",
            name="Person",
            first_name=None,
            last_name=None,
        )
    )

    await adapter.send_magic_code(
        email="person@example.com",
        ip_address=None,
        user_agent="test-agent",
    )
    identity = await adapter.authenticate_with_magic_code(
        email="person@example.com",
        code="123456",
        ip_address=None,
        user_agent="test-agent",
    )

    adapter._client.user_management.create_magic_auth.assert_called_once()
    adapter._client.user_management.authenticate_with_magic_auth.assert_called_once()
    assert identity.subject_id == "user_magic"
