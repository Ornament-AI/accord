#!/usr/bin/env python3
"""Export Accord FastAPI OpenAPI schema without starting the server."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DEFAULT_OUTPUT = ROOT / "tmp" / "openapi-spec.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Accord OpenAPI JSON.")
    parser.add_argument(
        "output",
        nargs="?",
        default=str(DEFAULT_OUTPUT),
        help=f"Output JSON path. Defaults to {DEFAULT_OUTPUT}.",
    )
    return parser.parse_args()


def configure_export_env() -> None:
    os.environ["ENVIRONMENT"] = "development"
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://accord@127.0.0.1:5432/accord",
    )
    os.environ.setdefault("DEV_AUTH_BYPASS", "false")
    os.environ.setdefault("SESSION_SECRET_KEY", "openapi-export-dev-secret")


def main() -> int:
    args = parse_args()
    configure_export_env()
    sys.path.insert(0, str(BACKEND))

    from app.main import app

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
