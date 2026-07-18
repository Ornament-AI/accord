"""Behavioral RLS tests for Phase 3 master-data tables.

Also covers GiST EXCLUDE overlap rejection, primary bank-account partial
exclude, gpf_jurisdiction CHECK, boundary-date effective_on resolution, and
the self_membership_read SELECT policy on organization_memberships.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import psycopg
import pytest
from psycopg.errors import ExclusionViolation
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.models.effective import select_active_version
from app.models.employees import employee_profile_versions
from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
)

RLS_SPOT_CHECK_TABLES = (
    "offices",
    "employee_profile_versions",
    "recurring_instruction_versions",
)


@dataclass(frozen=True)
class SeededMasterData:
    org_a_id: uuid.UUID
    org_b_id: uuid.UUID
    user_u_id: uuid.UUID
    user_v_id: uuid.UUID
    employee_a_id: uuid.UUID
    employee_b_id: uuid.UUID
    created_by: uuid.UUID
    recurring_header_a_id: uuid.UUID
    component_a_id: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


def _seed_master_data(database_url: str) -> SeededMasterData:
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    user_u_id = uuid.uuid4()
    user_v_id = uuid.uuid4()
    employee_a_id = uuid.uuid4()
    employee_b_id = uuid.uuid4()
    created_by = uuid.uuid4()
    component_a_id = uuid.uuid4()
    component_b_id = uuid.uuid4()
    recurring_header_a_id = uuid.uuid4()
    recurring_header_b_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s), (%s, %s, %s)",
            (org_a_id, "Org A", "org-a", org_b_id, "Org B", "org-b"),
        )
        conn.execute(
            "INSERT INTO users (id, workos_user_id, email, name) VALUES "
            "(%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                user_u_id,
                "workos_user_u",
                "u@example.com",
                "User U",
                user_v_id,
                "workos_user_v",
                "v@example.com",
                "User V",
            ),
        )
        # User U has memberships in BOTH orgs; user V has none.
        conn.execute(
            "INSERT INTO organization_memberships "
            "(organization_id, user_id, role) VALUES "
            "(%s, %s, %s), (%s, %s, %s)",
            (
                org_a_id,
                user_u_id,
                "organization_administrator",
                org_b_id,
                user_u_id,
                "payroll_preparer",
            ),
        )
        conn.execute(
            "INSERT INTO offices (organization_id, name, code, jurisdiction) VALUES "
            "(%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                org_a_id,
                "Office A",
                "OFF-A",
                "mumbai",
                org_b_id,
                "Office B",
                "OFF-B",
                "nagpur",
            ),
        )
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) VALUES "
            "(%s, %s, %s), (%s, %s, %s)",
            (
                employee_a_id,
                org_a_id,
                "E-001",
                employee_b_id,
                org_b_id,
                "E-001",
            ),
        )
        conn.execute(
            "INSERT INTO employee_profile_versions "
            "(organization_id, header_id, validity, name, sevarth_id, "
            "date_of_birth, date_of_joining, retirement_regime, gpf_jurisdiction, "
            "created_by) VALUES "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s), "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s)",
            (
                org_a_id,
                employee_a_id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                "Alice",
                "SEV-A",
                date(1990, 1, 1),
                date(2015, 1, 1),
                "gpf",
                "mumbai",
                created_by,
                org_b_id,
                employee_b_id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                "Bob",
                "SEV-B",
                date(1991, 1, 1),
                date(2016, 1, 1),
                "nps",
                None,
                created_by,
            ),
        )
        conn.execute(
            "INSERT INTO pay_components "
            "(id, organization_id, code, name, classification) VALUES "
            "(%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)",
            (
                component_a_id,
                org_a_id,
                "HRA",
                "HRA",
                "earning",
                component_b_id,
                org_b_id,
                "HRA",
                "HRA",
                "earning",
            ),
        )
        conn.execute(
            "INSERT INTO recurring_instructions "
            "(id, organization_id, employee_id, component_id) VALUES "
            "(%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                recurring_header_a_id,
                org_a_id,
                employee_a_id,
                component_a_id,
                recurring_header_b_id,
                org_b_id,
                employee_b_id,
                component_b_id,
            ),
        )
        conn.execute(
            "INSERT INTO recurring_instruction_versions "
            "(organization_id, header_id, validity, amount, created_by) VALUES "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s), "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s)",
            (
                org_a_id,
                recurring_header_a_id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                "1000.00",
                created_by,
                org_b_id,
                recurring_header_b_id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                "2000.00",
                created_by,
            ),
        )
        conn.commit()

    return SeededMasterData(
        org_a_id=org_a_id,
        org_b_id=org_b_id,
        user_u_id=user_u_id,
        user_v_id=user_v_id,
        employee_a_id=employee_a_id,
        employee_b_id=employee_b_id,
        created_by=created_by,
        recurring_header_a_id=recurring_header_a_id,
        component_a_id=component_a_id,
    )


@pytest.fixture
def seeded_master_db(scratch_db: str) -> tuple[str, SeededMasterData]:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_master_data(scratch_db)
    return scratch_db, seed


def test_master_data_select_scoped_to_organization_guc(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        offices = conn.execute("SELECT organization_id FROM offices").fetchall()
        profiles = conn.execute("SELECT organization_id FROM employee_profile_versions").fetchall()
        versions = conn.execute(
            "SELECT organization_id FROM recurring_instruction_versions"
        ).fetchall()

    assert {row[0] for row in offices} == {seed.org_a_id}
    assert {row[0] for row in profiles} == {seed.org_a_id}
    assert {row[0] for row in versions} == {seed.org_a_id}


def test_master_data_insert_wrong_organization_blocked(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO offices (organization_id, name, code, jurisdiction) "
                "VALUES (%s, %s, %s, %s)",
                (seed.org_b_id, "Cross", "X", "other"),
            )


def test_master_data_select_fail_closed_without_organization_guc(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, _seed = seeded_master_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        for table in RLS_SPOT_CHECK_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result"


def test_overlapping_validity_rejected_by_gist_exclude(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        with pytest.raises(ExclusionViolation):
            conn.execute(
                "INSERT INTO recurring_instruction_versions "
                "(organization_id, header_id, validity, amount, created_by) "
                "VALUES (%s, %s, daterange(%s, %s, '[)'), %s, %s)",
                (
                    seed.org_a_id,
                    seed.recurring_header_a_id,
                    date(2026, 6, 1),
                    date(2026, 9, 1),
                    "1500.00",
                    seed.created_by,
                ),
            )


def test_effective_on_boundary_date_resolution(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db
    employee_id = uuid.uuid4()
    created_by = seed.created_by

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) VALUES (%s, %s, %s)",
            (employee_id, seed.org_a_id, "E-BOUNDARY"),
        )
        conn.execute(
            "INSERT INTO employee_profile_versions "
            "(organization_id, header_id, validity, name, sevarth_id, "
            "date_of_birth, date_of_joining, retirement_regime, created_by) VALUES "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s), "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s)",
            (
                seed.org_a_id,
                employee_id,
                date(2026, 1, 1),
                date(2026, 4, 1),
                "Before",
                "SEV-1",
                date(1990, 1, 1),
                date(2015, 1, 1),
                "nps",
                created_by,
                seed.org_a_id,
                employee_id,
                date(2026, 4, 1),
                date(2026, 12, 31),
                "After",
                "SEV-1",
                date(1990, 1, 1),
                date(2015, 1, 1),
                "nps",
                created_by,
            ),
        )
        conn.commit()

    # as_psycopg_url yields a bare postgresql:// DSN, which SQLAlchemy resolves
    # to the psycopg2 dialect. Only psycopg (v3) is installed, so pin the driver.
    engine = create_engine(
        as_psycopg_url(database_url).replace("postgresql://", "postgresql+psycopg://", 1),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as conn:
            before = conn.execute(
                select_active_version(
                    employee_profile_versions,
                    header_id=employee_id,
                    organization_id=seed.org_a_id,
                    on_date=date(2026, 3, 31),
                )
            ).one()
            on_boundary = conn.execute(
                select_active_version(
                    employee_profile_versions,
                    header_id=employee_id,
                    organization_id=seed.org_a_id,
                    on_date=date(2026, 4, 1),
                )
            ).one()
            after = conn.execute(
                select_active_version(
                    employee_profile_versions,
                    header_id=employee_id,
                    organization_id=seed.org_a_id,
                    on_date=date(2026, 4, 2),
                )
            ).one()
    finally:
        engine.dispose()

    assert before.name == "Before"
    assert on_boundary.name == "After"
    assert after.name == "After"


def test_primary_bank_account_partial_exclude(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        # Two overlapping primary salary accounts — rejected.
        conn.execute(
            "INSERT INTO employee_bank_account_versions "
            "(organization_id, header_id, validity, account_number, ifsc, "
            "bank_name, branch, is_primary_salary, created_by) "
            "VALUES (%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s)",
            (
                seed.org_a_id,
                seed.employee_a_id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                "111",
                "SBIN0001",
                "SBI",
                "Main",
                True,
                seed.created_by,
            ),
        )
        with pytest.raises(ExclusionViolation):
            conn.execute(
                "INSERT INTO employee_bank_account_versions "
                "(organization_id, header_id, validity, account_number, ifsc, "
                "bank_name, branch, is_primary_salary, created_by) "
                "VALUES (%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s)",
                (
                    seed.org_a_id,
                    seed.employee_a_id,
                    date(2026, 6, 1),
                    date(2026, 9, 1),
                    "222",
                    "SBIN0002",
                    "SBI",
                    "Branch",
                    True,
                    seed.created_by,
                ),
            )
        conn.rollback()

        # Primary + overlapping non-primary — allowed.
        conn.execute(
            "INSERT INTO employee_bank_account_versions "
            "(organization_id, header_id, validity, account_number, ifsc, "
            "bank_name, branch, is_primary_salary, created_by) "
            "VALUES (%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s), "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s)",
            (
                seed.org_a_id,
                seed.employee_a_id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                "111",
                "SBIN0001",
                "SBI",
                "Main",
                True,
                seed.created_by,
                seed.org_a_id,
                seed.employee_a_id,
                date(2026, 6, 1),
                date(2026, 9, 1),
                "222",
                "SBIN0002",
                "SBI",
                "Branch",
                False,
                seed.created_by,
            ),
        )
        conn.commit()


def test_gpf_jurisdiction_check_constraint(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db
    employee_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO employees (id, organization_id, employee_number) VALUES (%s, %s, %s)",
            (employee_id, seed.org_a_id, "E-GPF"),
        )
        conn.commit()

        def _insert(regime: str, jurisdiction: str | None) -> None:
            conn.execute(
                "INSERT INTO employee_profile_versions "
                "(organization_id, header_id, validity, name, sevarth_id, "
                "date_of_birth, date_of_joining, retirement_regime, "
                "gpf_jurisdiction, created_by) VALUES "
                "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s)",
                (
                    seed.org_a_id,
                    employee_id,
                    date(2026, 1, 1),
                    date(2026, 2, 1),
                    "Name",
                    "SEV-GPF",
                    date(1990, 1, 1),
                    date(2015, 1, 1),
                    regime,
                    jurisdiction,
                    seed.created_by,
                ),
            )

        # gpf + jurisdiction set — ok
        _insert("gpf", "mumbai")
        conn.commit()

        # Shift validity windows so EXCLUDE does not fire between cases.
        # gpf + NULL — ok when the source does not state a jurisdiction
        conn.execute(
            "INSERT INTO employee_profile_versions "
            "(organization_id, header_id, validity, name, sevarth_id, "
            "date_of_birth, date_of_joining, retirement_regime, "
            "gpf_jurisdiction, created_by) VALUES "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s)",
            (
                seed.org_a_id,
                employee_id,
                date(2026, 2, 1),
                date(2026, 3, 1),
                "Name",
                "SEV-GPF",
                date(1990, 1, 1),
                date(2015, 1, 1),
                "gpf",
                None,
                seed.created_by,
            ),
        )
        conn.commit()

        # nps + NULL — ok
        conn.execute(
            "INSERT INTO employee_profile_versions "
            "(organization_id, header_id, validity, name, sevarth_id, "
            "date_of_birth, date_of_joining, retirement_regime, "
            "gpf_jurisdiction, created_by) VALUES "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s)",
            (
                seed.org_a_id,
                employee_id,
                date(2026, 3, 1),
                date(2026, 4, 1),
                "Name",
                "SEV-GPF",
                date(1990, 1, 1),
                date(2015, 1, 1),
                "nps",
                None,
                seed.created_by,
            ),
        )
        conn.commit()

        # epf + jurisdiction set — fails CHECK
        with pytest.raises(psycopg.Error, match="(?i)check"):
            conn.execute(
                "INSERT INTO employee_profile_versions "
                "(organization_id, header_id, validity, name, sevarth_id, "
                "date_of_birth, date_of_joining, retirement_regime, "
                "gpf_jurisdiction, created_by) VALUES "
                "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s)",
                (
                    seed.org_a_id,
                    employee_id,
                    date(2026, 4, 1),
                    date(2026, 5, 1),
                    "Name",
                    "SEV-GPF",
                    date(1990, 1, 1),
                    date(2015, 1, 1),
                    "epf",
                    "nagpur",
                    seed.created_by,
                ),
            )
        conn.rollback()

        # epf + NULL — ok
        conn.execute(
            "INSERT INTO employee_profile_versions "
            "(organization_id, header_id, validity, name, sevarth_id, "
            "date_of_birth, date_of_joining, retirement_regime, "
            "gpf_jurisdiction, created_by) VALUES "
            "(%s, %s, daterange(%s, %s, '[)'), %s, %s, %s, %s, %s, %s, %s)",
            (
                seed.org_a_id,
                employee_id,
                date(2026, 4, 1),
                date(2026, 5, 1),
                "Name",
                "SEV-GPF",
                date(1990, 1, 1),
                date(2015, 1, 1),
                "epf",
                None,
                seed.created_by,
            ),
        )
        conn.commit()


def test_self_membership_read_policy_cross_org(
    seeded_master_db: tuple[str, SeededMasterData],
) -> None:
    database_url, seed = seeded_master_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        # Only user_id GUC — no organization_id (or empty).
        conn.execute("SELECT set_config('app.organization_id', '', false)")
        conn.execute(
            "SELECT set_config('app.user_id', %s, false)",
            (str(seed.user_u_id),),
        )
        rows = conn.execute(
            "SELECT organization_id, user_id FROM organization_memberships ORDER BY organization_id"
        ).fetchall()

    assert {row[0] for row in rows} == {seed.org_a_id, seed.org_b_id}
    assert {row[1] for row in rows} == {seed.user_u_id}

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute("SELECT set_config('app.organization_id', '', false)")
        conn.execute(
            "SELECT set_config('app.user_id', %s, false)",
            (str(seed.user_v_id),),
        )
        rows_v = conn.execute("SELECT organization_id FROM organization_memberships").fetchall()

    assert rows_v == []
