#!/usr/bin/env python3
"""Provision a membership or invitation for the singleton organization (ADR 0011).

Uses MIGRATIONS_DATABASE_URL (or DATABASE_URL). Enforces last-administrator
invariants via the shared members service.

Usage:
  backend/.venv/bin/python scripts/provision_member.py \\
    --email user@example.com --role payroll_preparer
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
from app.services.members import provision_member, require_singleton_org_id  # noqa: E402


async def _run(email: str, role: str) -> int:
    settings = get_settings()
    database_url = settings.migrations_database_url or settings.database_url
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            org_id = await require_singleton_org_id(session)
            kind, row_id = await provision_member(
                session,
                organization_id=org_id,
                email=email,
                role=role,
            )
            await session.commit()
        print(f"{kind} provisioned: id={row_id} email={email} role={role}")
        return 0
    except AccordError as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.email, args.role)))


if __name__ == "__main__":
    main()
