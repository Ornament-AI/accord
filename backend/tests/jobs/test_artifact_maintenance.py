"""RLS regression for the ``artifacts.maintenance`` worker handler.

``reconcile_orphans`` commits, which drops the transaction-local
``app.organization_id`` GUC. Under the forced-RLS ``accord_worker`` role
every subsequent org-scoped statement would then match zero rows — the
expired idempotency key would survive and the past-retention artifact would
never expire. Each maintenance step must re-bind tenant context first.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.jobs.handlers import (
    bind_job_session,
    configure_generate_report,
    handle_artifact_maintenance,
)
from app.jobs.protocol import Job, JobStatus
from app.models.base import utcnow
from app.models.identity import IdempotencyKey
from app.models.platform import ExportArtifact
from app.reports.base import ReportRegistry
from app.storage.memory import InMemoryObjectStorage
from app.tenancy import bind_tenant_context
from tests.migrations.conftest import (
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
    scratch_db as scratch_db,  # noqa: F401
)


def _grant_table_dml(database_url: str) -> None:
    with psycopg.connect(as_psycopg_url(database_url), autocommit=True) as conn:
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO accord_app, accord_worker"
        )


@pytest.mark.asyncio
async def test_maintenance_steps_rebind_after_commit_under_accord_worker(
    scratch_db: str,
) -> None:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    failed_key_id = uuid.uuid4()
    succeeded_key_id = uuid.uuid4()
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
            (org_id, "Maint Org", "maint-rls"),
        )
        conn.execute(
            "INSERT INTO users (id, workos_user_id, email, name) VALUES (%s, %s, %s, %s)",
            (user_id, f"workos_{uuid.uuid4().hex[:8]}", "maint@example.com", "Maint"),
        )
        conn.execute(
            """
            INSERT INTO export_artifacts (
                id, organization_id, report_type, template_version,
                object_key, checksum_sha256, content_type, size_bytes,
                status, requested_by, retention_expires_at
            ) VALUES (%s, %s, 'bank_file', 'v1', %s, %s, 'text/csv', 3,
                      'finalized', %s, now() - interval '1 day')
            """,
            (artifact_id, org_id, f"{org_id}/maint-object", "a" * 64, user_id),
        )
        conn.execute(
            """
            INSERT INTO idempotency_keys (
                id, organization_id, key, request_hash, status, expires_at
            ) VALUES (%s, %s, 'k-exp-failed', 'h', 'failed',
                      now() - interval '1 hour'),
                     (%s, %s, 'k-exp-succeeded', 'h', 'succeeded',
                      now() - interval '1 hour')
            """,
            (failed_key_id, org_id, succeeded_key_id, org_id),
        )
        conn.commit()

    # NullPool returns/closes the connection on commit, which drops SET ROLE.
    # Re-apply on every connect so FORCE RLS stays active across handler
    # commits (production connects as accord_worker; SET ROLE is the
    # passwordless test equivalent per tests/rls/test_identity_tenancy_rls.py).
    engine = create_async_engine(scratch_db, poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_worker_role(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
        dbapi_conn.run_async(lambda conn: conn.execute("SET ROLE accord_worker"))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    configure_generate_report(storage=InMemoryObjectStorage(), registry=ReportRegistry())

    try:
        async with factory() as session:
            assert (
                await session.execute(text("SELECT current_user"))
            ).scalar_one() == "accord_worker"
            await bind_tenant_context(session, organization_id=org_id)

            job = Job(
                id=uuid.uuid4(),
                organization_id=org_id,
                job_type="artifacts.maintenance",
                status=JobStatus.running,
                payload={},
                available_at=utcnow(),
                created_at=utcnow(),
            )
            with bind_job_session(session):
                result = await handle_artifact_maintenance(job)

            assert result == {
                "reconciled": {
                    "finalized": 0,
                    "deleted": 0,
                    "idempotency_keys_purged": 1,
                    "checksum_mismatch": 0,
                },
                "expired": 1,
            }

            # Rebind to inspect the final state as accord_worker.
            await bind_tenant_context(session, organization_id=org_id)
            artifact = (
                await session.execute(
                    select(ExportArtifact).where(ExportArtifact.id == artifact_id)
                )
            ).scalar_one()
            assert artifact.status == "expired"

            keys = {
                row.id: row.status
                for row in (await session.execute(select(IdempotencyKey))).scalars().all()
            }
            assert failed_key_id not in keys
            assert keys[succeeded_key_id] == "succeeded"
    finally:
        await engine.dispose()
