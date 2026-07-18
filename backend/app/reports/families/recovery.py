"""Recovery and accommodation report family.

Builders read posted run snapshots only and emit :class:`~app.reports.base.ReportDTO`
values. Formatters are thin wrappers over the generic JSON / Excel / PDF writers.

Key invariants (docs/report-specs/report-catalog.md):

- HBA schedule total equals posted ``HBA_INSTALLMENT`` external recoveries.
- Generic advance schedule is parameterized by ``advance_type`` (infrastructure
  for festival / motor-car / etc.). When ``advance_type='hba'`` the row set and
  money total match the HBA schedule.
- Accommodation schedules keep **actual** license-fee recovery totals in a
  separate DTO field/column from **informational** foregone HRA; the two must
  never be summed into one recovery total.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.effective import select_active_version
from app.models.employees import employee_profile_versions
from app.models.identity import Organization
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.reports.base import (
    ColumnKind,
    ReportColumn,
    ReportContext,
    ReportDTO,
    ReportRegistry,
    TableSection,
    to_json as base_to_json,
)
from app.reports.excel import to_excel as base_to_excel
from app.reports.pdf import to_pdf as base_to_pdf

REPORT_TYPE_HBA_SCHEDULE = "hba_schedule"
REPORT_TYPE_ADVANCE_SCHEDULE = "advance_schedule"
REPORT_TYPE_ACCOMMODATION_MUMBAI = "accommodation_mumbai_schedule"
REPORT_TYPE_ACCOMMODATION_WORLI = "accommodation_worli_schedule"

HbaScheduleDTO = ReportDTO
AdvanceScheduleDTO = ReportDTO
AccommodationScheduleDTO = ReportDTO

AccommodationLocation = Literal["mumbai", "worli"]

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")

_LICENSE_FEE_COMPONENT = "ACCOMMODATION_LICENSE_FEE"
_FOREGONE_HRA_COMPONENT = "FOREGONE_HRA"

_ADVANCE_COMPONENT_BY_TYPE: dict[str, str] = {
    "hba": "HBA_INSTALLMENT",
    "gpf_advance": "GPF_ADVANCE_INSTALLMENT",
    "festival": "FESTIVAL_ADVANCE_INSTALLMENT",
    "motor_car": "MOTOR_CAR_ADVANCE_INSTALLMENT",
    "motorcycle": "MOTORCYCLE_ADVANCE_INSTALLMENT",
    "other": "OTHER_ADVANCE_INSTALLMENT",
}

DEFAULT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
FILENAME_PATTERN = "{report_type}_{posted_run_id}.{ext}"

# Column header must explicitly label foregone HRA as informational.
_FOREGONE_HRA_HEADER = "Informational foregone HRA (not recovered)"


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _period_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


async def _require_posted_run(
    session: AsyncSession,
    ctx: ReportContext,
) -> tuple[PayrollRun, Any, PayrollPeriod, Organization]:
    run = await session.get(PayrollRun, ctx.posted_run_id)
    if run is None or run.organization_id != ctx.organization_id:
        raise NotFoundError("Payroll run not found.")
    if run.status != "posted":
        raise ConflictError(
            f"Payroll run must be posted to generate reports; found {run.status!r}.",
            details={"run_id": str(run.id), "status": run.status},
        )
    if run.current_version_id is None:
        raise ConflictError("Posted payroll run has no current_version_id.")

    version = (
        (
            await session.execute(
                sa.select(payroll_run_versions).where(
                    payroll_run_versions.c.id == run.current_version_id,
                    payroll_run_versions.c.organization_id == ctx.organization_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise ConflictError("Posted payroll run version not found.")

    period = await session.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != ctx.organization_id:
        raise NotFoundError("Payroll period not found.")

    org = await session.get(Organization, ctx.organization_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    return run, version, period, org


async def _resolve_employee_name(
    session: AsyncSession,
    *,
    organization_id: UUID,
    employee_id: UUID,
    as_of: date,
) -> str:
    # ADR 0005: versions pinned by a posted run are immutable (superseded, not mutated).
    profile = (
        (
            await session.execute(
                select_active_version(
                    employee_profile_versions,
                    header_id=employee_id,
                    organization_id=organization_id,
                    on_date=as_of,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    return str(profile["name"]) if profile is not None else ""


def _advance_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="advance_reference", header="Advance reference", kind=ColumnKind.TEXT),
        ReportColumn(key="principal", header="Principal", kind=ColumnKind.MONEY),
        ReportColumn(
            key="installment_amount",
            header="Installment recovered this month",
            kind=ColumnKind.MONEY,
        ),
        ReportColumn(
            key="installments_progress",
            header="Installments recovered/total",
            kind=ColumnKind.TEXT,
        ),
    )


def _accommodation_columns() -> tuple[ReportColumn, ...]:
    return (
        ReportColumn(key="employee_number", header="Employee No.", kind=ColumnKind.TEXT),
        ReportColumn(key="name", header="Name", kind=ColumnKind.TEXT),
        ReportColumn(key="quarters_identifier", header="Quarters", kind=ColumnKind.TEXT),
        ReportColumn(
            key="license_fee_actual",
            header="License fee (actual recovery)",
            kind=ColumnKind.MONEY,
        ),
        ReportColumn(
            key="informational_foregone_hra",
            header=_FOREGONE_HRA_HEADER,
            kind=ColumnKind.MONEY,
        ),
    )


async def build_advance_schedule(
    session: AsyncSession,
    ctx: ReportContext,
    *,
    advance_type: str,
    report_type: str = REPORT_TYPE_ADVANCE_SCHEDULE,
) -> AdvanceScheduleDTO:
    """Build an advance installment recovery schedule for one ``advance_type``."""
    if advance_type not in _ADVANCE_COMPONENT_BY_TYPE:
        raise ConflictError(
            f"Unsupported advance_type {advance_type!r}.",
            details={"advance_type": advance_type},
        )
    component_code = _ADVANCE_COMPONENT_BY_TYPE[advance_type]

    _run, version, period, org = await _require_posted_run(session, ctx)
    as_of = _month_end(period.period_year, period.period_month)

    lines = (
        (
            await session.execute(
                sa.select(
                    payroll_result_lines.c.amount,
                    payroll_result_lines.c.trace,
                    payroll_employee_results.c.employee_id,
                    payroll_employee_results.c.employee_number,
                )
                .select_from(
                    payroll_result_lines.join(
                        payroll_employee_results,
                        payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                    )
                )
                .where(
                    payroll_employee_results.c.organization_id == ctx.organization_id,
                    payroll_employee_results.c.run_version_id == version["id"],
                    payroll_result_lines.c.organization_id == ctx.organization_id,
                    payroll_result_lines.c.component_code == component_code,
                    payroll_result_lines.c.classification == "external_recovery",
                )
                .order_by(payroll_employee_results.c.employee_number)
            )
        )
        .mappings()
        .all()
    )

    rows: list[tuple[Any, ...]] = []
    schedule_total = _ZERO

    for line in lines:
        installment_amount = _money(line["amount"])
        trace = line["trace"] or {}
        source_ids = list(trace.get("source_version_ids") or [])
        installment_version_id = UUID(str(source_ids[0])) if source_ids else None

        reference = ""
        principal = _ZERO
        progress = ""
        if installment_version_id is not None:
            inst = (
                (
                    await session.execute(
                        sa.select(advance_installment_versions).where(
                            advance_installment_versions.c.id == installment_version_id,
                            advance_installment_versions.c.organization_id == ctx.organization_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if inst is not None:
                advance = await session.get(AdvanceAccount, inst["header_id"])
                if advance is None or advance.organization_id != ctx.organization_id:
                    continue
                if advance.advance_type != advance_type:
                    continue
                opening = int(inst["installments_recovered_opening"])
                total = int(inst["installments_total"])
                # This posted recovery counts as one installment toward progress.
                progress = f"{opening + 1}/{total}"
                reference = advance.reference or ""
                principal = _money(advance.principal)

        name = await _resolve_employee_name(
            session,
            organization_id=ctx.organization_id,
            employee_id=line["employee_id"],
            as_of=as_of,
        )
        schedule_total += installment_amount
        rows.append(
            (
                str(line["employee_number"]),
                name,
                reference,
                principal,
                installment_amount,
                progress,
            )
        )

    title = (
        "HBA recovery schedule"
        if advance_type == "hba"
        else f"Advance recovery schedule ({advance_type})"
    )
    columns = _advance_columns()
    totals: tuple[Any, ...] = (
        "TOTAL",
        None,
        None,
        None,
        _money(schedule_total),
        None,
    )

    return ReportDTO(
        report_type=report_type,
        template_version=ctx.template_version,
        title=title,
        organization_name=org.name,
        subtitle=_period_label(period.period_year, period.period_month),
        sections=(
            TableSection(
                title="Schedule",
                columns=columns,
                rows=tuple(rows),
                totals=totals,
            ),
        ),
    )


async def build_hba_schedule(session: AsyncSession, ctx: ReportContext) -> HbaScheduleDTO:
    """HBA schedule — equivalent to :func:`build_advance_schedule` with ``advance_type='hba'``."""
    return await build_advance_schedule(
        session,
        ctx,
        advance_type="hba",
        report_type=REPORT_TYPE_HBA_SCHEDULE,
    )


async def build_accommodation_schedule(
    session: AsyncSession,
    ctx: ReportContext,
    *,
    location: AccommodationLocation,
    report_type: str,
) -> AccommodationScheduleDTO:
    """Build an accommodation schedule for Mumbai or Worli allotments.

    Actual license-fee recovery and informational foregone HRA are kept in
    separate columns and separate total fields. Foregone HRA is never added into
    the actual recovery total.
    """
    if location not in ("mumbai", "worli"):
        raise ConflictError(
            f"Unsupported accommodation location {location!r}.",
            details={"location": location},
        )

    _run, version, period, org = await _require_posted_run(session, ctx)
    as_of = _month_end(period.period_year, period.period_month)

    result_rows = (
        (
            await session.execute(
                sa.select(payroll_employee_results)
                .where(
                    payroll_employee_results.c.organization_id == ctx.organization_id,
                    payroll_employee_results.c.run_version_id == version["id"],
                )
                .order_by(payroll_employee_results.c.employee_number)
            )
        )
        .mappings()
        .all()
    )
    if not result_rows:
        return ReportDTO(
            report_type=report_type,
            template_version=ctx.template_version,
            title=f"Accommodation schedule — {location.title()}",
            organization_name=org.name,
            subtitle=_period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Schedule",
                    columns=_accommodation_columns(),
                    rows=(),
                    totals=("TOTAL", None, None, _ZERO, None),
                ),
                TableSection(
                    title="Informational foregone HRA (not part of recovery total)",
                    columns=(
                        ReportColumn(
                            key="informational_foregone_hra_total",
                            header=_FOREGONE_HRA_HEADER,
                            kind=ColumnKind.MONEY,
                        ),
                    ),
                    rows=((_ZERO,),),
                ),
            ),
        )

    result_ids = [row["id"] for row in result_rows]
    lines = (
        (
            await session.execute(
                sa.select(payroll_result_lines)
                .where(
                    payroll_result_lines.c.organization_id == ctx.organization_id,
                    payroll_result_lines.c.employee_result_id.in_(result_ids),
                    payroll_result_lines.c.component_code.in_(
                        (_LICENSE_FEE_COMPONENT, _FOREGONE_HRA_COMPONENT)
                    ),
                )
                .order_by(
                    payroll_result_lines.c.employee_result_id,
                    payroll_result_lines.c.sequence,
                )
            )
        )
        .mappings()
        .all()
    )

    lines_by_result: dict[UUID, list[Any]] = {rid: [] for rid in result_ids}
    for line in lines:
        lines_by_result[line["employee_result_id"]].append(line)

    async def _assignment_for_line(line: Any) -> AccommodationAssignment | None:
        # Result-line traces currently omit accommodation_location (engine gap);
        # resolve location + quarters from the charge version pinned in source_version_ids.
        source_ids = list((line["trace"] or {}).get("source_version_ids") or [])
        if not source_ids:
            return None
        charge = (
            (
                await session.execute(
                    sa.select(accommodation_charge_versions).where(
                        accommodation_charge_versions.c.id == UUID(str(source_ids[0])),
                        accommodation_charge_versions.c.organization_id == ctx.organization_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if charge is None:
            return None
        assignment = await session.get(AccommodationAssignment, charge["header_id"])
        if assignment is None or assignment.organization_id != ctx.organization_id:
            return None
        return assignment

    schedule_rows: list[tuple[Any, ...]] = []
    actual_recovery_total = _ZERO
    informational_foregone_hra_total = _ZERO

    for result in result_rows:
        emp_lines = lines_by_result.get(result["id"], [])
        license_line = None
        foregone_line = None
        assignment: AccommodationAssignment | None = None

        for line in emp_lines:
            code = str(line["component_code"])
            line_assignment = await _assignment_for_line(line)
            if line_assignment is not None:
                if line_assignment.quarters_location != location:
                    continue
            else:
                # Fallback when charge version is missing: use trace if present.
                trace_loc = (
                    str((line["trace"] or {}).get("accommodation_location") or "").strip().lower()
                )
                if trace_loc != location:
                    continue
            if code == _LICENSE_FEE_COMPONENT:
                license_line = line
                assignment = line_assignment or assignment
            elif code == _FOREGONE_HRA_COMPONENT:
                foregone_line = line
                assignment = line_assignment or assignment

        if license_line is None:
            continue

        license_fee = _money(license_line["amount"])
        foregone = _money(foregone_line["amount"]) if foregone_line is not None else _ZERO
        actual_recovery_total += license_fee
        informational_foregone_hra_total += foregone

        quarters_identifier = assignment.quarters_identifier if assignment is not None else ""

        name = await _resolve_employee_name(
            session,
            organization_id=ctx.organization_id,
            employee_id=result["employee_id"],
            as_of=as_of,
        )
        schedule_rows.append(
            (
                str(result["employee_number"]),
                name,
                quarters_identifier,
                license_fee,
                foregone,
            )
        )

    # Defense in depth: recovery total is actual only — never actual + foregone.
    actual_recovery_total = _money(actual_recovery_total)
    informational_foregone_hra_total = _money(informational_foregone_hra_total)

    return ReportDTO(
        report_type=report_type,
        template_version=ctx.template_version,
        title=f"Accommodation schedule — {location.title()}",
        organization_name=org.name,
        subtitle=_period_label(period.period_year, period.period_month),
        sections=(
            TableSection(
                title="Schedule",
                columns=_accommodation_columns(),
                rows=tuple(schedule_rows),
                # Only actual recovery is totaled here; foregone cell stays None.
                totals=("TOTAL", None, None, actual_recovery_total, None),
            ),
            TableSection(
                title="Informational foregone HRA (not part of recovery total)",
                columns=(
                    ReportColumn(
                        key="informational_foregone_hra_total",
                        header=_FOREGONE_HRA_HEADER,
                        kind=ColumnKind.MONEY,
                    ),
                ),
                rows=((informational_foregone_hra_total,),),
            ),
            TableSection(
                title="Actual recovery total",
                columns=(
                    ReportColumn(
                        key="actual_recovery_total",
                        header="License fee actual recovery total",
                        kind=ColumnKind.MONEY,
                    ),
                ),
                rows=((actual_recovery_total,),),
            ),
        ),
    )


class HbaScheduleBuilder:
    """Build the HBA recovery schedule DTO from a posted run snapshot."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> HbaScheduleDTO:
        return await build_hba_schedule(session, ctx)


