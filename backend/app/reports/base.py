"""Shared report infrastructure: context, DTO, builder/formatter protocols, registry.

Core contract (docs/report-specs/report-catalog.md): a builder accepts
``(organization_id, posted_run_id, template_version)`` (via :class:`ReportContext`)
and emits exactly one typed :class:`ReportDTO`. JSON preview, Excel, and PDF
formatters all consume that same DTO — no per-format data fetching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import UUID

CellValue = Decimal | str | int | date | datetime | None


class ColumnKind(StrEnum):
    """Semantic column kinds used by tabular formatters."""

    TEXT = "text"
    MONEY = "money"
    COUNT = "count"
    DATE = "date"


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Identity and generation metadata passed into every report builder."""

    organization_id: UUID
    posted_run_id: UUID
    template_version: str
    generated_at: datetime
    engine_version: str


@dataclass(frozen=True, slots=True)
class ReportColumn:
    """One column in a tabular section."""

    key: str
    header: str
    kind: ColumnKind = ColumnKind.TEXT


@dataclass(frozen=True, slots=True)
class TableSection:
    """A register-style table or schedule-style listing within a report.

    Rows are positional tuples aligned with ``columns``. Optional ``totals``
    is a positional tuple of the same width (``None`` cells where no total).
    """

    title: str
    columns: tuple[ReportColumn, ...]
    rows: tuple[tuple[CellValue, ...], ...]
    totals: tuple[CellValue, ...] | None = None


@dataclass(frozen=True, slots=True)
class ReportDTO:
    """Immutable presentation DTO shared by JSON, Excel, and PDF formatters.

    Money values in cells must be :class:`~decimal.Decimal` (never ``float``;
    ADR 0006). Formatters may rearrange layout but must not re-query live data.
    """

    report_type: str
    template_version: str
    title: str
    organization_name: str
    subtitle: str
    sections: tuple[TableSection, ...]


@runtime_checkable
class ReportBuilder(Protocol):
    """Builds exactly one typed DTO from posted-run snapshot data."""

    async def build(self, session: Any, ctx: ReportContext) -> ReportDTO:
        """Load snapshot data for ``ctx`` and return a frozen :class:`ReportDTO`."""


@runtime_checkable
class JsonFormatter(Protocol):
    def __call__(self, dto: ReportDTO) -> dict[str, Any]:
        """Serialize ``dto`` to a JSON-ready dict (preview)."""


@runtime_checkable
class ExcelFormatter(Protocol):
    def __call__(self, dto: ReportDTO) -> bytes:
        """Render ``dto`` to ``.xlsx`` bytes."""


@runtime_checkable
class PdfFormatter(Protocol):
    def __call__(self, dto: ReportDTO) -> bytes:
        """Render ``dto`` to PDF bytes."""


def _serialize_cell(value: CellValue) -> Any:
    if isinstance(value, Decimal):
        quantized = value.quantize(Decimal("0.01"))
        return format(quantized, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def to_json(dto: ReportDTO) -> dict[str, Any]:
    """Stable-key-order JSON preview of a report DTO.

    Decimals are serialized as fixed-scale strings (e.g. ``\"5102985.00\"``).
    Key insertion order is deterministic so ``json.dumps`` is stable.
    """
    sections: list[dict[str, Any]] = []
    for section in dto.sections:
        columns = [
            {"key": col.key, "header": col.header, "kind": str(col.kind)} for col in section.columns
        ]
        rows: list[dict[str, Any]] = []
        for row in section.rows:
            row_obj: dict[str, Any] = {}
            for col, cell in zip(section.columns, row, strict=True):
                row_obj[col.key] = _serialize_cell(cell)
            rows.append(row_obj)
        section_obj: dict[str, Any] = {
            "title": section.title,
            "columns": columns,
            "rows": rows,
        }
        if section.totals is not None:
            totals_obj: dict[str, Any] = {}
            for col, cell in zip(section.columns, section.totals, strict=True):
                totals_obj[col.key] = _serialize_cell(cell)
            section_obj["totals"] = totals_obj
        sections.append(section_obj)

    return {
        "report_type": dto.report_type,
        "template_version": dto.template_version,
        "title": dto.title,
        "organization_name": dto.organization_name,
        "subtitle": dto.subtitle,
        "sections": sections,
    }


@dataclass(frozen=True, slots=True)
class ReportFormatters:
    """Formatters and artifact metadata for one registered report type."""

    to_json: JsonFormatter
    to_excel: ExcelFormatter
    to_pdf: PdfFormatter
    content_types: Mapping[str, str]
    filename_pattern: str


@dataclass(frozen=True, slots=True)
class ReportRegistration:
    """Closed registration entry: builder + formatters for one report type."""

    report_type: str
    builder: ReportBuilder
    formatters: ReportFormatters


class ReportRegistry:
    """Closed map of ``report_type`` → builder + formatters.

    Registration is explicit via :meth:`register`. Duplicate ``report_type``
    values raise; unknown lookups raise a clear error.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ReportRegistration] = {}

    def register(
        self,
        report_type: str,
        *,
        builder: ReportBuilder,
        to_json: JsonFormatter,
        to_excel: ExcelFormatter,
        to_pdf: PdfFormatter,
        content_types: Mapping[str, str],
        filename_pattern: str,
    ) -> None:
        if report_type in self._entries:
            raise ValueError(f"report_type already registered: {report_type!r}")
        self._entries[report_type] = ReportRegistration(
            report_type=report_type,
            builder=builder,
            formatters=ReportFormatters(
                to_json=to_json,
                to_excel=to_excel,
                to_pdf=to_pdf,
                content_types=dict(content_types),
                filename_pattern=filename_pattern,
            ),
        )

    def get(self, report_type: str) -> ReportRegistration:
        try:
            return self._entries[report_type]
        except KeyError as exc:
            raise KeyError(f"unknown report_type: {report_type!r}") from exc

    def __contains__(self, report_type: object) -> bool:
        return isinstance(report_type, str) and report_type in self._entries
