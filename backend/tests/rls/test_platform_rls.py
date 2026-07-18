"""Behavioral RLS tests for Phase 5 platform tables (audit_events + jobs)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
import pytest
from psycopg.types.json import Json

from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
)

RLS_SPOT_CHECK_TABLES = (
    "audit_events",
    "jobs",
)


@dataclass(frozen=True)
class SeededPlatformData:
    org_a_id: uuid.UUID
    org_b_id: uuid.UUID
    user_a_id: uuid.UUID
    user_b_id: uuid.UUID
    audit_a_id: uuid.UUID
    audit_b_id: uuid.UUID
    job_a_id: uuid.UUID
    job_b_id: uuid.UUID


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )
        # Re-apply ADR-0009 narrow grants after the broad grant above.
        conn.execute(
            "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM accord_app, accord_worker"
        )
        conn.execute(
            "REVOKE DELETE, TRUNCATE ON TABLE outbox_events FROM accord_app, accord_worker"
        )


def _seed_platform_data(database_url: str) -> SeededPlatformData:
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    audit_a_id = uuid.uuid4()
    audit_b_id = uuid.uuid4()
    job_a_id = uuid.uuid4()
    job_b_id = uuid.uuid4()

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s), (%s, %s, %s)",
            (org_a_id, "Org A", "org-a", org_b_id, "Org B", "org-b"),
        )
        conn.execute(
            "INSERT INTO users (id, workos_user_id, email, name) VALUES "
            "(%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                user_a_id,
                f"wos_{user_a_id.hex[:12]}",
                f"a-{user_a_id.hex[:8]}@example.com",
                "User A",
                user_b_id,
                f"wos_{user_b_id.hex[:12]}",
                f"b-{user_b_id.hex[:8]}@example.com",
                "User B",
            ),
        )
        conn.execute(
            "INSERT INTO audit_events "
            "(id, organization_id, actor_user_id, request_id, command, "
            "entity_type, entity_id, summary) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s), "
            "(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                audit_a_id,
                org_a_id,
                user_a_id,
                "req-a",
                "post",
                "payroll_run",
                uuid.uuid4(),
                Json({"before": {"status": "approved"}, "after": {"status": "posted"}}),
                audit_b_id,
                org_b_id,
                user_b_id,
                "req-b",
                "post",
                "payroll_run",
                uuid.uuid4(),
                Json({"before": {"status": "approved"}, "after": {"status": "posted"}}),
            ),
        )
        conn.execute(
            "INSERT INTO jobs "
            "(id, organization_id, job_type, status, payload, created_by) VALUES "
            "(%s, %s, %s, %s, %s, %s), (%s, %s, %s, %s, %s, %s)",
            (
                job_a_id,
                org_a_id,
                "export.generate",
                "queued",
                Json({"report_type": "bank_file"}),
                user_a_id,
                job_b_id,
                org_b_id,
                "export.generate",
                "queued",
                Json({"report_type": "bank_file"}),
                user_b_id,
            ),
        )
        conn.commit()

    return SeededPlatformData(
        org_a_id=org_a_id,
        org_b_id=org_b_id,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        audit_a_id=audit_a_id,
        audit_b_id=audit_b_id,
        job_a_id=job_a_id,
        job_b_id=job_b_id,
    )


@pytest.fixture
def seeded_platform_db(scratch_db: str) -> tuple[str, SeededPlatformData]:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)
    seed = _seed_platform_data(scratch_db)
    return scratch_db, seed


@pytest.mark.parametrize("role", ("accord_app", "accord_worker"))
def test_platform_select_scoped_to_organization_guc(
    seeded_platform_db: tuple[str, SeededPlatformData],
    role: str,
) -> None:
    database_url, seed = seeded_platform_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(f"SET ROLE {role}")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        audits = conn.execute("SELECT organization_id FROM audit_events").fetchall()
        jobs = conn.execute("SELECT organization_id FROM jobs").fetchall()

    assert {row[0] for row in audits} == {seed.org_a_id}
    assert {row[0] for row in jobs} == {seed.org_a_id}


def test_platform_insert_wrong_organization_blocked(
    seeded_platform_db: tuple[str, SeededPlatformData],
) -> None:
    database_url, seed = seeded_platform_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO audit_events "
                "(organization_id, command, entity_type, entity_id, summary) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_b_id,
                    "calculate",
                    "payroll_run",
                    uuid.uuid4(),
                    Json({"after": {"status": "calculated"}}),
                ),
            )
        conn.rollback()
        conn.execute("SET ROLE accord_app")
        conn.execute(
            "SELECT set_config('app.organization_id', %s, false)",
            (str(seed.org_a_id),),
        )
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO jobs (organization_id, job_type, status, payload) "
                "VALUES (%s, %s, %s, %s)",
                (
                    seed.org_b_id,
                    "export.generate",
                    "queued",
                    Json({}),
                ),
            )


@pytest.mark.parametrize("role", ("accord_app", "accord_worker"))
def test_platform_select_fail_closed_without_organization_guc(
    seeded_platform_db: tuple[str, SeededPlatformData],
    role: str,
) -> None:
    database_url, _seed = seeded_platform_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute(f"SET ROLE {role}")
        for table in RLS_SPOT_CHECK_TABLES:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table}: expected fail-closed empty result"


def test_platform_insert_fail_closed_without_organization_guc(
    seeded_platform_db: tuple[str, SeededPlatformData],
) -> None:
    database_url, seed = seeded_platform_db

    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        conn.execute("SET ROLE accord_app")
        # No app.organization_id GUC — WITH CHECK must reject inserts.
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO audit_events "
                "(organization_id, command, entity_type, entity_id, summary) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    seed.org_a_id,
                    "calculate",
                    "payroll_run",
                    uuid.uuid4(),
                    Json({"after": {}}),
                ),
            )
        conn.rollback()
        # ROLLBACK undoes SET ROLE issued in the aborted transaction.
        conn.execute("SET ROLE accord_app")
        with pytest.raises(psycopg.Error, match="(?i)row-level security"):
            conn.execute(
                "INSERT INTO jobs (organization_id, job_type, status, payload) "
                "VALUES (%s, %s, %s, %s)",
                (seed.org_a_id, "export.generate", "queued", Json({})),
            )
