"""Test fixtures for Accord backend infrastructure."""

import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Override env before any app imports — use TEST_DATABASE_URL or default to accord_test
_test_db_url = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://darshan@127.0.0.1:5432/accord_test",
)

# Safety guard: refuse to run against a database that doesn't look like a test DB
_db_name = _test_db_url.rsplit("/", 1)[-1].split("?")[0]
if "test" not in _db_name.lower():
    raise RuntimeError(
        f"Refusing to run tests against database '{_db_name}' — "
        "name must contain 'test'. Set TEST_DATABASE_URL to a test database."
    )

os.environ["DATABASE_URL"] = _test_db_url
os.environ["TEST_DATABASE_URL"] = _test_db_url
os.environ["ACCORD_ALLOW_WEAK_SECRETS"] = "1"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEV_AUTH_BYPASS"] = "false"
os.environ.setdefault("SESSION_SECRET_KEY", "test-session-secret-key")
os.environ.setdefault("MIGRATIONS_DATABASE_URL", _test_db_url)

from app.db import configure_engine, dispose_engine, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware.rate_limit import limiter  # noqa: E402

# Force NullPool for tests
configure_engine(os.environ["DATABASE_URL"])

# Infrastructure skeleton has no domain schema to create; mark auth ready for
# readiness checks when lifespan has not yet run for a given client.
app.state.auth_ready = True


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _engine_lifecycle():
    """Ensure the async engine is configured for the session, then dispose."""
    configure_engine()
    yield
    await dispose_engine()


@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limits():
    limiter.reset()


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
