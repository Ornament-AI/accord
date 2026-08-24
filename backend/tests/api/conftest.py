"""API package fixtures — identity table cleanup + shared auth helpers."""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.identity_helpers import (
    clear_settings_cache,
    patch_get_settings,
    settings,
)


@pytest_asyncio.fixture(autouse=True)
async def _autouse_clean_identity_tables(clean_identity_tables):
    """Keep identity tables empty between API tests (including health)."""
    yield


@pytest.fixture
def dev_settings(monkeypatch):
    value = settings(dev_auth_bypass=True)
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()


@pytest.fixture
def production_missing_workos(monkeypatch):
    value = settings(
        environment="production",
        dev_auth_bypass=False,
        workos_client_id="",
        workos_api_key="",
        workos_redirect_uri="",
        workos_webhook_secret="",
        migrations_database_url="postgresql+asyncpg://accord@localhost/accord_test",
        session_secret_key="test-session-secret-key-prod",
    )
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()
