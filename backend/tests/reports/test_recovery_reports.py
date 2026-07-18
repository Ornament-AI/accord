"""Golden tests for HBA / advance / accommodation recovery report builders."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.exceptions import ConflictError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import Employee, employee_pay_versions, employee_profile_versions
from app.models.pay_components import PayComponent
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
)
from app.models.platform import PayrollApproval
from app.reports.base import ReportContext, ReportRegistry
from app.reports.families.recovery import (
    REPORT_TYPE_ACCOMMODATION_MUMBAI,
    REPORT_TYPE_ACCOMMODATION_WORLI,
    REPORT_TYPE_ADVANCE_SCHEDULE,
    REPORT_TYPE_HBA_SCHEDULE,
    AdvanceScheduleBuilder,
    AccommodationScheduleBuilder,
    HbaScheduleBuilder,
    _FOREGONE_HRA_HEADER,
    build_accommodation_schedule,
    build_advance_schedule,
    build_hba_schedule,
    recovery_to_excel,
    recovery_to_pdf,
    register_recovery_reports,
)
from app.services import versioning
from app.services.run_calculation import calculate_run_command
from app.services.run_posting import post_run
from app.tenancy import bind_tenant_context
from tests.e2e.fixture_loader import (
    ADVANCE_COMPONENT_CODES,
    EmployeeSeed,
    line_amount,
    load_june_fixture,
    map_quarters_location,
    map_regime,
)
from tests.identity_helpers import seed_organization, seed_user

EFFECTIVE_FROM = date(2026, 1, 1)
TEMPLATE_VERSION = "v1"
_TWO = Decimal("0.01")

_HBA_TOTAL = Decimal("72723.00")
_MUMBAI_TOTAL = Decimal("10419.00")
_WORLI_TOTAL = Decimal("1250.00")

# June fixture employees that carry HBA and/or accommodation recoveries.
_RECOVERY_EMPLOYEE_IDS = frozenset({"E001", "E002", "E003", "E004", "E017", "E018", "E029"})


def _dec(value: object) -> Decimal:
    return Decimal(str(value)).quantize(_TWO)


def _ctx(*, org_id: UUID, run_id: UUID) -> ReportContext:
    return ReportContext(
        organization_id=org_id,
        posted_run_id=run_id,
        template_version=TEMPLATE_VERSION,
        generated_at=datetime.now(timezone.utc),
        engine_version="test",
    )


async def _bind(session: AsyncSession, org_id: UUID, user_id: UUID) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


def _needs_recovery(employee: EmployeeSeed) -> bool:
    if employee.fixture_id not in _RECOVERY_EMPLOYEE_IDS:
        return False
    codes = {line.component_code for line in employee.lines}
    return bool(codes & (ADVANCE_COMPONENT_CODES | {"ACCOMMODATION_LICENSE_FEE"}))


async def _seed_posted_june_recovery_world(session: AsyncSession) -> dict:
    """Seed the June recovery slice (7 employees), calculate, approve, and post."""
    fixture = load_june_fixture()
    employees = [e for e in fixture.employees if _needs_recovery(e)]
    assert len(employees) == 7

    if session.in_transaction():
        await session.rollback()

    org = await seed_organization(
        session, name=fixture.organization.name, slug=f"rec-{uuid4().hex[:10]}"
    )
    user = await seed_user(session, workos_user_id=f"rec_{uuid4().hex[:10]}")
    await session.commit()

    await _bind(session, org.id, user.id)

    catalog_codes = {
        "BASIC": ("Basic Pay", "earning"),
        "HBA_INSTALLMENT": ("HBA Installment", "external_recovery"),
        "ACCOMMODATION_LICENSE_FEE": ("Accommodation License Fee", "external_recovery"),
    }
    component_ids: dict[str, UUID] = {}
    for code, (name, classification) in catalog_codes.items():
        row = PayComponent(
            organization_id=org.id,
            code=code,
            name=name,
            classification=classification,
        )
        session.add(row)
        await session.flush()
        component_ids[code] = row.id

    employee_ids: dict[str, UUID] = {}
    for emp in employees:
        regime, gpf_jurisdiction = map_regime(emp.regime)
        header = Employee(organization_id=org.id, employee_number=emp.fixture_id)
        session.add(header)
        await session.flush()
        employee_ids[emp.fixture_id] = header.id

        await versioning.insert_version(
            session,
            employee_profile_versions,
            organization_id=org.id,
            header_id=header.id,
            effective_from=EFFECTIVE_FROM,
            values={
                "name": emp.name,
                "sevarth_id": emp.sevarth_id,
                "pan": emp.pan,
                "date_of_birth": date(1990, 1, 15),
                "date_of_joining": date(2015, 6, 1),
                "retirement_regime": regime,
                "gpf_jurisdiction": gpf_jurisdiction,
                "pran": emp.pran,
                "gpf_account_number": emp.gpf_account,
                "epf_number": emp.epf_number,
                "pension_account": None,
            },
            change_reason=None,
            created_by=user.id,
        )

        basic = line_amount(emp, "BASIC") or Decimal("50000")
        await versioning.insert_version(
            session,
            employee_pay_versions,
            organization_id=org.id,
            header_id=header.id,
            effective_from=EFFECTIVE_FROM,
            values={"pay_matrix_level": "L10", "basic_pay": _dec(basic)},
            change_reason=None,
            created_by=user.id,
        )

        hba_amount = line_amount(emp, "HBA_INSTALLMENT")
        if hba_amount is not None:
            principal = max(hba_amount * Decimal("24"), hba_amount)
            advance = AdvanceAccount(
                organization_id=org.id,
                employee_id=header.id,
                advance_type="hba",
                principal=_dec(principal),
                sanctioned_on=EFFECTIVE_FROM,
                reference=f"HBA-{emp.fixture_id}",
            )
            session.add(advance)
            await session.flush()
            await versioning.insert_version(
                session,
                advance_installment_versions,
                organization_id=org.id,
                header_id=advance.id,
                effective_from=EFFECTIVE_FROM,
                values={
                    "installment_amount": _dec(hba_amount),
                    "installments_total": 24,
                    "installments_recovered_opening": 0,
                },
                change_reason=None,
                created_by=user.id,
            )

        license_fee = line_amount(emp, "ACCOMMODATION_LICENSE_FEE")
        if license_fee is not None:
            assert emp.accommodation is not None
            foregone = line_amount(emp, "FOREGONE_HRA")
            assignment = AccommodationAssignment(
                organization_id=org.id,
                employee_id=header.id,
                quarters_location=map_quarters_location(emp.accommodation.location),
                quarters_identifier=f"Q-{emp.fixture_id}",
            )
            session.add(assignment)
            await session.flush()
            charge_values: dict[str, object] = {"license_fee": _dec(license_fee)}
            if foregone is not None:
                charge_values["informational_hra_foregone"] = _dec(foregone)
            await versioning.insert_version(
                session,
                accommodation_charge_versions,
                organization_id=org.id,
                header_id=assignment.id,
                effective_from=EFFECTIVE_FROM,
                values=charge_values,
                change_reason=None,
                created_by=user.id,
            )

    period = PayrollPeriod(
        organization_id=org.id,
        period_year=2026,
        period_month=6,
        status="open",
    )
    session.add(period)
    await session.flush()
    run = PayrollRun(
        organization_id=org.id,
        period_id=period.id,
        run_type="regular",
        status="draft",
    )
    session.add(run)
    await session.commit()

    world = {
        "org_id": org.id,
        "user_id": user.id,
        "run_id": run.id,
        "employee_ids": employee_ids,
        "fixture_employees": {e.fixture_id: e for e in employees},
    }

    await _bind(session, org.id, user.id)
    calc = await calculate_run_command(
        session,
        organization_id=org.id,
        run_id=run.id,
        user_id=user.id,
    )

    await _bind(session, org.id, user.id)
    run_row = await session.get(PayrollRun, run.id)
    assert run_row is not None
    run_row.status = "approved"
    session.add(
        PayrollApproval(
            organization_id=org.id,
            run_id=run.id,
            run_version_id=calc["version_id"],
            content_hash=calc["content_hash"],
            action="approve",
            actor_user_id=user.id,
            reason="Recovery report golden approve",
        )
    )
    await session.commit()

    await _bind(session, org.id, user.id)
    posted = await post_run(
        session,
        organization_id=org.id,
        run_id=run.id,
        user_id=user.id,
    )
    assert posted["status"] == "posted"
    world["version_id"] = UUID(str(calc["version_id"]))
    return world


async def _posted_lines_by_component(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    version_id: UUID,
    component_code: str,
) -> dict[str, Decimal]:
    await _bind(session, org_id, user_id)
    rows = (
        await session.execute(
            sa.select(
                payroll_employee_results.c.employee_number,
                payroll_result_lines.c.amount,
            )
            .select_from(
                payroll_result_lines.join(
                    payroll_employee_results,
                    payroll_result_lines.c.employee_result_id == payroll_employee_results.c.id,
                )
            )
            .where(
                payroll_employee_results.c.organization_id == org_id,
                payroll_employee_results.c.run_version_id == version_id,
                payroll_result_lines.c.component_code == component_code,
            )
        )
    ).all()
    return {str(number): _dec(amount) for number, amount in rows}


_IDENTITY_TRUNCATE_SQL = text(
    "TRUNCATE TABLE sessions, organization_memberships, organization_settings, "
    "organizations, users, idempotency_keys RESTART IDENTITY CASCADE"
)


async def _truncate_identity_with_retry() -> None:
    """TRUNCATE identity tables; retry when sibling lanes contend on accord_test."""
    factory = get_session_factory()
    last_exc: BaseException | None = None
    for attempt in range(8):
        try:
            async with factory() as trunc_session:
                await trunc_session.execute(_IDENTITY_TRUNCATE_SQL)
                await trunc_session.commit()
            return
        except Exception as exc:  # noqa: BLE001 — retry deadlock/lock only
            last_exc = exc
            msg = str(exc).lower()
            if "deadlock" not in msg and "lock" not in msg and "could not obtain" not in msg:
                raise
            await asyncio.sleep(0.35 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


@pytest_asyncio.fixture
async def posted_june_recovery(session):
    last_exc: BaseException | None = None
    for attempt in range(5):
        try:
            await _truncate_identity_with_retry()
            return await _seed_posted_june_recovery_world(session)
        except Exception as exc:  # noqa: BLE001 — retry shared-DB contention
            last_exc = exc
            msg = str(exc).lower()
            if "deadlock" not in msg and "lock" not in msg and "could not obtain" not in msg:
                raise
            if session.in_transaction():
                await session.rollback()
            await asyncio.sleep(0.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


@pytest.mark.asyncio
async def test_registry_registers_four_recovery_report_types() -> None:
    registry = ReportRegistry()
    register_recovery_reports(registry)
    for report_type in (
        REPORT_TYPE_HBA_SCHEDULE,
        REPORT_TYPE_ADVANCE_SCHEDULE,
        REPORT_TYPE_ACCOMMODATION_MUMBAI,
        REPORT_TYPE_ACCOMMODATION_WORLI,
    ):
        assert report_type in registry
        entry = registry.get(report_type)
        assert entry.builder is not None
        assert callable(entry.formatters.to_json)
        assert callable(entry.formatters.to_excel)
        assert callable(entry.formatters.to_pdf)


@pytest.mark.asyncio
async def test_june_recovery_schedules_golden_and_formatters(session, posted_june_recovery):
    """Single seeded posted world covers HBA, advance equivalence, accommodation, exports."""
    world = posted_june_recovery
    await _bind(session, world["org_id"], world["user_id"])
    ctx = _ctx(org_id=world["org_id"], run_id=world["run_id"])

    hba = await build_hba_schedule(session, ctx)
    assert hba.report_type == REPORT_TYPE_HBA_SCHEDULE
    hba_schedule = hba.sections[0]
    assert len(hba_schedule.rows) == 3
    assert hba_schedule.totals is not None
    assert _dec(hba_schedule.totals[4]) == _HBA_TOTAL

    posted_hba = await _posted_lines_by_component(
        session,
        org_id=world["org_id"],
        user_id=world["user_id"],
        version_id=world["version_id"],
        component_code="HBA_INSTALLMENT",
    )
    assert sum(posted_hba.values(), _dec("0")) == _HBA_TOTAL
    by_number = {row[0]: row for row in hba_schedule.rows}
    assert set(by_number) == set(posted_hba)
    for employee_number, amount in posted_hba.items():
        row = by_number[employee_number]
        assert _dec(row[4]) == amount
        assert row[2] == f"HBA-{employee_number}"
        assert row[5] == "1/24"

    await _bind(session, world["org_id"], world["user_id"])
    advance = await build_advance_schedule(
        session, ctx, advance_type="hba", report_type=REPORT_TYPE_ADVANCE_SCHEDULE
    )
    assert hba_schedule.rows == advance.sections[0].rows
    assert hba_schedule.totals == advance.sections[0].totals
    via_class = await AdvanceScheduleBuilder("hba").build(session, ctx)
    assert via_class.sections[0].rows == hba_schedule.rows

    await _bind(session, world["org_id"], world["user_id"])
    mumbai = await build_accommodation_schedule(
        session, ctx, location="mumbai", report_type=REPORT_TYPE_ACCOMMODATION_MUMBAI
    )
    worli = await build_accommodation_schedule(
        session, ctx, location="worli", report_type=REPORT_TYPE_ACCOMMODATION_WORLI
    )
    mumbai_schedule = mumbai.sections[0]
    worli_schedule = worli.sections[0]
    assert len(mumbai_schedule.rows) == 3
    assert len(worli_schedule.rows) == 1
    assert mumbai_schedule.totals is not None
    assert worli_schedule.totals is not None
    assert _dec(mumbai_schedule.totals[3]) == _MUMBAI_TOTAL
    assert _dec(worli_schedule.totals[3]) == _WORLI_TOTAL

    mumbai_numbers = {row[0] for row in mumbai_schedule.rows}
    worli_numbers = {row[0] for row in worli_schedule.rows}
    assert mumbai_numbers.isdisjoint(worli_numbers)
    assert mumbai_numbers == {"E001", "E002", "E003"}
    assert worli_numbers == {"E017"}

    assert any(_FOREGONE_HRA_HEADER in col.header for col in mumbai_schedule.columns)
    mumbai_actual = _dec(
        next(s for s in mumbai.sections if s.title == "Actual recovery total").rows[0][0]
    )
    mumbai_foregone = _dec(
        next(s for s in mumbai.sections if s.title.startswith("Informational foregone HRA")).rows[
            0
        ][0]
    )
    assert mumbai_actual == _MUMBAI_TOTAL
    assert mumbai_foregone > _dec("0")
    assert mumbai_actual != mumbai_actual + mumbai_foregone
    assert _dec(mumbai_schedule.totals[3]) == mumbai_actual
    assert mumbai_schedule.totals[4] is None

    posted_license = await _posted_lines_by_component(
        session,
        org_id=world["org_id"],
        user_id=world["user_id"],
        version_id=world["version_id"],
        component_code="ACCOMMODATION_LICENSE_FEE",
    )
    posted_foregone = await _posted_lines_by_component(
        session,
        org_id=world["org_id"],
        user_id=world["user_id"],
        version_id=world["version_id"],
        component_code="FOREGONE_HRA",
    )
    for row in (*mumbai_schedule.rows, *worli_schedule.rows):
        number = row[0]
        assert _dec(row[3]) == posted_license[number]
        assert _dec(row[4]) == posted_foregone[number]
        assert row[2] == f"Q-{number}"

    await _bind(session, world["org_id"], world["user_id"])
    hba_xlsx = recovery_to_excel(await HbaScheduleBuilder().build(session, ctx))
    wb = load_workbook(BytesIO(hba_xlsx))
    assert wb.active is not None
    assert "HBA" in str(wb.active["A1"].value)

    mumbai_pdf = recovery_to_pdf(
        await AccommodationScheduleBuilder(
            "mumbai", report_type=REPORT_TYPE_ACCOMMODATION_MUMBAI
        ).build(session, ctx)
    )
    assert mumbai_pdf.startswith(b"%PDF")
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(mumbai_pdf)).pages)
    assert "Accommodation" in pdf_text
    assert "10,419.00" in pdf_text or "10419" in pdf_text
    assert "Informational" in pdf_text


@pytest.mark.asyncio
async def test_unposted_run_raises_conflict_error(session):
    await _truncate_identity_with_retry()
    if session.in_transaction():
        await session.rollback()
    org = await seed_organization(session, name="Draft Org", slug=f"draft-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"draft_{uuid4().hex[:10]}")
    await session.commit()

    await _bind(session, org.id, user.id)
    period = PayrollPeriod(organization_id=org.id, period_year=2026, period_month=6, status="open")
    session.add(period)
    await session.flush()
    run = PayrollRun(
        organization_id=org.id,
        period_id=period.id,
        run_type="regular",
        status="draft",
    )
    session.add(run)
    await session.commit()

    await _bind(session, org.id, user.id)
    ctx = _ctx(org_id=org.id, run_id=run.id)
    with pytest.raises(ConflictError, match="must be posted"):
        await build_hba_schedule(session, ctx)
    with pytest.raises(ConflictError, match="must be posted"):
        await build_accommodation_schedule(
            session, ctx, location="mumbai", report_type=REPORT_TYPE_ACCOMMODATION_MUMBAI
        )
