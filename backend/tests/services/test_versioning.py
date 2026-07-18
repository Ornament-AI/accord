"""DB-backed tests for app.services.versioning clip-and-insert helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.models.employees import Employee, employee_pay_versions
from app.services.versioning import get_active_version, insert_version, list_versions
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


async def _seed_header(session: AsyncSession) -> tuple[Employee, object]:
    org = await seed_organization(session, name="Versioning Org", slug=f"ver-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"ver_{uuid4().hex[:10]}")
    employee = Employee(organization_id=org.id, employee_number=f"E-{uuid4().hex[:8]}")
    session.add(employee)
    await session.commit()
    return employee, user


async def _bind(session: AsyncSession, employee: Employee, user) -> None:
    if not session.in_transaction():
        await session.begin()
    await bind_tenant_context(session, organization_id=employee.organization_id, user_id=user.id)


@pytest.mark.asyncio
async def test_first_insert_creates_open_ended_version(session, clean_identity_tables):
    employee, user = await _seed_header(session)
    await _bind(session, employee, user)

    row = await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={"pay_matrix_level": "L10", "basic_pay": Decimal("50000.00")},
        change_reason="hire",
        created_by=user.id,
    )
    await session.commit()

    assert row["pay_matrix_level"] == "L10"
    assert row["basic_pay"] == Decimal("50000.00")
    validity = row["validity"]
    assert validity.lower == date(2026, 1, 1)
    assert validity.upper is None

    await _bind(session, employee, user)
    active = await get_active_version(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
        on_date=date(2026, 6, 1),
    )
    assert active is not None
    assert active["id"] == row["id"]


@pytest.mark.asyncio
async def test_second_insert_clips_open_version(session, clean_identity_tables):
    employee, user = await _seed_header(session)
    await _bind(session, employee, user)

    first = await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={"pay_matrix_level": "L10", "basic_pay": Decimal("50000.00")},
        change_reason=None,
        created_by=user.id,
    )
    second = await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 4, 1),
        values={"pay_matrix_level": "L11", "basic_pay": Decimal("55000.00")},
        change_reason="increment",
        created_by=user.id,
    )
    await session.commit()

    await _bind(session, employee, user)
    rows = (
        (
            await session.execute(
                sa.select(employee_pay_versions)
                .where(employee_pay_versions.c.header_id == employee.id)
                .order_by(sa.func.lower(employee_pay_versions.c.validity))
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 2
    assert rows[0]["id"] == first["id"]
    assert rows[0]["validity"].lower == date(2026, 1, 1)
    assert rows[0]["validity"].upper == date(2026, 4, 1)
    assert rows[1]["id"] == second["id"]
    assert rows[1]["validity"].lower == date(2026, 4, 1)
    assert rows[1]["validity"].upper is None


@pytest.mark.asyncio
async def test_effective_from_not_after_open_start_conflicts(session, clean_identity_tables):
    employee, user = await _seed_header(session)
    await _bind(session, employee, user)
    await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={"pay_matrix_level": "L10", "basic_pay": Decimal("50000.00")},
        change_reason=None,
        created_by=user.id,
    )
    await session.commit()

    await _bind(session, employee, user)
    with pytest.raises(ConflictError, match="effective_from must be after"):
        await insert_version(
            session,
            employee_pay_versions,
            organization_id=employee.organization_id,
            header_id=employee.id,
            effective_from=date(2026, 1, 1),
            values={"pay_matrix_level": "L11", "basic_pay": Decimal("51000.00")},
            change_reason=None,
            created_by=user.id,
        )


@pytest.mark.asyncio
async def test_effective_from_inside_closed_historical_conflicts(session, clean_identity_tables):
    employee, user = await _seed_header(session)
    await _bind(session, employee, user)
    await session.execute(
        sa.insert(employee_pay_versions).values(
            organization_id=employee.organization_id,
            header_id=employee.id,
            validity=Range(date(2026, 1, 1), date(2026, 6, 1), bounds="[)"),
            pay_matrix_level="L10",
            basic_pay=Decimal("50000.00"),
            created_by=user.id,
            change_reason="seed",
        )
    )
    await session.commit()

    await _bind(session, employee, user)
    with pytest.raises(ConflictError, match="overlaps an existing historical version"):
        await insert_version(
            session,
            employee_pay_versions,
            organization_id=employee.organization_id,
            header_id=employee.id,
            effective_from=date(2026, 3, 1),
            values={"pay_matrix_level": "L11", "basic_pay": Decimal("51000.00")},
            change_reason=None,
            created_by=user.id,
        )


@pytest.mark.asyncio
async def test_get_active_version_boundary_dates(session, clean_identity_tables):
    employee, user = await _seed_header(session)
    await _bind(session, employee, user)
    await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={"pay_matrix_level": "L10", "basic_pay": Decimal("50000.00")},
        change_reason=None,
        created_by=user.id,
    )
    await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 4, 1),
        values={"pay_matrix_level": "L11", "basic_pay": Decimal("55000.00")},
        change_reason=None,
        created_by=user.id,
    )
    await session.commit()

    await _bind(session, employee, user)
    before = await get_active_version(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
        on_date=date(2026, 3, 31),
    )
    on_boundary = await get_active_version(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
        on_date=date(2026, 4, 1),
    )
    after = await get_active_version(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
        on_date=date(2026, 4, 2),
    )
    assert before is not None and before["pay_matrix_level"] == "L10"
    assert on_boundary is not None and on_boundary["pay_matrix_level"] == "L11"
    assert after is not None and after["pay_matrix_level"] == "L11"

    too_early = await get_active_version(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
        on_date=date(2025, 12, 31),
    )
    assert too_early is None


@pytest.mark.asyncio
async def test_list_versions_order_newest_first_by_default(session, clean_identity_tables):
    employee, user = await _seed_header(session)
    await _bind(session, employee, user)
    await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values={"pay_matrix_level": "L10", "basic_pay": Decimal("50000.00")},
        change_reason=None,
        created_by=user.id,
    )
    await insert_version(
        session,
        employee_pay_versions,
        organization_id=employee.organization_id,
        header_id=employee.id,
        effective_from=date(2026, 4, 1),
        values={"pay_matrix_level": "L11", "basic_pay": Decimal("55000.00")},
        change_reason=None,
        created_by=user.id,
    )
    await session.commit()

    await _bind(session, employee, user)
    newest_first = await list_versions(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
    )
    oldest_first = await list_versions(
        session,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=employee.organization_id,
        order="asc",
    )
    assert [r["pay_matrix_level"] for r in newest_first] == ["L11", "L10"]
    assert [r["pay_matrix_level"] for r in oldest_first] == ["L10", "L11"]
