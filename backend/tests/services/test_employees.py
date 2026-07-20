"""Service-layer tests for employee master data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.org_structure import Office, Post
from app.schemas.employees import (
    BankInput,
    CreateEmployeeRequest,
    PayInput,
    PostingInput,
    ProfileInput,
    RetirementRegime,
    GpfJurisdiction,
    mask_value,
)
from app.services.employees import (
    create_employee,
    create_employee_version,
    get_employee_detail,
    list_employees,
)
from app.tenancy import bind_tenant_context
from tests.identity_helpers import seed_organization, seed_user


async def _world(session: AsyncSession):
    org = await seed_organization(session, name="Emp Svc Org", slug=f"emp-svc-{uuid4().hex[:10]}")
    user = await seed_user(session, workos_user_id=f"emp_svc_{uuid4().hex[:10]}")
    office = Office(
        organization_id=org.id, name="HQ", jurisdiction="mumbai"
    )
    post = Post(organization_id=org.id, designation=f"Clerk-{uuid4().hex[:6]}", class_="III")
    session.add_all([office, post])
    await session.commit()
    return org, user, office, post


async def _bind(session: AsyncSession, org, user) -> None:
    if not session.in_transaction():
        await session.begin()
    await bind_tenant_context(session, organization_id=org.id, user_id=user.id)


def _profile(regime: RetirementRegime = RetirementRegime.GPF, **overrides) -> ProfileInput:
    data = {
        "name": "Alice Example",
        "sevarth_id": f"SEV-{uuid4().hex[:8]}",
        "pan": "ABCDE1234F",
        "date_of_birth": date(1990, 1, 15),
        "date_of_joining": date(2015, 6, 1),
        "retirement_regime": regime,
        "gpf_jurisdiction": GpfJurisdiction.MUMBAI if regime == RetirementRegime.GPF else None,
        "pran": "123456789012",
        "gpf_account_number": "GPF998877",
        "epf_number": None,
        "pension_account": None,
    }
    data.update(overrides)
    return ProfileInput.model_validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "regime,jurisdiction",
    [
        (RetirementRegime.GPF, GpfJurisdiction.MUMBAI),
        (RetirementRegime.NPS, None),
        (RetirementRegime.EPF, None),
    ],
)
async def test_create_employee_all_regimes(session, clean_identity_tables, regime, jurisdiction):
    org, user, office, post = await _world(session)
    await _bind(session, org, user)
    body = CreateEmployeeRequest(
        employee_number=f"E-{uuid4().hex[:6]}",
        effective_from=date(2026, 1, 1),
        profile=_profile(regime, gpf_jurisdiction=jurisdiction),
        posting=PostingInput(
            office_id=office.id,
            post_id=post.id,
        ),
        pay=PayInput(pay_matrix_level="L10", basic_pay=Decimal("50732.00")),
        bank=BankInput(
            account_number="123456789012",
            ifsc="SBIN0001234",
            bank_name="SBI",
            branch="Main",
            is_primary_salary=True,
        ),
    )
    detail = await create_employee(session, organization_id=org.id, created_by=user.id, body=body)
    assert detail.employee_number == body.employee_number
    assert detail.profile is not None
    assert detail.profile.retirement_regime == regime.value
    assert detail.profile.pan == mask_value("ABCDE1234F")
    assert detail.pay is not None
    assert str(detail.pay.basic_pay) == "50732.00" or detail.pay.basic_pay == Decimal("50732.00")
    assert detail.bank is not None
    assert detail.bank.account_number == "••••9012"


@pytest.mark.asyncio
async def test_duplicate_employee_number_conflicts(session, clean_identity_tables):
    org, user, *_ = await _world(session)
    await _bind(session, org, user)
    body = CreateEmployeeRequest(
        employee_number="DUP-001",
        effective_from=date(2026, 1, 1),
        profile=_profile(),
    )
    await create_employee(session, organization_id=org.id, created_by=user.id, body=body)

    await _bind(session, org, user)
    with pytest.raises(ConflictError, match="employee_number"):
        await create_employee(session, organization_id=org.id, created_by=user.id, body=body)


@pytest.mark.asyncio
async def test_unknown_office_fk_not_found(session, clean_identity_tables):
    org, user, _office, post = await _world(session)
    await _bind(session, org, user)
    body = CreateEmployeeRequest(
        employee_number="E-FK",
        effective_from=date(2026, 1, 1),
        profile=_profile(),
        posting=PostingInput(
            office_id=uuid4(),
            post_id=post.id,
        ),
    )
    with pytest.raises(NotFoundError, match="Office"):
        await create_employee(session, organization_id=org.id, created_by=user.id, body=body)


@pytest.mark.asyncio
async def test_list_search_and_pagination(session, clean_identity_tables):
    org, user, *_ = await _world(session)
    await _bind(session, org, user)
    for i, name in enumerate(["Alpha One", "Beta Two", "Alpha Three"], start=1):
        await create_employee(
            session,
            organization_id=org.id,
            created_by=user.id,
            body=CreateEmployeeRequest(
                employee_number=f"PAG-{i:03d}",
                effective_from=date(2026, 1, 1),
                profile=_profile(name=name, sevarth_id=f"SEV-PAG-{i}"),
            ),
        )
        await _bind(session, org, user)

    page1 = await list_employees(
        session,
        organization_id=org.id,
        as_of=date(2026, 1, 1),
        search="Alpha",
        page=1,
        page_size=1,
    )
    assert page1.total == 2
    assert page1.page_size == 1
    assert page1.total_pages == 2
    assert len(page1.items) == 1

    page2 = await list_employees(
        session,
        organization_id=org.id,
        as_of=date(2026, 1, 1),
        search="Alpha",
        page=2,
        page_size=1,
    )
    assert len(page2.items) == 1
    assert {page1.items[0].employee_number, page2.items[0].employee_number} == {
        "PAG-001",
        "PAG-003",
    }


@pytest.mark.asyncio
async def test_bank_primary_overlap_conflict(session, clean_identity_tables):
    org, user, *_ = await _world(session)
    await _bind(session, org, user)
    detail = await create_employee(
        session,
        organization_id=org.id,
        created_by=user.id,
        body=CreateEmployeeRequest(
            employee_number="BANK-1",
            effective_from=date(2026, 1, 1),
            profile=_profile(),
            bank=BankInput(
                account_number="111122223333",
                ifsc="SBIN0001111",
                bank_name="SBI",
                branch="A",
                is_primary_salary=True,
            ),
        ),
    )
    await _bind(session, org, user)
    # Non-primary may coexist; primary overlapping without clip should conflict.
    # Insert a second primary with earlier effective_from into historical range → conflict.
    with pytest.raises(ConflictError):
        await create_employee_version(
            session,
            organization_id=org.id,
            employee_id=detail.id,
            kind="bank",
            created_by=user.id,
            effective_from=date(2026, 1, 1),
            change_reason="bad",
            bank=BankInput(
                account_number="999988887777",
                ifsc="SBIN0002222",
                bank_name="SBI",
                branch="B",
                is_primary_salary=True,
            ),
        )


@pytest.mark.asyncio
async def test_get_detail_as_of_and_masking(session, clean_identity_tables):
    org, user, *_ = await _world(session)
    await _bind(session, org, user)
    created = await create_employee(
        session,
        organization_id=org.id,
        created_by=user.id,
        body=CreateEmployeeRequest(
            employee_number="MASK-1",
            effective_from=date(2026, 1, 1),
            profile=_profile(pan="ABCDE1234F"),
            pay=PayInput(pay_matrix_level="L10", basic_pay=Decimal("1000.00")),
        ),
    )
    await _bind(session, org, user)
    await create_employee_version(
        session,
        organization_id=org.id,
        employee_id=created.id,
        kind="pay",
        created_by=user.id,
        effective_from=date(2026, 7, 1),
        change_reason="raise",
        pay=PayInput(pay_matrix_level="L11", basic_pay=Decimal("1200.00")),
    )

    await _bind(session, org, user)
    before = await get_employee_detail(
        session,
        organization_id=org.id,
        employee_id=created.id,
        as_of=date(2026, 6, 30),
        reveal=False,
    )
    on = await get_employee_detail(
        session,
        organization_id=org.id,
        employee_id=created.id,
        as_of=date(2026, 7, 1),
        reveal=True,
    )
    assert before.pay is not None and before.pay.pay_matrix_level == "L10"
    assert on.pay is not None and on.pay.pay_matrix_level == "L11"
    assert before.profile is not None and before.profile.pan == "••••234F"
    assert on.profile is not None and on.profile.pan == "ABCDE1234F"


def test_mask_value_helper():
    assert mask_value(None) is None
    assert mask_value("1234") == "••••"
    assert mask_value("12") == "••••"
    assert mask_value("12345") == "••••2345"
