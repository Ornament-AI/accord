"""Auth package fixtures — identity table cleanup + shared helpers."""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.identity_helpers import (  # noqa: F401
    _session_cookie_from_response,
    _settings,
    clear_settings_cache,
    login_dev,
    patch_get_settings,
    session_cookie_from_response,
    settings,
)


@pytest_asyncio.fixture(autouse=True)
async def _autouse_clean_identity_tables(clean_identity_tables):
    yield


@pytest.fixture
def dev_settings(monkeypatch):
    value = settings(dev_auth_bypass=True)
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()
