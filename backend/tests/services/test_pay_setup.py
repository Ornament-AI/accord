"""Unit/integration tests for pay-setup versioning helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from pydantic import ValidationError as PydanticValidationError

from app.exceptions import ConflictError, ValidationError
from app.models.pay_components import PayComponent, component_rate_versions
from app.schemas.pay_setup import ComponentRateVersionCreate
from app.services.versioning import insert_version, terminate_open_version
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


def _rate_payload(*, calc_kind: str = "fixed_recurring_amount", amount: str = "1000.00") -> dict:
    return {
        "calc_kind": calc_kind,
        "rounding_rule": "ROUND_HALF_UP_RUPEE",
        "amount": Decimal(amount),
        "rate": None,
        "basis": None,
    }


@pytest.mark.asyncio
async def test_insert_version_clip_and_insert_happy_path(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="BASIC",
            name="Basic Pay",
            classification="earning",
        )
        session.add(component)
        await session.flush()
        header_id = component.id

        first = await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=header_id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )
        second = await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=header_id,
            effective_from=date(2026, 4, 1),
            created_by=user.id,
            values=_rate_payload(amount="1200.00"),
            change_reason=None,
        )

    stmt = (
        sa.select(component_rate_versions)
        .where(component_rate_versions.c.header_id == header_id)
        .order_by(sa.func.lower(component_rate_versions.c.validity))
    )
    rows = (await session.execute(stmt)).mappings().all()
    assert len(rows) == 2

    first_from = rows[0]["validity"].lower
    first_to = rows[0]["validity"].upper
    assert first_from == date(2026, 1, 1)
    assert first_to == date(2026, 4, 1)
    assert rows[0]["id"] == first["id"]

    second_from = rows[1]["validity"].lower
    second_to = rows[1]["validity"].upper
    assert second_from == date(2026, 4, 1)
    assert second_to is None or not hasattr(second_to, "year")
    assert rows[1]["id"] == second["id"]


@pytest.mark.asyncio
async def test_insert_version_conflict_when_effective_from_not_after_open_lower(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="DA",
            name="Dearness Allowance",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )

        with pytest.raises(ConflictError, match="effective_from must be after"):
            await insert_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                effective_from=date(2026, 1, 1),
                created_by=user.id,
                values=_rate_payload(amount="1100.00"),
                change_reason=None,
            )


@pytest.mark.asyncio
async def test_terminate_open_version_clips_without_insert(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="HRA",
            name="House Rent Allowance",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )
        terminated = await terminate_open_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            end_on=date(2026, 6, 1),
        )

    upper = terminated["validity"].upper
    assert upper == date(2026, 6, 1)

    header_id = terminated["header_id"]
    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(component_rate_versions)
        .where(component_rate_versions.c.header_id == header_id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_terminate_open_version_conflict_when_no_open_version(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="TA",
            name="Transport Allowance",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        with pytest.raises(ConflictError, match="No open version exists"):
            await terminate_open_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                end_on=date(2026, 6, 1),
            )


@pytest.mark.asyncio
async def test_terminate_open_version_validation_when_end_on_not_after_start(session):
    org = await seed_organization(session)
    user = await seed_user(session)
    await session.commit()

    async with session.begin():
        await bind_tenant_context(session, organization_id=org.id, user_id=user.id)
        component = PayComponent(
            organization_id=org.id,
            code="MED",
            name="Medical",
            classification="earning",
        )
        session.add(component)
        await session.flush()

        await insert_version(
            session,
            component_rate_versions,
            organization_id=org.id,
            header_id=component.id,
            effective_from=date(2026, 1, 1),
            created_by=user.id,
            values=_rate_payload(),
            change_reason=None,
        )

        with pytest.raises(ValidationError, match="end_on must be after"):
            await terminate_open_version(
                session,
                component_rate_versions,
                organization_id=org.id,
                header_id=component.id,
                end_on=date(2026, 1, 1),
            )


def test_component_rate_version_create_rejects_non_string_money():
    with pytest.raises(PydanticValidationError):
        ComponentRateVersionCreate.model_validate(
            {
                "effective_from": "2026-01-01",
                "calc_kind": "fixed_recurring_amount",
                "rounding_rule": "ROUND_HALF_UP_RUPEE",
                "amount": 1000.00,
            }
        )