class AdvanceScheduleBuilder:
    """Parameterized advance schedule builder (festival / motor-car / HBA / …)."""

    def __init__(
        self, advance_type: str, *, report_type: str = REPORT_TYPE_ADVANCE_SCHEDULE
    ) -> None:
        self.advance_type = advance_type
        self.report_type = report_type

    async def build(self, session: AsyncSession, ctx: ReportContext) -> AdvanceScheduleDTO:
        return await build_advance_schedule(
            session,
            ctx,
            advance_type=self.advance_type,
            report_type=self.report_type,
        )


class AccommodationScheduleBuilder:
    """Accommodation schedule for one quarters location (mumbai | worli)."""

    def __init__(self, location: AccommodationLocation, *, report_type: str) -> None:
        self.location = location
        self.report_type = report_type

    async def build(self, session: AsyncSession, ctx: ReportContext) -> AccommodationScheduleDTO:
        return await build_accommodation_schedule(
            session,
            ctx,
            location=self.location,
            report_type=self.report_type,
        )


hba_schedule_builder = HbaScheduleBuilder()
# Registered ``advance_schedule`` entry is infrastructure; type is set by the caller /
# orchestrator when constructing :class:`AdvanceScheduleBuilder`. The module-level
# instance defaults to ``other`` so the closed registry has a concrete builder.
advance_schedule_builder = AdvanceScheduleBuilder("other")
accommodation_mumbai_builder = AccommodationScheduleBuilder(
    "mumbai", report_type=REPORT_TYPE_ACCOMMODATION_MUMBAI
)
accommodation_worli_builder = AccommodationScheduleBuilder(
    "worli", report_type=REPORT_TYPE_ACCOMMODATION_WORLI
)


