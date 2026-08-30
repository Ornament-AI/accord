"""Cross-stack contract for the backend report catalog and frontend registry."""

from __future__ import annotations

import json
from pathlib import Path

from app.reports.registry_setup import (
    PRODUCT_REPORT_SHEET_TITLES,
    PRODUCT_REPORT_SHEETS,
    build_report_registry,
)


ROOT = Path(__file__).resolve().parents[3]
GENERATED_CATALOG = ROOT / "frontend/src/lib/reports/report-catalog.generated.json"


def test_frontend_product_report_catalog_matches_backend_authority() -> None:
    """Fail when backend membership, order, or titles drift from the frontend input."""
    registry = build_report_registry()
    expected = [
        {
            "report_type": report_type,
            "title": PRODUCT_REPORT_SHEET_TITLES[report_type],
        }
        for report_type in PRODUCT_REPORT_SHEETS
    ]

    assert json.loads(GENERATED_CATALOG.read_text(encoding="utf-8")) == expected
    assert all(report_type in registry for report_type in PRODUCT_REPORT_SHEETS)
