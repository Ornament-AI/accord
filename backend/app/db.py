"""Async database engine and session management.

Module-level singleton pattern. Tests override via configure_engine(url).
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _asyncpg_connect_args(database_url: str, statement_timeout_ms: int) -> dict | None:
    """Return asyncpg server settings for bounded query execution.

    A zero statement timeout keeps PostgreSQL's default behavior. The helper is
    deliberately scoped to asyncpg URLs so SQLite or sync test URLs are not given
    driver-specific arguments.
    """
    if statement_timeout_ms <= 0:
        return None
    if make_url(database_url).drivername != "postgresql+asyncpg":
        return None
    return {
        "server_settings": {
            "application_name": "accord-api",
            "statement_timeout": str(statement_timeout_ms),
        }
    }


def configure_engine(database_url: str | None = None) -> AsyncEngine:
    """Create and register the global async engine.

    Called without arguments, reads DATABASE_URL from settings.
    Tests pass a custom URL to bypass the lru_cache singleton.
    """
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    settings = get_settings()
    if database_url is None:
        database_url = settings.database_url

    connect_args = _asyncpg_connect_args(database_url, settings.db_statement_timeout_ms)
    engine_kwargs: dict = {
        "future": True,
        "echo": False,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "pool_pre_ping": True,
        "pool_use_lifo": True,
    }
    if connect_args is not None:
        engine_kwargs["connect_args"] = connect_args

    # Tests: disable pooling for clean per-test isolation.
    test_url = os.getenv("TEST_DATABASE_URL")
    if test_url and test_url == database_url:
        engine_kwargs = {"future": True, "echo": False, "poolclass": NullPool}
        if connect_args is not None:
            engine_kwargs["connect_args"] = connect_args

    _engine = create_async_engine(database_url, **engine_kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        return configure_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        configure_engine()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_context() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def repeatable_read_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only PostgreSQL session with one stable transaction snapshot."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    engine = _engine
    _engine = None
    _session_factory = None
    if engine is not None:
        await engine.dispose()
