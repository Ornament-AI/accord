"""Integration tests for organization-scoped command idempotency."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import get_session_factory
from app.exceptions import ConflictError
from app.models.base import utcnow
from app.models.identity import IdempotencyKey
from app.services.idempotency import compute_request_hash, idempotent_command
from tests.identity_helpers import seed_organization


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
async def test_same_key_different_organizations_do_not_collide(session):
    org_a = await seed_organization(session, slug="idem-org-a")
    org_b = await seed_organization(session, slug="idem-org-b")
    await session.commit()

    calls: list[str] = []

    async def exec_a():
        calls.append("a")
        return {"org": "a"}

    async def exec_b():
        calls.append("b")
        return {"org": "b"}

    out_a = await idempotent_command(
        session,
        organization_id=org_a.id,
        key="shared-key",
        request_payload={"x": 1},
        executor=exec_a,
    )
    out_b = await idempotent_command(
        session,
        organization_id=org_b.id,
        key="shared-key",
        request_payload={"x": 1},
        executor=exec_b,
    )
    assert out_a == {"org": "a"}
    assert out_b == {"org": "b"}
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_executor_raise_persists_failed_and_propagates(session):
    org = await seed_organization(session, slug="idem-raise")
    await session.commit()

    async def executor():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await idempotent_command(
            session,
            organization_id=org.id,
            key="cmd-raise",
            request_payload={"action": "submit"},
            executor=executor,
        )

    row = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == org.id,
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
