"""Integration tests for organization-scoped command idempotency."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import psycopg
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import get_session_factory
from app.exceptions import ConflictError
from app.models.base import utcnow
from app.models.identity import IdempotencyKey
from app.services.idempotency import compute_request_hash, idempotent_command
from app.tenancy import set_config_local
from tests.identity_helpers import seed_organization
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


def test_compute_request_hash_is_canonical():
    a = compute_request_hash({"b": 1, "a": 2})
    b = compute_request_hash({"a": 2, "b": 1})
    assert a == b
    assert len(a) == 64
    assert a != compute_request_hash({"a": 2, "b": 3})


@pytest.mark.asyncio
async def test_first_call_executes_and_stores_succeeded_snapshot(session):
    org = await seed_organization(session, slug="idem-first")
    await session.commit()

    calls: list[int] = []

    async def executor():
        calls.append(1)
        return {"result": "ok", "n": 1}

    out = await idempotent_command(
        session,
        organization_id=org.id,
        key="cmd-1",
        request_payload={"action": "submit", "run_id": "r1"},
        executor=executor,
    )
    assert out == {"result": "ok", "n": 1}
    assert len(calls) == 1

    row = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == org.id,
                IdempotencyKey.key == "cmd-1",
            )
        )
    ).scalar_one()
    assert row.status == "succeeded"
    assert row.response_snapshot == {"result": "ok", "n": 1}
    assert row.request_hash == compute_request_hash({"action": "submit", "run_id": "r1"})


@pytest.mark.asyncio
async def test_replay_same_key_and_payload_does_not_reexecute(session):
    org = await seed_organization(session, slug="idem-replay")
    await session.commit()

    calls: list[int] = []

    async def executor():
        calls.append(1)
        return {"result": "stored"}

    payload = {"action": "approve", "run_id": "r2"}
    first = await idempotent_command(
        session,
        organization_id=org.id,
        key="cmd-replay",
        request_payload=payload,
        executor=executor,
    )
    second = await idempotent_command(
        session,
        organization_id=org.id,
        key="cmd-replay",
        request_payload=payload,
        executor=executor,
    )
    assert first == second == {"result": "stored"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_same_key_different_payload_conflicts(session):
    org = await seed_organization(session, slug="idem-mismatch")
    await session.commit()

    async def executor():
        return {"ok": True}

    await idempotent_command(
        session,
        organization_id=org.id,
        key="cmd-mismatch",
        request_payload={"v": 1},
        executor=executor,
    )
    with pytest.raises(ConflictError, match="different request payload"):
        await idempotent_command(
            session,
            organization_id=org.id,
            key="cmd-mismatch",
            request_payload={"v": 2},
            executor=executor,
        )


@pytest.mark.asyncio
async def test_in_progress_same_payload_conflicts(session):
    org = await seed_organization(session, slug="idem-inflight")
    await session.commit()

    payload = {"action": "post"}
    session.add(
        IdempotencyKey(
            organization_id=org.id,
            key="cmd-inflight",
            request_hash=compute_request_hash(payload),
            status="in_progress",
            expires_at=utcnow() + timedelta(hours=72),
        )
    )
    await session.commit()

    async def executor():
        return {"should": "not-run"}

    with pytest.raises(ConflictError, match="command in progress"):
        await idempotent_command(
            session,
            organization_id=org.id,
            key="cmd-inflight",
            request_payload=payload,
            executor=executor,
        )


@pytest.mark.asyncio
async def test_failed_row_retries_and_succeeds(session):
    org = await seed_organization(session, slug="idem-failed")
    await session.commit()

    payload = {"action": "validate"}
    session.add(
        IdempotencyKey(
            organization_id=org.id,
            key="cmd-failed",
            request_hash=compute_request_hash(payload),
            status="failed",
            expires_at=utcnow() + timedelta(hours=72),
        )
    )
    await session.commit()

    calls: list[int] = []

    async def executor():
        calls.append(1)
        return {"retried": True}

    out = await idempotent_command(
        session,
        organization_id=org.id,
        key="cmd-failed",
        request_payload=payload,
        executor=executor,
    )
    assert out == {"retried": True}
    assert len(calls) == 1

    row = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == org.id,
                IdempotencyKey.key == "cmd-failed",
            )
        )
    ).scalar_one()
    assert row.status == "succeeded"
    assert row.response_snapshot == {"retried": True}


@pytest.mark.asyncio
async def test_expired_row_reexecutes(session):
    org = await seed_organization(session, slug="idem-expired")
    await session.commit()

    payload = {"action": "calculate"}
    session.add(
        IdempotencyKey(
            organization_id=org.id,
            key="cmd-expired",
            request_hash=compute_request_hash(payload),
            status="succeeded",
            response_snapshot={"stale": True},
            expires_at=utcnow() - timedelta(hours=1),
        )
    )
    await session.commit()

    calls: list[int] = []

    async def executor():
        calls.append(1)
        return {"fresh": True}

    out = await idempotent_command(
        session,
        organization_id=org.id,
        key="cmd-expired",
        request_payload=payload,
        executor=executor,
    )
    assert out == {"fresh": True}
    assert len(calls) == 1

    row = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == org.id,
                IdempotencyKey.key == "cmd-expired",
            )
        )
    ).scalar_one()
    assert row.status == "succeeded"
    assert row.response_snapshot == {"fresh": True}
    assert row.expires_at > utcnow()


@pytest.mark.asyncio
async def test_executor_raise_persists_failed_and_propagates(session):
    org = await seed_organization(session, slug="idem-raise")
    await session.commit()
    # Capture before idempotent_command: failure-path rollback expires session ORM
    # state after _execute_claimed snapshots tenant GUCs (opens a transaction).
    org_id = org.id

    async def executor():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await idempotent_command(
            session,
            organization_id=org_id,
            key="cmd-raise",
            request_payload={"action": "submit"},
            executor=executor,
        )

    row = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == org_id,
                IdempotencyKey.key == "cmd-raise",
            )
        )
    ).scalar_one()
    assert row.status == "failed"
    assert row.response_snapshot is None


@pytest.mark.asyncio
async def test_concurrent_race_coherent_outcome(session):
    org = await seed_organization(session, slug="idem-race")
    await session.commit()
    org_id = org.id
    payload = {"action": "post", "run_id": "race-1"}
    key = "cmd-race"

    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[int] = []

    async def slow_executor():
        calls.append(1)
        started.set()
        await release.wait()
        return {"winner": True}

    factory = get_session_factory()

    async def caller():
        async with factory() as db:
            try:
                return await idempotent_command(
                    db,
                    organization_id=org_id,
                    key=key,
                    request_payload=payload,
                    executor=slow_executor,
                )
            except ConflictError as exc:
                return exc

    task_a = asyncio.create_task(caller())
    await asyncio.wait_for(started.wait(), timeout=5.0)
    task_b = asyncio.create_task(caller())
    # Let B observe in_progress (or wait on the unique index) before A finishes.
    await asyncio.sleep(0.05)
    release.set()
    results = await asyncio.gather(task_a, task_b)

    successes = [r for r in results if isinstance(r, dict)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]
    assert len(successes) + len(conflicts) == 2
    assert len(successes) >= 1
    assert all(s == {"winner": True} for s in successes)
    assert all("command in progress" in str(c) for c in conflicts)
    # At most one execution while the first claim is held; a conflict loser must
    # not have re-executed. If both somehow finish after success, still one call.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_execute_claimed_rebinds_tenant_gucs_under_accord_app(
    scratch_db: str,
) -> None:
    """Regression: executor commit must not leave idempotency_keys updates blind.

    WHY this fails pre-fix: without the rebind after executor commit/rollback,
    ``db.get`` / UPDATE run under ``accord_app`` with no ``app.organization_id``
    → forced RLS matches zero rows → key stays ``in_progress`` / snapshot never
    written (or ``ConflictError`` "disappeared"). Superuser DSNs mask this.
    """
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)
    ensure_accord_roles(database_url=scratch_db)
    _grant_table_dml(scratch_db)

    org_id = uuid.uuid4()
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
            (org_id, "Idem GUC Org", "idem-guc-rebind"),
        )
        conn.commit()

    # NullPool returns/closes the connection on commit, which drops SET ROLE.
    # Re-apply on every connect so FORCE RLS stays active across claim/executor
    # commits (production connects as accord_app; SET ROLE is the passwordless
    # test equivalent per tests/rls/test_identity_tenancy_rls.py).
    engine = create_async_engine(scratch_db, poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_accord_app_role(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
        dbapi_conn.run_async(lambda conn: conn.execute("SET ROLE accord_app"))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls: list[int] = []
    key = "cmd-guc-rebind"
    payload = {"action": "submit", "run_id": "guc-1"}

    try:
        async with factory() as db:
            current_user = (await db.execute(text("SELECT current_user"))).scalar_one()
            session_user = (await db.execute(text("SELECT session_user"))).scalar_one()
            assert current_user == "accord_app"
            assert session_user != "accord_app"

            # Middleware-equivalent: bind org GUC with SET LOCAL before the command.
            await set_config_local(db, "app.organization_id", str(org_id))

            async def executor() -> dict:
                calls.append(1)
                # Mid-command commit drops SET LOCAL tenant GUCs — triggers the bug.
                # Assert role survives the reconnect so we still exercise accord_app.
                await db.commit()
                role_after = (await db.execute(text("SELECT current_user"))).scalar_one()
                assert role_after == "accord_app"
                return {"result": "ok", "n": 1}

            out = await idempotent_command(
                db,
                organization_id=org_id,
                key=key,
                request_payload=payload,
                executor=executor,
            )
            assert out == {"result": "ok", "n": 1}
            assert len(calls) == 1

            # Final command commit cleared GUCs; rebind to inspect as accord_app.
            await set_config_local(db, "app.organization_id", str(org_id))
            assert (await db.execute(text("SELECT current_user"))).scalar_one() == "accord_app"
            row = (
                await db.execute(
                    select(IdempotencyKey).where(
                        IdempotencyKey.organization_id == org_id,
                        IdempotencyKey.key == key,
                    )
                )
            ).scalar_one()
            assert row.status == "succeeded"
            assert row.response_snapshot == {"result": "ok", "n": 1}

            replay = await idempotent_command(
                db,
                organization_id=org_id,
                key=key,
                request_payload=payload,
                executor=executor,
            )
            assert replay == {"result": "ok", "n": 1}
            assert len(calls) == 1
    finally:
        await engine.dispose()
