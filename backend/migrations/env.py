"""Alembic async environment for Accord."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the backend package is importable when running `alembic` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

# Import the models package so SQLModel.metadata is fully populated.
import app.models  # noqa: F401

target_metadata = SQLModel.metadata


def get_database_url() -> str:
    """Prefer MIGRATIONS_DATABASE_URL; fall back to DATABASE_URL. No hardcoded DSN."""
    url = os.getenv("MIGRATIONS_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATIONS_DATABASE_URL or DATABASE_URL must be set for Alembic")
    return url


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_database_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