def recovery_to_json(dto: ReportDTO) -> dict[str, Any]:
    return base_to_json(dto)


def recovery_to_excel(dto: ReportDTO) -> bytes:
    return base_to_excel(dto)


def _dto_with_totals_folded_into_rows(dto: ReportDTO) -> ReportDTO:
    """Work around ``app.reports.pdf`` omitting ``widths`` when drawing totals.

    The generic PDF writer currently crashes on ``section.totals``; fold the
    totals tuple into the body rows so recovery PDFs still render. JSON/Excel
    continue to use the original DTO with a proper totals row.
    """
    sections: list[TableSection] = []
    for section in dto.sections:
        if section.totals is None:
            sections.append(section)
            continue
        sections.append(
            TableSection(
                title=section.title,
                columns=section.columns,
                rows=(*section.rows, section.totals),
                totals=None,
            )
        )
    return ReportDTO(
        report_type=dto.report_type,
        template_version=dto.template_version,
        title=dto.title,
        organization_name=dto.organization_name,
        subtitle=dto.subtitle,
        sections=tuple(sections),
    )


def recovery_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(_dto_with_totals_folded_into_rows(dto))


def register_recovery_reports(registry: ReportRegistry) -> None:
    """Register HBA, generic advance, and accommodation schedule report types."""
    shared = dict(
        to_json=recovery_to_json,
        to_excel=recovery_to_excel,
        to_pdf=recovery_to_pdf,
        content_types=DEFAULT_CONTENT_TYPES,
        filename_pattern=FILENAME_PATTERN,
    )
    registry.register(REPORT_TYPE_HBA_SCHEDULE, builder=hba_schedule_builder, **shared)
    registry.register(REPORT_TYPE_ADVANCE_SCHEDULE, builder=advance_schedule_builder, **shared)
    registry.register(
        REPORT_TYPE_ACCOMMODATION_MUMBAI, builder=accommodation_mumbai_builder, **shared
    )
    registry.register(
        REPORT_TYPE_ACCOMMODATION_WORLI, builder=accommodation_worli_builder, **shared
    )
