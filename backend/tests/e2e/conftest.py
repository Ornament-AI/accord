"""E2E fixtures for production HTTP routes and identity cleanup."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.identity_helpers import (  # noqa: F401
    clear_settings_cache,
    patch_get_settings,
    settings,
)


def pytest_configure(config: pytest.Config) -> None:
    """Register ``e2e`` without editing read-only pyproject/pytest.ini."""
    config.addinivalue_line(
        "markers",
        "e2e: full-stack HTTP end-to-end proofs (serial; shared accord_test DB)",
    )


@pytest_asyncio.fixture(autouse=True)
async def _autouse_clean_identity_tables(clean_identity_tables):
    """Keep identity tables empty between E2E tests (CASCADE clears org data)."""
    yield


@pytest.fixture
def dev_settings(monkeypatch):
    value = settings(dev_auth_bypass=True)
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()


def _e2e_app():
    """Build the app with its production route set."""
    application = create_app()
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _e2e_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
