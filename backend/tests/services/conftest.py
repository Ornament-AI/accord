"""Services package fixtures — identity table cleanup + shared helpers."""

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
    yield


@pytest.fixture
def dev_settings(monkeypatch):
    value = settings(dev_auth_bypass=True)
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()
