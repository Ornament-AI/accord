#!/usr/bin/env python3
"""Generate the frontend product-report catalog from the backend authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_OUTPUT = ROOT / "frontend/src/lib/reports/report-catalog.generated.json"

sys.path.insert(0, str(BACKEND))

from app.reports.registry_setup import (  # noqa: E402
    PRODUCT_REPORT_SHEET_TITLES,
    PRODUCT_REPORT_SHEETS,
    build_report_registry,
)


def render_catalog() -> str:
    """Return the canonical product-sheet catalog as stable JSON."""
    registry = build_report_registry()
    catalog = []
    for report_type in PRODUCT_REPORT_SHEETS:
        if report_type not in registry:
            raise RuntimeError(f"Product report is not registered: {report_type}")
        catalog.append(
            {
                "report_type": report_type,
                "title": PRODUCT_REPORT_SHEET_TITLES[report_type],
            }
        )
    return json.dumps(catalog, indent="\t", ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the generated file is stale")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    expected = render_catalog()
    output = args.output.resolve()
    if args.check:
        try:
            actual = output.read_text(encoding="utf-8")
        except FileNotFoundError:
            actual = ""
        if actual != expected:
            print(
                f"{output} is stale; run "
                "backend/.venv/bin/python scripts/generate-report-catalog.py",
                file=sys.stderr,
            )
            return 1
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
