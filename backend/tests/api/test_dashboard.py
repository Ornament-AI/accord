"""API tests for GET /api/dashboard payroll summary."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.api.routes.dashboard import router as dashboard_router
from app.main import create_app
from app.models.employees import Employee, employee_profile_versions
from app.models.payroll_runs import PayrollPeriod, PayrollRun, payroll_run_versions
from app.models.platform import ExportArtifact, PayrollApproval
from app.services import versioning
from app.tenancy import bind_tenant_context
from tests.gate_d.conftest import apply_session_cookie, mint_session_cookie
from tests.identity_helpers import seed_membership, seed_organization, seed_user

_ENGINE_VERSION = "test-engine-1.0"


def _dashboard_app():
    application = create_app()
    application.include_router(dashboard_router, prefix="/api")
    application.state.auth_ready = True
    return application


@pytest_asyncio.fixture
async def client(dev_settings):
    application = _dashboard_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_world(session, dev_settings, client, *, slug: str | None = None):
    org = await seed_organization(
        session,
        name="Dashboard API Org",
        slug=slug or f"dash-api-{uuid4().hex[:10]}",
    )
    admin = await seed_user(session, name="Org Admin")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=admin.id,
        role="organization_administrator",
    )
    await session.commit()
    cookie = await mint_session_cookie(
        session,
        dev_settings,
        user_id=admin.id,
        active_organization_id=org.id,
    )
    apply_session_cookie(client, cookie)
    return org, admin


async def _bind(session, org_id: UUID, user_id: UUID) -> None:
    if session.in_transaction():
        await session.rollback()
    await session.begin()
    await bind_tenant_context(session, organization_id=org_id, user_id=user_id)


def _profile_values(regime: str) -> dict:
    values: dict = {
        "name": f"{regime.upper()} Employee",
        "sevarth_id": f"SEV-{uuid4().hex[:8]}",
        "pan": "ABCDE1234F",
        "date_of_birth": date(1990, 1, 15),
        "date_of_joining": date(2015, 6, 1),
        "retirement_regime": regime,
        "gpf_jurisdiction": None,
        "pran": None,
        "gpf_account_number": None,
        "epf_number": None,
        "pension_account": None,
    }
    if regime == "gpf":
        values["gpf_jurisdiction"] = "mumbai"
        values["gpf_account_number"] = f"GPF-{uuid4().hex[:6]}"
    elif regime == "nps":
        values["pran"] = f"9{uuid4().hex[:11]}"
    elif regime == "epf":
        values["epf_number"] = f"EPF-{uuid4().hex[:6]}"
    return values


async def _seed_employee_with_regime(
    session, *, org_id: UUID, user_id: UUID, regime: str, number: str
) -> UUID:
    employee = Employee(organization_id=org_id, employee_number=number)
    session.add(employee)
    await session.flush()
    await versioning.insert_version(
        session,
        employee_profile_versions,
        organization_id=org_id,
        header_id=employee.id,
        effective_from=date(2026, 1, 1),
        values=_profile_values(regime),
        change_reason=None,
        created_by=user_id,
    )
    return employee.id


async def _seed_posted_run(
    session,
    *,
    org_id: UUID,
    user_id: UUID,
    year: int,
    month: int,
    totals: dict[str, str],
    content_hash: str,
    posted_at: datetime,
    status: str = "posted",
) -> UUID:
    period = PayrollPeriod(
        organization_id=org_id,
        period_year=year,
        period_month=month,
        status="open",
    )
    session.add(period)
    await session.flush()

    run = PayrollRun(
        organization_id=org_id,
        period_id=period.id,
        run_type="regular",
        status="draft",
    )
    session.add(run)
    await session.flush()

    version_id = uuid4()
    await session.execute(
        sa.insert(payroll_run_versions).values(
            id=version_id,
            organization_id=org_id,
            run_id=run.id,
            version_number=1,
            engine_version=_ENGINE_VERSION,
            content_hash=content_hash,
            calculated_at=posted_at,
            calculated_by=user_id,
            inputs_snapshot={"employees": []},
            totals=totals,
        )
    )
    run.current_version_id = version_id
    run.status = status
    session.add(
        PayrollApproval(
            organization_id=org_id,
            run_id=run.id,
            run_version_id=version_id,
            content_hash=content_hash,
            action="post",
            actor_user_id=user_id,
            reason="Posted for dashboard test",
            created_at=posted_at,
        )
    )
    await session.flush()
    return run.id


async def _seed_draft_run(
    session, *, org_id: UUID, year: int, month: int, status: str = "draft"
) -> UUID:
    period = PayrollPeriod(
        organization_id=org_id,
        period_year=year,
        period_month=month,
        status="open",
    )
    session.add(period)
    await session.flush()
    run = PayrollRun(
        organization_id=org_id,
        period_id=period.id,
        run_type="regular",
        status=status,
    )
    session.add(run)
    await session.flush()
    return run.id


async def _seed_artifact(
    session,
    *,
    org_id: UUID,
    user_id: UUID,
    report_type: str,
    created_at: datetime,
) -> UUID:
    artifact = ExportArtifact(
        organization_id=org_id,
        report_type=report_type,
        template_version="v1",
        object_key=f"{org_id}/{uuid4()}",
        checksum_sha256="a" * 64,
        content_type="application/pdf",
        size_bytes=12,
        status="finalized",
        requested_by=user_id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(artifact)
    await session.flush()
    return artifact.id


def _empty_dashboard_shape() -> dict:
    return {
        "headcount": {
            "active_employees": 0,
            "by_regime": {"gpf": 0, "nps": 0, "epf": 0},
        },
        "current_period": None,
        "latest_posted": None,
        "previous_posted": None,
        "variance": None,
        "pipeline": {
            "draft": 0,
            "calculated": 0,
            "submitted": 0,
            "approved": 0,
            "posted": 0,
            "rejected": 0,
            "reversed": 0,
        },
        "recent_artifacts": [],
    }


@pytest.mark.asyncio
async def test_dashboard_empty_org(client, session, dev_settings):
    await _admin_world(session, dev_settings, client)

    resp = await client.get("/api/dashboard")
    assert resp.status_code == 200, resp.text
    assert resp.json() == _empty_dashboard_shape()


@pytest.mark.asyncio
async def test_dashboard_seeded_world_headcount_posted_pipeline_variance(
    client, session, dev_settings
):
    org, admin = await _admin_world(session, dev_settings, client)
    await _bind(session, org.id, admin.id)

    await _seed_employee_with_regime(
        session, org_id=org.id, user_id=admin.id, regime="gpf", number="E-GPF-1"
    )
    await _seed_employee_with_regime(
        session, org_id=org.id, user_id=admin.id, regime="gpf", number="E-GPF-2"
    )
    await _seed_employee_with_regime(
        session, org_id=org.id, user_id=admin.id, regime="nps", number="E-NPS-1"
    )
    await _seed_employee_with_regime(
        session, org_id=org.id, user_id=admin.id, regime="epf", number="E-EPF-1"
    )

    may_totals = {
        "earnings_total": "100000.00",
        "employer_contribution_total": "1000.00",
        "gross_adjustment_total": "0.00",
        "gross_total": "101000.00",
        "ag_deduction_total": "0.00",
        "treasury_deduction_total": "0.00",
        "external_recovery_total": "0.00",
        "deductions_total": "10000.00",
        "net_payable": "91000.00",
    }
    june_totals = {
        "earnings_total": "120000.00",
        "employer_contribution_total": "1500.00",
        "gross_adjustment_total": "0.00",
        "gross_total": "121500.00",
        "ag_deduction_total": "0.00",
        "treasury_deduction_total": "0.00",
        "external_recovery_total": "0.00",
        "deductions_total": "12000.00",
        "net_payable": "109500.00",
    }

    may_run_id = await _seed_posted_run(
        session,
        org_id=org.id,
        user_id=admin.id,
        year=2026,
        month=5,
        totals=may_totals,
        content_hash="b" * 64,
        posted_at=datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc),
    )
    june_run_id = await _seed_posted_run(
        session,
        org_id=org.id,
        user_id=admin.id,
        year=2026,
        month=6,
        totals=june_totals,
        content_hash="c" * 64,
        posted_at=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
    )
    draft_run_id = await _seed_draft_run(session, org_id=org.id, year=2026, month=7, status="draft")
    await _seed_draft_run(session, org_id=org.id, year=2026, month=4, status="calculated")

    art_new = await _seed_artifact(
        session,
        org_id=org.id,
        user_id=admin.id,
        report_type="payroll_register",
        created_at=datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc),
    )
    await _seed_artifact(
        session,
        org_id=org.id,
        user_id=admin.id,
        report_type="bank_file",
        created_at=datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc),
    )
    await session.commit()

    # Single posted run → variance null
    await _bind(session, org.id, admin.id)
    may_run = await session.get(PayrollRun, may_run_id)
    assert may_run is not None
    may_run.status = "approved"
    await session.commit()

    resp_one = await client.get("/api/dashboard")
    assert resp_one.status_code == 200, resp_one.text
    one = resp_one.json()
    assert one["variance"] is None
    assert one["latest_posted"]["run_id"] == str(june_run_id)
    assert one["previous_posted"] is None

    await _bind(session, org.id, admin.id)
    may_run = await session.get(PayrollRun, may_run_id)
    assert may_run is not None
    may_run.status = "posted"
    await session.commit()

    resp = await client.get("/api/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["headcount"] == {
        "active_employees": 4,
        "by_regime": {"gpf": 2, "nps": 1, "epf": 1},
    }

    assert body["current_period"]["year"] == 2026
    assert body["current_period"]["month"] == 7
    assert body["current_period"]["run"]["id"] == str(draft_run_id)
    assert body["current_period"]["run"]["status"] == "draft"
    assert body["current_period"]["run"]["version_number"] is None

    assert body["latest_posted"]["run_id"] == str(june_run_id)
    assert body["latest_posted"]["period"] == {"year": 2026, "month": 6}
    assert body["latest_posted"]["totals"] == {
        "earnings": "120000.00",
        "employer_contribution": "1500.00",
        "gross": "121500.00",
        "deductions": "12000.00",
        "net": "109500.00",
    }
    assert body["latest_posted"]["posted_at"].startswith("2026-06-28T10:00:00")

    assert body["previous_posted"]["run_id"] == str(may_run_id)
    assert body["previous_posted"]["period"] == {"year": 2026, "month": 5}
    assert body["previous_posted"]["totals"] == {
        "earnings": "100000.00",
        "employer_contribution": "1000.00",
        "gross": "101000.00",
        "deductions": "10000.00",
        "net": "91000.00",
    }

    assert body["variance"] == {
        "gross_delta": "20500.00",
        "net_delta": "18500.00",
    }

    assert body["pipeline"] == {
        "draft": 1,
        "calculated": 1,
        "submitted": 0,
        "approved": 0,
        "posted": 2,
        "rejected": 0,
        "reversed": 0,
    }

    assert len(body["recent_artifacts"]) == 2
    assert body["recent_artifacts"][0]["id"] == str(art_new)
    assert body["recent_artifacts"][0]["report_type"] == "payroll_register"


@pytest.mark.asyncio
async def test_dashboard_tenant_isolation(client, session, dev_settings):
    org_a, admin_a = await _admin_world(
        session, dev_settings, client, slug=f"dash-a-{uuid4().hex[:8]}"
    )
    await _bind(session, org_a.id, admin_a.id)
    await _seed_employee_with_regime(
        session, org_id=org_a.id, user_id=admin_a.id, regime="gpf", number="A-GPF-1"
    )
    await _seed_posted_run(
        session,
        org_id=org_a.id,
        user_id=admin_a.id,
        year=2026,
        month=6,
        totals={
            "earnings_total": "50000.00",
            "employer_contribution_total": "0.00",
            "gross_total": "50000.00",
            "deductions_total": "0.00",
            "net_payable": "50000.00",
        },
        content_hash="d" * 64,
        posted_at=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
    )
    await _seed_artifact(
        session,
        org_id=org_a.id,
        user_id=admin_a.id,
        report_type="payroll_register",
        created_at=datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc),
    )
    await session.commit()

    org_b, admin_b = await _admin_world(
        session, dev_settings, client, slug=f"dash-b-{uuid4().hex[:8]}"
    )
    assert org_b.id != org_a.id
    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=admin_b.id,
            active_organization_id=org_b.id,
        ),
    )

    resp = await client.get("/api/dashboard")
    assert resp.status_code == 200, resp.text
    assert resp.json() == _empty_dashboard_shape()


@pytest.mark.asyncio
async def test_dashboard_capability_gate_auditor_403(client, session, dev_settings):
    org, _admin = await _admin_world(session, dev_settings, client)

    auditor = await seed_user(session, email="auditor-dash@example.com", name="Auditor")
    await seed_membership(
        session,
        organization_id=org.id,
        user_id=auditor.id,
        role="auditor",
    )
    await session.commit()

    apply_session_cookie(
        client,
        await mint_session_cookie(
            session,
            dev_settings,
            user_id=auditor.id,
            active_organization_id=org.id,
        ),
    )

    resp = await client.get("/api/dashboard")
    assert resp.status_code == 403
    assert resp.json()["error"] == "urn:accord:capability:view_master_data"
