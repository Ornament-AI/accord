"""Migration tests run alembic via subprocess against scratch databases.

These tests deliberately avoid relying on the top-level ``conftest.py``
fixtures (which configure a shared session-scoped engine against
``accord_test``). Each test here owns its own scratch database, pointed at by
a per-test ``DATABASE_URL`` / ``MIGRATIONS_DATABASE_URL``, and shells out to
``python -m alembic``.

Rationale: alembic's own machinery loads ``backend/migrations/env.py`` which
imports ``app.models``. Running it in-process inside pytest would race the
session-scoped fixtures in the top-level conftest.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
import warnings
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CREATE_ROLES_SQL = BACKEND_ROOT / "scripts" / "create_roles.sql"

# Base URL comes from the same env knob as the top-level conftest.py; the
# migration tests derive per-test database names from it, keeping admin
# connection parameters (user, password, host, port) but swapping the database.
_BASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://darshan@127.0.0.1:5432/accord_test",
)


def _admin_url() -> str:
    """URL pointing at the default ``postgres`` admin DB so we can CREATE/DROP."""
    parsed = urlparse(_BASE_URL.replace("+asyncpg", ""))
    return parsed._replace(path="/postgres").geturl()


def _derive_scratch_url(db_name: str) -> str:
    """Replace only the database name in the base URL."""
    return urlparse(_BASE_URL)._replace(path=f"/{db_name}").geturl()


def as_psycopg_url(asyncpg_url: str) -> str:
    """Convert a ``postgresql+asyncpg://…`` URL to a vanilla ``postgresql://…`` URL."""
    parsed = urlparse(asyncpg_url)
    return parsed._replace(scheme=parsed.scheme.replace("+asyncpg", "")).geturl()


def ensure_accord_roles(*, database_url: str | None = None) -> None:
    """Idempotently create accord_* roles (cluster-wide). Required before CREATE POLICY.

    When ``database_url`` is provided, also applies schema USAGE + default
    privileges in that database (roles themselves are cluster-wide either way).
    """
    target_url = as_psycopg_url(database_url) if database_url else _admin_url()
    result = subprocess.run(
        [
            "psql",
            target_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(CREATE_ROLES_SQL),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"create_roles.sql failed\nstdout={result.stdout}\nstderr={result.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def _accord_roles_exist() -> None:
    ensure_accord_roles()


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """Provision an empty Postgres database for one test and drop it after.

    Yields a ``DATABASE_URL`` string (asyncpg flavour) suitable for passing to
    alembic via env. The DB name is unique per test. The ``accord_test_mig_``
    prefix satisfies the top-level conftest's "DB name must contain 'test'"
    safety guard.
    """
    db_name = f"accord_test_mig_{uuid.uuid4().hex[:12]}"
    admin_url = _admin_url()

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')

    try:
        yield _derive_scratch_url(db_name)
    finally:
        # Don't let cleanup raise — orphan DBs are preferable to masked failures.
        try:
            with psycopg.connect(admin_url, autocommit=True) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (db_name,),
                )
                conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        except Exception as exc:
            warnings.warn(
                f"scratch DB cleanup failed for {db_name!r}: {exc}",
                stacklevel=2,
            )


def run_alembic(
    database_url: str, *args: str, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m alembic`` with the backend as cwd and DB URLs set.

    Sets both ``DATABASE_URL`` and ``MIGRATIONS_DATABASE_URL`` so env.py's
    preferred migrator URL resolves to the scratch database.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["MIGRATIONS_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_ROOT),
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def diag(step: str, result: subprocess.CompletedProcess[str]) -> str:
    """Format a subprocess result for an assertion message."""
    return (
        f"{step} failed (exit {result.returncode})\n"
        f"---stdout---\n{result.stdout}\n"
        f"---stderr---\n{result.stderr}"
    )
