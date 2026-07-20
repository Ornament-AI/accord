"""ORM smoke tests for Phase 4 payroll run persistence tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import select as sqlmodel_select

from app.models.employees import Employee
from app.models.identity import Organization
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunInput,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from tests.migrations.conftest import diag, ensure_accord_roles, run_alembic


@pytest.mark.asyncio
async def test_payroll_run_orm_roundtrip(scratch_db: str) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    org_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    created_by = uuid.uuid4()
    version_id = uuid.uuid4()
    result_id = uuid.uuid4()
    line_one_id = uuid.uuid4()
    line_two_id = uuid.uuid4()
    calculated_at = datetime.now(timezone.utc)

    inputs_snapshot = {
        "run": {"id": "run-1"},
        "employees": [{"id": "emp-1", "overrides": [{"code": "BASIC", "amount": "100"}]}],
    }
    totals = {
        "earnings": "1234.56",
        "deductions": "100.00",
        "net": "1134.56",
        "nested": {"count": 2},
    }
    trace_one = {
        "component": "BASIC",
        "basis": "1000.00",
        "rate": "99.1234",
        "rounded_value": "1234.56",
    }
    trace_two = {
        "component": "HRA",
        "basis": "500.00",
        "rounded_value": "500.00",
    }

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            org = Organization(
                id=org_id,
                name="Payroll Org",
                slug=f"payroll-org-{uuid.uuid4().hex[:8]}",
            )
            session.add(org)
            await session.flush()

            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )

            employee = Employee(
                id=employee_id,
                organization_id=org_id,
                employee_number="E-100",
            )
            session.add(employee)

            period = PayrollPeriod(
                organization_id=org_id,
                period_year=2026,
                period_month=7,
                status="open",
            )
            session.add(period)
            await session.flush()

            run = PayrollRun(
                organization_id=org_id,
                period_id=period.id,
                status="draft",
            )
            session.add(run)
            await session.flush()
            assert run.lock_version == 0

            run_input = PayrollRunInput(
                organization_id=org_id,
                run_id=run.id,
                employee_id=employee_id,
                component_code="BASIC",
                input_kind="exception",
                amount=Decimal("1234.56"),
                rate=Decimal("99.1234"),
                reason="Test exception",
                created_by=created_by,
            )
            session.add(run_input)
            await session.flush()
            assert run_input.version == 0

            await session.execute(
                insert(payroll_run_versions).values(
                    id=version_id,
                    organization_id=org_id,
                    run_id=run.id,
                    version_number=1,
                    engine_version="engine-1.0",
                    content_hash="abc123",
                    calculated_at=calculated_at,
                    calculated_by=created_by,
                    inputs_snapshot=inputs_snapshot,
                    totals=totals,
                )
            )
            await session.execute(
                insert(payroll_employee_results).values(
                    id=result_id,
                    organization_id=org_id,
                    run_version_id=version_id,
                    employee_id=employee_id,
                    employee_number="E-100",
                    earnings_total=Decimal("1234.56"),
                    employer_contribution_total=Decimal("200.00"),
                    gross_total=Decimal("1434.56"),
                    deductions_total=Decimal("100.00"),
                    net_payable=Decimal("1134.56"),
                    offbill_employer_remittance=Decimal("0.00"),
                    disbursement=Decimal("1134.56"),
                )
            )
            await session.execute(
                insert(payroll_result_lines).values(
                    [
                        {
                            "id": line_one_id,
                            "organization_id": org_id,
                            "employee_result_id": result_id,
                            "component_code": "BASIC",
                            "classification": "earning",
                            "calc_kind": "fixed_recurring_amount",
                            "amount": Decimal("1234.56"),
                            "sequence": 1,
                            "trace": trace_one,
                        },
                        {
                            "id": line_two_id,
                            "organization_id": org_id,
                            "employee_result_id": result_id,
                            "component_code": "HRA",
                            "classification": "earning",
                            "calc_kind": "fixed_recurring_amount",
                            "amount": Decimal("500.00"),
                            "sequence": 2,
                            "trace": trace_two,
                        },
                    ]
                )
            )
            await session.commit()

            period_id = period.id
            run_id = run.id
            run_input_id = run_input.id

        async with session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )

            loaded_period = (
                await session.execute(
                    sqlmodel_select(PayrollPeriod).where(PayrollPeriod.id == period_id)
                )
            ).scalar_one()
            assert loaded_period.period_year == 2026
            assert loaded_period.period_month == 7

            loaded_run = (
                await session.execute(sqlmodel_select(PayrollRun).where(PayrollRun.id == run_id))
            ).scalar_one()
            assert loaded_run.lock_version == 0

            loaded_input = (
                await session.execute(
                    sqlmodel_select(PayrollRunInput).where(PayrollRunInput.id == run_input_id)
                )
            ).scalar_one()
            assert loaded_input.amount == Decimal("1234.56")
            assert loaded_input.rate == Decimal("99.1234")
            assert loaded_input.version == 0

            version_row = (
                await session.execute(
                    select(
                        payroll_run_versions.c.inputs_snapshot,
                        payroll_run_versions.c.totals,
                    ).where(payroll_run_versions.c.id == version_id)
                )
            ).one()
            assert version_row.inputs_snapshot == inputs_snapshot
            assert version_row.totals == totals
            assert version_row.totals["nested"]["count"] == 2

            result_row = (
                await session.execute(
                    select(
                        payroll_employee_results.c.earnings_total,
                        payroll_employee_results.c.net_payable,
                    ).where(payroll_employee_results.c.id == result_id)
                )
            ).one()
            assert result_row.earnings_total == Decimal("1234.56")
            assert result_row.net_payable == Decimal("1134.56")

            line_rows = (
                await session.execute(
                    select(
                        payroll_result_lines.c.amount,
                        payroll_result_lines.c.trace,
                    )
                    .where(payroll_result_lines.c.employee_result_id == result_id)
                    .order_by(payroll_result_lines.c.sequence)
                )
            ).all()
            assert len(line_rows) == 2
            assert line_rows[0].amount == Decimal("1234.56")
            assert line_rows[0].trace == trace_one
            assert line_rows[1].amount == Decimal("500.00")
            assert line_rows[1].trace == trace_two
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_payroll_period_duplicate_org_year_month_raises_integrity_error(
    scratch_db: str,
) -> None:
    ensure_accord_roles()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    org_id = uuid.uuid4()

    engine = create_async_engine(scratch_db, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            org = Organization(
                id=org_id,
                name="Dup Period Org",
                slug=f"dup-period-{uuid.uuid4().hex[:8]}",
            )
            session.add(org)
            await session.flush()

            await session.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )

            session.add(
                PayrollPeriod(
                    organization_id=org_id,
                    period_year=2026,
                    period_month=7,
                    status="open",
                )
            )
            await session.flush()

            session.add(
                PayrollPeriod(
                    organization_id=org_id,
                    period_year=2026,
                    period_month=7,
                    status="open",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
    finally:
        await engine.dispose()
