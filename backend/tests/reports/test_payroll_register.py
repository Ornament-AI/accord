"""Golden tests for Pay Bill and Treasury Face report builders/formatters."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import (
    Employee,
    employee_pay_versions,
    employee_posting_versions,
    employee_profile_versions,
)
from app.models.identity import Organization
from app.models.org_structure import Office, Post
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.platform import PayrollApproval
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.models.reports import ReportConfiguration
from app.reports.amount_in_words import amount_in_words
from app.reports.base import ReportContext
from app.reports.excel import MONEY_FORMAT
from app.reports.families.payroll_register import (
    REPORT_TYPE_PAY_BILL,
    REPORT_TYPE_TREASURY_FACE,
    pay_bill_builder,
    pay_bill_to_excel,
    pay_bill_to_json,
    pay_bill_to_pdf,
    treasury_face_builder,
    treasury_face_to_excel,
    treasury_face_to_json,
    treasury_face_to_pdf,
)
from app.services import versioning
from app.services.run_calculation import calculate_run_command
from app.services.run_posting import post_run
from app.tenancy import bind_tenant_context
from tests.roster_helpers import initialize_run_roster
from tests.e2e.fixture_loader import (
    ACCOMMODATION_COMPONENT_CODES,
    ADVANCE_COMPONENT_CODES,
    BASIC_CODE,
    RECURRING_COMPONENT_CODES,
    EmployeeSeed,
    line_amount,
    load_june_fixture,
    map_quarters_location,
    map_regime,
    money,
)
from tests.identity_helpers import seed_organization, seed_user

EFFECTIVE_FROM = date(2026, 1, 1)
PERIOD_YEAR = 2026
PERIOD_MONTH = 6
TEMPLATE_VERSION = "v1"

_CLASSIFICATION_DB = {
    "earning": "earning",
    "employer_contribution": "employer_contribution",
    "AG_deduction": "ag_deduction",
    "treasury_deduction": "treasury_deduction",
    "gross_adjustment": "gross_adjustment",
    "external_recovery": "external_recovery",
}

_TWO = Decimal("0.01")
_ZERO = Decimal("0.00")

# Module-level cache so the expensive June seed runs once per process.
_CACHED_WORLD: dict | None = None


def _dec(value: object) -> Decimal:
    return Decimal(str(value)).quantize(_TWO)


async def _bind(session: AsyncSession, org_id: UUID, user_id: UUID) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


async def _seed_posted_june(session: AsyncSession) -> dict:
    """Seed fixture_loader June world, calculate, approve directly, and post."""
    fixture = load_june_fixture()
    assert len(fixture.employees) == 32

    if session.in_transaction():
        await session.rollback()

    org = await seed_organization(
        session,
        name=fixture.organization.name,
        slug=f"paybill-{uuid4().hex[:10]}",
    )
    user = await seed_user(session, workos_user_id=f"paybill_{uuid4().hex[:10]}")
    await session.commit()

    await _bind(session, org.id, user.id)

    office_ids: dict[str, UUID] = {}
    for office in fixture.organization.offices:
        row = Office(
            organization_id=org.id,
            name=office.name,
            jurisdiction=office.jurisdiction,
        )
        session.add(row)
        await session.flush()
        office_ids[office.fixture_id] = row.id

    post = Post(
        organization_id=org.id,
        designation="Synthetic Clerk",
        class_="III",
    )
    session.add(post)
    await session.flush()

    component_ids: dict[str, UUID] = {}
    display_order = 0
    for comp in fixture.components:
        display_order += 1
        api_cls = comp.api_classification
        if api_cls is None:
            assert comp.code == "FOREGONE_HRA"
            continue
        db_cls = _CLASSIFICATION_DB[comp.fixture_classification]
        component = PayComponent(
            organization_id=org.id,
            code=comp.code,
            name=comp.name,
            classification=db_cls,
            display_order=display_order,
            employer_transfer=comp.employer_transfer,
            transfer_of=comp.transfer_of,
        )
        session.add(component)
        await session.flush()
        component_ids[comp.code] = component.id

        if comp.code in RECURRING_COMPONENT_CODES or comp.code == BASIC_CODE:
            await versioning.insert_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                effective_from=EFFECTIVE_FROM,
                values={
                    "calc_kind": "fixed_recurring_amount",
                    "amount": Decimal("0.00"),
                    "rate": None,
                    "basis": None,
                    "rounding_rule": "ROUND_HALF_UP_RUPEE",
                },
                change_reason=None,
                created_by=user.id,
            )

    employee_ids: dict[str, UUID] = {}
    for emp in fixture.employees:
        employee_id = await _seed_one_employee(
            session,
            org_id=org.id,
            user_id=user.id,
            employee=emp,
            office_ids=office_ids,
            post_id=post.id,
            component_ids=component_ids,
        )
        employee_ids[emp.fixture_id] = employee_id

    period = PayrollPeriod(
        organization_id=org.id,
        period_year=PERIOD_YEAR,
        period_month=PERIOD_MONTH,
        status="open",
    )
    session.add(period)
    await session.flush()
    run = PayrollRun(
        organization_id=org.id,
        period_id=period.id,
        status="draft",
    )
    session.add(run)
    await session.flush()
    session.add_all(
        initialize_run_roster(
            organization_id=org.id,
            run=run,
            employee_ids=list(employee_ids.values()),
            period_year=period.period_year,
            period_month=period.period_month,
        )
    )
    await session.commit()

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
            reason="June golden approve",
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

    return {
        "org_id": org.id,
        "org_name": org.name,
        "user_id": user.id,
        "run_id": run.id,
        "version_id": UUID(str(calc["version_id"])),
        "employee_ids": employee_ids,
        "expected": fixture.expected.aggregates,
        "engine_version": calc.get("engine_version") or "0.1.0",
    }


async def _seed_one_employee(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    employee: EmployeeSeed,
    office_ids: dict[str, UUID],
    post_id: UUID,
    component_ids: dict[str, UUID],
) -> UUID:
    basic = line_amount(employee, BASIC_CODE)
    assert basic is not None, f"{employee.fixture_id} missing BASIC"
    regime, gpf_jurisdiction = map_regime(employee.regime)

    header = Employee(organization_id=org_id, employee_number=employee.fixture_id)
    session.add(header)
    await session.flush()

    profile_values: dict = {
        "name": employee.name,
        "sevarth_id": employee.sevarth_id,
        "pan": employee.pan,
        "date_of_birth": date(1985, 1, 15),
        "date_of_joining": date(2010, 6, 1),
        "retirement_regime": regime,
        "gpf_jurisdiction": gpf_jurisdiction,
        "pran": None,
        "gpf_account_number": None,
        "epf_number": None,
        "pension_account": None,
    }
    if regime == "gpf":
        profile_values["gpf_account_number"] = employee.gpf_account
        if employee.pran:
            profile_values["pran"] = employee.pran
    elif regime == "nps":
        profile_values["pran"] = employee.pran or f"9000{employee.fixture_id[-4:].zfill(8)}"
    elif regime == "epf":
        profile_values["epf_number"] = employee.epf_number or f"SYNTEPF/{employee.fixture_id}/UAN"

    await versioning.insert_version(
        session,
        employee_profile_versions,
        organization_id=org_id,
        header_id=header.id,
        effective_from=EFFECTIVE_FROM,
        values=profile_values,
        change_reason=None,
        created_by=user_id,
    )
    await versioning.insert_version(
        session,
        employee_posting_versions,
        organization_id=org_id,
        header_id=header.id,
        effective_from=EFFECTIVE_FROM,
        values={
            "office_id": office_ids[employee.office_id],
            "post_id": post_id,
        },
        change_reason=None,
        created_by=user_id,
    )
    await versioning.insert_version(
        session,
        employee_pay_versions,
        organization_id=org_id,
        header_id=header.id,
        effective_from=EFFECTIVE_FROM,
        values={"pay_matrix_level": "L10", "basic_pay": money(basic).quantize(_TWO)},
        change_reason=None,
        created_by=user_id,
    )

    for line in employee.lines:
        code = line.component_code
        if code == BASIC_CODE:
            continue
        if code in RECURRING_COMPONENT_CODES:
            instruction = RecurringInstruction(
                organization_id=org_id,
                employee_id=header.id,
                component_id=component_ids[code],
            )
            session.add(instruction)
            await session.flush()
            await versioning.insert_version(
                session,
                recurring_instruction_versions,
                organization_id=org_id,
                header_id=instruction.id,
                effective_from=EFFECTIVE_FROM,
                values={
                    "amount": money(line.amount).quantize(_TWO),
                    "rate": None,
                    "reason": f"June fixture {code}",
                },
                change_reason=None,
                created_by=user_id,
            )
            continue
        if code in ADVANCE_COMPONENT_CODES:
            principal = max(line.amount * Decimal("24"), line.amount)
            advance = AdvanceAccount(
                organization_id=org_id,
                employee_id=header.id,
                advance_type="hba",
                principal=money(principal).quantize(_TWO),
                sanctioned_on=EFFECTIVE_FROM,
                reference=f"HBA-{employee.fixture_id}",
            )
            session.add(advance)
            await session.flush()
            await versioning.insert_version(
                session,
                advance_installment_versions,
                organization_id=org_id,
                header_id=advance.id,
                effective_from=EFFECTIVE_FROM,
                values={
                    "installment_amount": money(line.amount).quantize(_TWO),
                    "installments_total": 24,
                    "installments_recovered_opening": 0,
                },
                change_reason=None,
                created_by=user_id,
            )
            continue
        if code == "ACCOMMODATION_LICENSE_FEE":
            assert employee.accommodation is not None
            foregone = line_amount(employee, "FOREGONE_HRA")
            assignment = AccommodationAssignment(
                organization_id=org_id,
                employee_id=header.id,
                quarters_location=map_quarters_location(employee.accommodation.location),
                quarters_identifier=f"Q-{employee.fixture_id}",
            )
            session.add(assignment)
            await session.flush()
            await versioning.insert_version(
                session,
                accommodation_charge_versions,
                organization_id=org_id,
                header_id=assignment.id,
                effective_from=EFFECTIVE_FROM,
                values={
                    "license_fee": money(line.amount).quantize(_TWO),
                    "informational_hra_foregone": (
                        money(foregone).quantize(_TWO) if foregone is not None else None
                    ),
                },
                change_reason=None,
                created_by=user_id,
            )
            continue
        if code in ACCOMMODATION_COMPONENT_CODES:
            continue
        raise AssertionError(f"No seeding strategy for {employee.fixture_id} line {code}")

    return header.id


async def _june_world(session: AsyncSession) -> dict:
    global _CACHED_WORLD
    # Re-seed when the cached org was truncated away (singleton-org isolation).
    if _CACHED_WORLD is not None:
        await _bind(session, _CACHED_WORLD["org_id"], _CACHED_WORLD["user_id"])
        org = await session.get(Organization, _CACHED_WORLD["org_id"])
        if org is not None:
            return _CACHED_WORLD
        _CACHED_WORLD = None
    _CACHED_WORLD = await _seed_posted_june(session)
    return _CACHED_WORLD


def _ctx(
    world: dict,
    *,
    run_id: UUID | None = None,
    template_version: str = TEMPLATE_VERSION,
) -> ReportContext:
    return ReportContext(
        organization_id=world["org_id"],
        posted_run_id=run_id or world["run_id"],
        template_version=template_version,
        generated_at=datetime.now(UTC),
        engine_version=str(world["engine_version"]),
    )


def _section_by_title(dto, title: str):
    for section in dto.sections:
        if section.title == title:
            return section
    raise AssertionError(f"section {title!r} not found")


def _col_index(section, key: str) -> int:
    for idx, col in enumerate(section.columns):
        if col.key == key:
            return idx
    raise AssertionError(f"column {key!r} not found")


@pytest.mark.asyncio
async def test_pay_bill_footer_totals_and_headcount(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await pay_bill_builder.build(session, _ctx(world))

    assert dto.report_type == REPORT_TYPE_PAY_BILL
    register = _section_by_title(dto, "Register")
    assert len(register.rows) == 32
    assert register.totals is not None

    earnings_idx = _col_index(register, "earnings_total")
    deductions_idx = _col_index(register, "deductions_total")
    net_idx = _col_index(register, "net_payable")

    assert _dec(register.totals[earnings_idx]) == _dec("5073200.00")
    assert _dec(register.totals[deductions_idx]) == _dec("1264890.00")
    assert _dec(register.totals[net_idx]) == _dec("3838095.00")

    # Cross-check expected_totals.json aggregates.
    assert _dec(world["expected"]["salary_earnings"]) == _dec("5073200")
    assert _dec(world["expected"]["total_deductions"]) == _dec("1264890")
    assert _dec(world["expected"]["net_payable"]) == _dec("3838095")

    employee_numbers = [row[0] for row in register.rows]
    assert len(employee_numbers) == len(set(employee_numbers)) == 32


@pytest.mark.asyncio
async def test_pay_bill_rows_reconcile_to_db_results(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await pay_bill_builder.build(session, _ctx(world))
    register = _section_by_title(dto, "Register")

    db_rows = (
        (
            await session.execute(
                sa.select(payroll_employee_results).where(
                    payroll_employee_results.c.organization_id == world["org_id"],
                    payroll_employee_results.c.run_version_id == world["version_id"],
                )
            )
        )
        .mappings()
        .all()
    )
    by_number = {row["employee_number"]: row for row in db_rows}
    assert len(by_number) == 32

    earnings_idx = _col_index(register, "earnings_total")
    deductions_idx = _col_index(register, "deductions_total")
    net_idx = _col_index(register, "net_payable")

    for row in register.rows:
        emp_no = row[0]
        db = by_number[emp_no]
        assert _dec(row[earnings_idx]) == _dec(db["earnings_total"])
        assert _dec(row[deductions_idx]) == _dec(db["deductions_total"])
        assert _dec(row[net_idx]) == _dec(db["net_payable"])

        # Component columns reconcile to result lines.
        line_rows = (
            (
                await session.execute(
                    sa.select(payroll_result_lines).where(
                        payroll_result_lines.c.organization_id == world["org_id"],
                        payroll_result_lines.c.employee_result_id == db["id"],
                    )
                )
            )
            .mappings()
            .all()
        )
        amounts: dict[str, Decimal] = {}
        for line in line_rows:
            code = line["component_code"]
            if code == "FOREGONE_HRA":
                continue
            amounts[code] = amounts.get(code, _ZERO) + _dec(line["amount"])

        assert _dec(row[_col_index(register, "basic")]) == amounts.get("BASIC", _ZERO)
        assert _dec(row[_col_index(register, "gpf")]) == amounts.get("GPF_SUBSCRIPTION", _ZERO)
        assert _dec(row[_col_index(register, "pt")]) == amounts.get("PROFESSIONAL_TAX", _ZERO)
        assert _dec(row[_col_index(register, "hba")]) == amounts.get("HBA_INSTALLMENT", _ZERO)
        assert _dec(row[_col_index(register, "accommodation")]) == amounts.get(
            "ACCOMMODATION_LICENSE_FEE", _ZERO
        )
        transfers = amounts.get("NPS_EMPLOYER_TRANSFER", _ZERO) + amounts.get(
            "EPF_EMPLOYER_TRANSFER", _ZERO
        )
        assert _dec(row[_col_index(register, "transfers")]) == transfers


@pytest.mark.asyncio
async def test_pay_bill_v2_dynamic_columns_reconcile_and_excel_uses_formulas(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await pay_bill_builder.build(session, _ctx(world, template_version="v2"))
    register = _section_by_title(dto, "Register")

    keys = [column.key for column in register.columns]
    assert len(keys) == len(set(keys))
    assert "component:EPF_EMPLOYER" in keys
    assert "pan" in keys
    assert "gpf_account_number" in keys
    assert register.formulas

    earning_keys = [
        column.key
        for column in register.columns
        if column.key.startswith("component:")
        and column.key
        in {
            "component:BASIC",
            "component:DA",
            "component:HRA",
            "component:TRANSPORT",
            "component:OTHER_ALLOWANCE",
        }
    ]
    for row in register.rows:
        visible_earnings = sum(
            (row[_col_index(register, key)] for key in earning_keys),
            _ZERO,
        )
        assert _dec(visible_earnings) == _dec(row[_col_index(register, "earnings_total")])
        assert _dec(row[_col_index(register, "gross_bill")]) - _dec(
            row[_col_index(register, "deductions_total")]
        ) == _dec(row[_col_index(register, "net_payable")])

    workbook = load_workbook(BytesIO(pay_bill_to_excel(dto)), data_only=False)
    sheet = workbook["Register"]
    header_to_col = {sheet.cell(5, col).value: col for col in range(1, sheet.max_column + 1)}
    first_data_row = 6
    assert str(sheet.cell(first_data_row, header_to_col["Earnings Total"]).value).startswith("=")
    assert str(sheet.cell(first_data_row, header_to_col["Gross Bill"]).value).startswith("=")
    assert str(sheet.cell(first_data_row, header_to_col["Net Payable"]).value).startswith("=")


@pytest.mark.asyncio
async def test_pay_bill_amount_in_words_matches_numeric(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await pay_bill_builder.build(session, _ctx(world))
    register = _section_by_title(dto, "Register")
    words_section = _section_by_title(dto, "Amount in words")
    net = _dec(register.totals[_col_index(register, "net_payable")])
    assert words_section.rows[0][1] == amount_in_words(net)


@pytest.mark.asyncio
async def test_treasury_face_totals_and_reconciliation(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await treasury_face_builder.build(session, _ctx(world))

    assert dto.report_type == REPORT_TYPE_TREASURY_FACE
    summary = _section_by_title(dto, "Treasury Face Summary")
    by_label = {row[0]: _dec(row[1]) for row in summary.rows}

    assert by_label["Gross bill"] == _dec("5102985.00")
    assert by_label["Employer share"] == _dec("29785.00")
    assert by_label["Total deductions"] == _dec("1264890.00")
    assert by_label["Net payable"] == _dec("3838095.00")

    assert by_label["Gross bill"] - by_label["Total deductions"] == by_label["Net payable"]
    assert (
        by_label["AG deductions"]
        + by_label["Treasury deductions"]
        + by_label["External recoveries"]
        == by_label["Total deductions"]
    )

    words = _section_by_title(dto, "Amount in words")
    words_by_label = {row[0]: row[1] for row in words.rows}
    assert words_by_label["Gross bill"] == amount_in_words(by_label["Gross bill"])
    assert words_by_label["Net payable"] == amount_in_words(by_label["Net payable"])


async def _seed_minimal_posted_run_with_gross_adjustment(session: AsyncSession) -> dict:
    """Minimal posted run: one employee with earning + gross_adjustment + deduction.

    Inserted directly (posting-shaped rows) to prove Treasury Face includes
    gross_adjustment lines in Gross bill — the June fixture has none.
    """
    org = await seed_organization(session, name="Gross Adj Org", slug=f"ga-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"ga_{uuid4().hex[:10]}")
    await session.commit()
    await _bind(session, org.id, user.id)

    employee = Employee(organization_id=org.id, employee_number="GA-01")
    session.add(employee)
    period = PayrollPeriod(
        organization_id=org.id,
        period_year=PERIOD_YEAR,
        period_month=PERIOD_MONTH,
        status="open",
    )
    session.add(period)
    await session.flush()
    run = PayrollRun(organization_id=org.id, period_id=period.id, status="posted")
    session.add(run)
    await session.flush()

    version_id = (
        await session.execute(
            sa.insert(payroll_run_versions)
            .values(
                organization_id=org.id,
                run_id=run.id,
                version_number=1,
                engine_version="0.1.0",
                content_hash="ga-test-hash",
                calculated_at=datetime.now(UTC),
                calculated_by=user.id,
                inputs_snapshot={},
                totals={
                    "earnings_total": "1000.00",
                    "employer_contribution_total": "0.00",
                    "gross_adjustment_total": "50.00",
                    "gross_total": "1050.00",
                    "deductions_total": "100.00",
                    "net_payable": "950.00",
                    "offbill_employer_remittance": "0.00",
                    "disbursement": "950.00",
                },
            )
            .returning(payroll_run_versions.c.id)
        )
    ).scalar_one()
    run.current_version_id = version_id

    result_id = (
        await session.execute(
            sa.insert(payroll_employee_results)
            .values(
                organization_id=org.id,
                run_version_id=version_id,
                employee_id=employee.id,
                employee_number="GA-01",
                earnings_total=Decimal("1000.00"),
                employer_contribution_total=Decimal("0.00"),
                gross_total=Decimal("1050.00"),
                deductions_total=Decimal("100.00"),
                net_payable=Decimal("950.00"),
                offbill_employer_remittance=Decimal("0.00"),
                disbursement=Decimal("950.00"),
            )
            .returning(payroll_employee_results.c.id)
        )
    ).scalar_one()

    lines = (
        ("BASIC", "earning", "earning", Decimal("1000.00"), 1),
        ("DA_DIFFERENCE", "gross_adjustment", "gross_adjustment", Decimal("50.00"), 2),
        ("INCOME_TAX", "treasury_deduction", "treasury_deduction", Decimal("100.00"), 3),
    )
    for code, db_class, trace_class, amount, sequence in lines:
        await session.execute(
            sa.insert(payroll_result_lines).values(
                organization_id=org.id,
                employee_result_id=result_id,
                component_code=code,
                classification=db_class,
                calc_kind="fixed_recurring_amount",
                amount=amount,
                sequence=sequence,
                trace={"classification": trace_class},
            )
        )
    await session.commit()
    return {"org_id": org.id, "user_id": user.id, "run_id": run.id, "engine_version": "0.1.0"}


@pytest.mark.asyncio
async def test_treasury_face_includes_gross_adjustment_in_gross_bill(session):
    """Regression: gross_adjustment lines must be part of Gross bill so that
    gross − deductions = posted net payable (engine identity, ADR 0007)."""
    world = await _seed_minimal_posted_run_with_gross_adjustment(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await treasury_face_builder.build(session, _ctx(world))

    summary = _section_by_title(dto, "Treasury Face Summary")
    by_label = {row[0]: _dec(row[1]) for row in summary.rows}
    assert by_label["Gross bill"] == _dec("1050.00")
    assert by_label["Gross adjustments (in gross bill)"] == _dec("50.00")
    assert by_label["Total deductions"] == _dec("100.00")
    assert by_label["Net payable"] == _dec("950.00")
    assert by_label["Gross bill"] - by_label["Total deductions"] == by_label["Net payable"]


@pytest.mark.asyncio
async def test_treasury_face_signatories_from_report_configurations(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])

    # Absent → empty section.
    dto_empty = await treasury_face_builder.build(session, _ctx(world))
    assert _section_by_title(dto_empty, "Signatories").rows == ()

    session.add(
        ReportConfiguration(
            organization_id=world["org_id"],
            key="signatories",
            value={"chair": "Director", "dda": "Deputy Director"},
        )
    )
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    dto = await treasury_face_builder.build(session, _ctx(world))
    signatories = _section_by_title(dto, "Signatories")
    assert ("chair", "Director") in signatories.rows
    assert ("dda", "Deputy Director") in signatories.rows

    # Clean up so later tests on the cached world see an empty section again.
    await session.execute(
        sa.delete(ReportConfiguration).where(
            ReportConfiguration.organization_id == world["org_id"],
            ReportConfiguration.key == "signatories",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_pay_bill_excel_and_pdf_formatters(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await pay_bill_builder.build(session, _ctx(world))

    payload = pay_bill_to_json(dto)
    assert payload["report_type"] == REPORT_TYPE_PAY_BILL
    assert payload["sections"][0]["totals"]["net_payable"] == "3838095.00"

    xlsx = pay_bill_to_excel(dto)
    wb = load_workbook(BytesIO(xlsx))
    ws = wb.active
    assert ws is not None
    # Header row 5; first money column after employee_number/name/designation is BASIC (col 4).
    money_cell = ws.cell(row=6, column=4)
    assert money_cell.number_format == MONEY_FORMAT
    # Footer net payable cell: find last data+totals row, last column.
    register = _section_by_title(dto, "Register")
    totals_excel_row = 6 + len(register.rows)
    net_col = len(register.columns)
    net_cell = ws.cell(row=totals_excel_row, column=net_col)
    assert net_cell.number_format == MONEY_FORMAT
    assert _dec(net_cell.value) == _dec("3838095.00")

    pdf = pay_bill_to_pdf(dto)
    assert pdf.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert "Payroll Register — Pay Bill" in text or "Payroll Register" in text
    assert "38,38,095.00" in text


@pytest.mark.asyncio
async def test_treasury_face_excel_and_pdf_formatters(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])
    dto = await treasury_face_builder.build(session, _ctx(world))

    payload = treasury_face_to_json(dto)
    assert payload["report_type"] == REPORT_TYPE_TREASURY_FACE

    xlsx = treasury_face_to_excel(dto)
    wb = load_workbook(BytesIO(xlsx))
    ws = wb.active
    assert ws is not None
    # First money cell in summary (Gross bill amount).
    money_cell = ws.cell(row=6, column=2)
    assert money_cell.number_format == MONEY_FORMAT
    assert _dec(money_cell.value) == _dec("5102985.00")

    pdf = treasury_face_to_pdf(dto)
    assert pdf.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert "Treasury Face" in text
    assert "38,38,095.00" in text


@pytest.mark.asyncio
async def test_unposted_run_raises_conflict(session):
    world = await _june_world(session)
    await _bind(session, world["org_id"], world["user_id"])

    period = PayrollPeriod(
        organization_id=world["org_id"],
        period_year=2026,
        period_month=7,
        status="open",
    )
    session.add(period)
    await session.flush()
    draft = PayrollRun(
        organization_id=world["org_id"],
        period_id=period.id,
        status="draft",
    )
    session.add(draft)
    await session.flush()
    draft_id = draft.id
    await session.commit()

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="must be posted"):
        await pay_bill_builder.build(session, _ctx(world, run_id=draft_id))

    await _bind(session, world["org_id"], world["user_id"])
    with pytest.raises(ConflictError, match="must be posted"):
        await treasury_face_builder.build(session, _ctx(world, run_id=draft_id))
