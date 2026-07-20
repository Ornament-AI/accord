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

from datetime import date
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.effective import select_active_version
from app.models.employees import employee_profile_versions
from app.models.payroll_runs import (
    payroll_employee_results,
    payroll_result_lines,
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
from app.reports.snapshots import load_report_snapshot
from app.reports.posted_run import (
    DEFAULT_CONTENT_TYPES,
    DEFAULT_FILENAME_PATTERN,
    ZERO,
    money,
    month_end,
    period_label,
    require_posted_run,
)

REPORT_TYPE_HBA_SCHEDULE = "hba_schedule"
REPORT_TYPE_ADVANCE_SCHEDULE = "advance_schedule"
REPORT_TYPE_GPF_ADVANCE_SCHEDULE = "gpf_advance_schedule"
REPORT_TYPE_FESTIVAL_ADVANCE_SCHEDULE = "festival_advance_schedule"
REPORT_TYPE_MOTOR_CAR_ADVANCE_SCHEDULE = "motor_car_advance_schedule"
REPORT_TYPE_MOTORCYCLE_ADVANCE_SCHEDULE = "motorcycle_advance_schedule"
REPORT_TYPE_COMPONENT_SCHEDULE = "component_schedule"
REPORT_TYPE_ACCOMMODATION_MUMBAI = "accommodation_mumbai_schedule"
REPORT_TYPE_ACCOMMODATION_WORLI = "accommodation_worli_schedule"

HbaScheduleDTO = ReportDTO
AdvanceScheduleDTO = ReportDTO
AccommodationScheduleDTO = ReportDTO

AccommodationLocation = Literal["mumbai", "worli"]


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

FILENAME_PATTERN = DEFAULT_FILENAME_PATTERN

# Column header must explicitly label foregone HRA as informational.
_FOREGONE_HRA_HEADER = "Informational foregone HRA (not recovered)"


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

    _run, version, period, org = await require_posted_run(session, ctx)
    as_of = month_end(period.period_year, period.period_month)
    snapshot = (
        await load_report_snapshot(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        if ctx.template_version == "v2"
        else None
    )
    advance_sources = (
        (snapshot.get("recovery_sources") or {}).get("advance_installments") or {}
        if snapshot is not None
        else {}
    )
    identities = snapshot.get("employee_identity") or {} if snapshot is not None else {}

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
    schedule_total = ZERO

    for line in lines:
        installment_amount = money(line["amount"])
        trace = line["trace"] or {}
        source_ids = list(trace.get("source_version_ids") or [])
        installment_version_id = UUID(str(source_ids[0])) if source_ids else None

        reference = ""
        principal = ZERO
        progress = ""
        if installment_version_id is not None and snapshot is not None:
            advance = advance_sources.get(str(installment_version_id))
            if not isinstance(advance, dict):
                raise ConflictError(
                    "Posted report snapshot is missing advance presentation data.",
                    details={"source_version_id": str(installment_version_id)},
                )
            if advance.get("advance_type") != advance_type:
                continue
            opening = int(advance["installments_recovered_opening"])
            total = int(advance["installments_total"])
            progress = f"{opening + 1}/{total}"
            reference = str(advance.get("reference") or "")
            principal = money(advance["principal"])
        elif installment_version_id is not None:
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
                principal = money(advance.principal)

        if snapshot is not None:
            identity = identities.get(str(line["employee_id"]), {})
            name = str(identity.get("name") or "")
        else:
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
        money(schedule_total),
        None,
    )

    return ReportDTO(
        report_type=report_type,
        template_version=ctx.template_version,
        title=title,
        organization_name=(
            str((snapshot.get("organization") or {}).get("name") or org.name)
            if snapshot is not None
            else org.name
        ),
        subtitle=period_label(period.period_year, period.period_month),
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

    _run, version, period, org = await require_posted_run(session, ctx)
    as_of = month_end(period.period_year, period.period_month)
    snapshot = (
        await load_report_snapshot(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        if ctx.template_version == "v2"
        else None
    )
    accommodation_sources = (
        (snapshot.get("recovery_sources") or {}).get("accommodation_charges") or {}
        if snapshot is not None
        else {}
    )
    identities = snapshot.get("employee_identity") or {} if snapshot is not None else {}

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
            subtitle=period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Schedule",
                    columns=_accommodation_columns(),
                    rows=(),
                    totals=("TOTAL", None, None, ZERO, None),
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
                    rows=((ZERO,),),
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

    async def _assignment_for_line(line: Any) -> tuple[str, str] | None:
        # Result-line traces currently omit accommodation_location (engine gap);
        # resolve location + quarters from the charge version pinned in source_version_ids.
        source_ids = list((line["trace"] or {}).get("source_version_ids") or [])
        if not source_ids:
            return None
        if snapshot is not None:
            assignment = accommodation_sources.get(str(source_ids[0]))
            if not isinstance(assignment, dict):
                raise ConflictError(
                    "Posted report snapshot is missing accommodation presentation data.",
                    details={"source_version_id": str(source_ids[0])},
                )
            return (
                str(assignment.get("quarters_location") or ""),
                str(assignment.get("quarters_identifier") or ""),
            )
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
        return assignment.quarters_location, assignment.quarters_identifier

    schedule_rows: list[tuple[Any, ...]] = []
    actual_recovery_total = ZERO
    informational_foregone_hra_total = ZERO

    for result in result_rows:
        emp_lines = lines_by_result.get(result["id"], [])
        license_line = None
        foregone_line = None
        assignment: tuple[str, str] | None = None

        for line in emp_lines:
            code = str(line["component_code"])
            line_assignment = await _assignment_for_line(line)
            if line_assignment is not None:
                if line_assignment[0] != location:
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

        license_fee = money(license_line["amount"])
        foregone = money(foregone_line["amount"]) if foregone_line is not None else ZERO
        actual_recovery_total += license_fee
        informational_foregone_hra_total += foregone

        quarters_identifier = assignment[1] if assignment is not None else ""

        if snapshot is not None:
            identity = identities.get(str(result["employee_id"]), {})
            name = str(identity.get("name") or "")
        else:
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
    actual_recovery_total = money(actual_recovery_total)
    informational_foregone_hra_total = money(informational_foregone_hra_total)

    return ReportDTO(
        report_type=report_type,
        template_version=ctx.template_version,
        title=f"Accommodation schedule — {location.title()}",
        organization_name=(
            str((snapshot.get("organization") or {}).get("name") or org.name)
            if snapshot is not None
            else org.name
        ),
        subtitle=period_label(period.period_year, period.period_month),
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


class ComponentScheduleBuilder:
    """Build a custom schedule variant declared by snapshotted catalog metadata."""

    async def build(self, session: AsyncSession, ctx: ReportContext) -> ReportDTO:
        code = (ctx.variant_key or "").strip()
        if not code:
            raise ConflictError("component_schedule requires a component-code variant_key.")
        _run, version, period, org = await require_posted_run(session, ctx)
        snapshot = await load_report_snapshot(
            session,
            organization_id=ctx.organization_id,
            run_version_id=version["id"],
        )
        catalog = {
            str(item.get("code")): item
            for item in snapshot.get("component_catalog", [])
            if isinstance(item, dict) and item.get("code")
        }
        component = catalog.get(code)
        if component is None or not component.get("schedule_kind"):
            raise ConflictError(
                f"Component {code!r} has no schedule in the posted report snapshot.",
                details={"component_code": code},
            )

        line_rows = (
            (
                await session.execute(
                    sa.select(
                        payroll_employee_results.c.employee_id,
                        payroll_employee_results.c.employee_number,
                        payroll_result_lines.c.amount,
                    )
                    .select_from(
                        payroll_result_lines.join(
                            payroll_employee_results,
                            payroll_result_lines.c.employee_result_id
                            == payroll_employee_results.c.id,
                        )
                    )
                    .where(
                        payroll_employee_results.c.organization_id == ctx.organization_id,
                        payroll_employee_results.c.run_version_id == version["id"],
                        payroll_result_lines.c.organization_id == ctx.organization_id,
                        payroll_result_lines.c.component_code == code,
                    )
                    .order_by(payroll_employee_results.c.employee_number)
                )
            )
            .mappings()
            .all()
        )
        identities = snapshot.get("employee_identity") or {}
        rows: list[tuple[Any, ...]] = []
        total = ZERO
        for line in line_rows:
            identity = identities.get(str(line["employee_id"]), {})
            amount = money(line["amount"])
            total += amount
            rows.append(
                (
                    str(line["employee_number"]),
                    str(identity.get("name") or ""),
                    amount,
                )
            )

        title = str(component.get("schedule_title") or component.get("name") or code)
        account_head = str(component.get("schedule_account_head") or "")
        return ReportDTO(
            report_type=REPORT_TYPE_COMPONENT_SCHEDULE,
            template_version=ctx.template_version,
            title=title,
            organization_name=str((snapshot.get("organization") or {}).get("name") or org.name),
            subtitle=period_label(period.period_year, period.period_month),
            sections=(
                TableSection(
                    title="Schedule",
                    columns=(
                        ReportColumn("employee_number", "Employee No."),
                        ReportColumn("name", "Name"),
                        ReportColumn(
                            "amount", str(component.get("name") or code), ColumnKind.MONEY
                        ),
                    ),
                    rows=tuple(rows),
                    totals=("TOTAL", None, money(total)),
                ),
                TableSection(
                    title="Accounting",
                    columns=(ReportColumn("account_head", "Account Head"),),
                    rows=((account_head,),),
                ),
            ),
        )


hba_schedule_builder = HbaScheduleBuilder()
# Registered ``advance_schedule`` entry is infrastructure; type is set by the caller /
# orchestrator when constructing :class:`AdvanceScheduleBuilder`. The module-level
# instance defaults to ``other`` so the closed registry has a concrete builder.
advance_schedule_builder = AdvanceScheduleBuilder("other")
gpf_advance_schedule_builder = AdvanceScheduleBuilder(
    "gpf_advance", report_type=REPORT_TYPE_GPF_ADVANCE_SCHEDULE
)
festival_advance_schedule_builder = AdvanceScheduleBuilder(
    "festival", report_type=REPORT_TYPE_FESTIVAL_ADVANCE_SCHEDULE
)
motor_car_advance_schedule_builder = AdvanceScheduleBuilder(
    "motor_car", report_type=REPORT_TYPE_MOTOR_CAR_ADVANCE_SCHEDULE
)
motorcycle_advance_schedule_builder = AdvanceScheduleBuilder(
    "motorcycle", report_type=REPORT_TYPE_MOTORCYCLE_ADVANCE_SCHEDULE
)
component_schedule_builder = ComponentScheduleBuilder()
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


def recovery_to_pdf(dto: ReportDTO) -> bytes:
    return base_to_pdf(dto)


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
        REPORT_TYPE_GPF_ADVANCE_SCHEDULE,
        builder=gpf_advance_schedule_builder,
        **shared,
    )
    registry.register(
        REPORT_TYPE_FESTIVAL_ADVANCE_SCHEDULE,
        builder=festival_advance_schedule_builder,
        **shared,
    )
    registry.register(
        REPORT_TYPE_MOTOR_CAR_ADVANCE_SCHEDULE,
        builder=motor_car_advance_schedule_builder,
        **shared,
    )
    registry.register(
        REPORT_TYPE_MOTORCYCLE_ADVANCE_SCHEDULE,
        builder=motorcycle_advance_schedule_builder,
        **shared,
    )
    registry.register(
        REPORT_TYPE_COMPONENT_SCHEDULE,
        builder=component_schedule_builder,
        **shared,
    )
    registry.register(
        REPORT_TYPE_ACCOMMODATION_MUMBAI, builder=accommodation_mumbai_builder, **shared
    )
    registry.register(
        REPORT_TYPE_ACCOMMODATION_WORLI, builder=accommodation_worli_builder, **shared
    )
