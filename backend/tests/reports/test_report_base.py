"""Tests for report DTO JSON preview and closed ReportRegistry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.reports.base import (
    ColumnKind,
    ReportBuilder,
    ReportColumn,
    ReportContext,
    ReportDTO,
    ReportRegistry,
    TableSection,
    to_json,
)


def _sample_dto() -> ReportDTO:
    return ReportDTO(
        report_type="pay_bill",
        template_version="v1",
        title="Payroll Register — Pay Bill",
        organization_name="Accord Demo Org",
        subtitle="June 2026",
        sections=(
            TableSection(
                title="Register",
                columns=(
                    ReportColumn(key="employee", header="Employee", kind=ColumnKind.TEXT),
                    ReportColumn(key="gross", header="Gross", kind=ColumnKind.MONEY),
                ),
                rows=(("Ada Lovelace", Decimal("5102985.00")),),
                totals=(None, Decimal("5102985.00")),
            ),
        ),
    )


class _StubBuilder:
    async def build(self, session: Any, ctx: ReportContext) -> ReportDTO:
        return _sample_dto()


def test_to_json_decimal_money_as_string() -> None:
    payload = to_json(_sample_dto())
    assert payload["sections"][0]["rows"][0]["gross"] == "5102985.00"
    assert payload["sections"][0]["totals"]["gross"] == "5102985.00"


def test_to_json_stable_key_ordering() -> None:
    payload = to_json(_sample_dto())
    first = json.dumps(payload, separators=(",", ":"))
    second = json.dumps(payload, separators=(",", ":"))
    assert first == second
    # Re-serialize a freshly built DTO must match (deterministic key insertion).
    assert json.dumps(to_json(_sample_dto()), separators=(",", ":")) == first


def test_registry_register_and_lookup() -> None:
    registry = ReportRegistry()
    builder: ReportBuilder = _StubBuilder()
    registry.register(
        "pay_bill",
        builder=builder,
        to_json=to_json,
        to_excel=lambda dto: b"xlsx",
        to_pdf=lambda dto: b"%PDF",
        content_types={
            "json": "application/json",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
        },
        filename_pattern="{report_type}_{posted_run_id}.{ext}",
    )
    entry = registry.get("pay_bill")
    assert entry.report_type == "pay_bill"
    assert entry.builder is builder
    assert "pay_bill" in registry


def test_registry_duplicate_registration_raises() -> None:
    registry = ReportRegistry()
    kwargs = dict(
        builder=_StubBuilder(),
        to_json=to_json,
        to_excel=lambda dto: b"xlsx",
        to_pdf=lambda dto: b"%PDF",
        content_types={"pdf": "application/pdf"},
        filename_pattern="{report_type}.pdf",
    )
    registry.register("pay_bill", **kwargs)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("pay_bill", **kwargs)


def test_registry_unknown_report_type_raises() -> None:
    registry = ReportRegistry()
    with pytest.raises(KeyError, match="unknown report_type"):
        registry.get("missing_report")


def test_report_context_frozen_fields() -> None:
    ctx = ReportContext(
        organization_id=uuid4(),
        posted_run_id=uuid4(),
        template_version="v1",
        generated_at=datetime.now(UTC),
        engine_version="0.1.0",
    )
    with pytest.raises(AttributeError):
        ctx.template_version = "v2"  # type: ignore[misc]
