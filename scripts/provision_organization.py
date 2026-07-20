#!/usr/bin/env python3
"""Privileged idempotent singleton organization bootstrap (ADR 0011).

Uses MIGRATIONS_DATABASE_URL (or DATABASE_URL) — migrator/ops DB credential is
the trust boundary. Not an HTTP API.

Usage:
  backend/.venv/bin/python scripts/provision_organization.py \\
    --name "MSIDC" --slug msidc --admin-email admin@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.exceptions import AccordError  # noqa: E402
from app.services.bootstrap import provision_organization  # noqa: E402


async def _run(name: str, slug: str, admin_email: str) -> int:
    settings = get_settings()
    database_url = settings.migrations_database_url or settings.database_url
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await provision_organization(
                session,
                name=name,
                slug=slug,
                admin_email=admin_email,
            )
        action = "created" if result.created else "unchanged (idempotent)"
        print(
            f"Organization {action}: {result.organization.name} "
            f"({result.organization.slug}) id={result.organization.id}"
        )
        return 0
    except AccordError as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Organization display name")
    parser.add_argument("--slug", required=True, help="Lowercase kebab-case slug")
    parser.add_argument(
        "--admin-email",
        required=True,
        help="Administrator email (membership if user exists, else invitation)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.name, args.slug, args.admin_email)))


if __name__ == "__main__":
    main()
