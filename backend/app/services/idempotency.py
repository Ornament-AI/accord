"""Organization-scoped command idempotency (ADR 0008 §6).

Phase 5 command routes (submit / approve / post / …) should wrap the command
body with :func:`idempotent_command`, passing the ``Idempotency-Key`` header as
``key`` and the request body (plus any command identity fields) as
``request_payload``::

    async def submit_run(...):
        async def _execute() -> dict:
            return await commands.submit(...)

        return await idempotent_command(
            db,
            organization_id=org_id,
            key=idempotency_key_header,
            request_payload=request_body,
            executor=_execute,
        )

A thin decorator with the same signature is fine once routes exist; this module
is the service primitive those routes will call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.exceptions import ConflictError
from app.models.base import utcnow
from app.models.identity import IdempotencyKey
from app.tenancy import set_config_local

_TENANT_GUCS = ("app.organization_id", "app.user_id", "app.request_id")


async def _snapshot_tenant_gucs(db: AsyncSession) -> dict[str, str]:
    """Capture transaction-local tenant context before a mid-command commit.

    ``SET LOCAL`` state dies with the transaction; commands that commit their
    idempotency claim before executing must restore it or every subsequent
    tenant-scoped statement runs blind under forced RLS (observed as 404s).
    """
    values: dict[str, str] = {}
    for guc in _TENANT_GUCS:
        result = await db.execute(text("SELECT current_setting(:name, true)"), {"name": guc})
        value = result.scalar_one_or_none()
        if value:
            values[guc] = value
    return values


async def _rebind_tenant_gucs(db: AsyncSession, values: dict[str, str]) -> None:
    for guc, value in values.items():
        await set_config_local(db, guc, value)


Executor = Callable[[], Awaitable[dict[str, Any]]]


def compute_request_hash(payload: dict) -> str:
    """Return SHA-256 hex digest of canonical JSON for ``payload``.

    Canonical form uses ``sort_keys=True`` and stable separators ``(",", ":")``.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def idempotent_command(
    db: AsyncSession,
    *,
    organization_id: UUID,
    key: str,
    request_payload: dict,
    executor: Executor,
    ttl_hours: int = 72,
) -> dict[str, Any]:
    """Run ``executor`` at most once per (organization_id, key) within the TTL.

    Semantics (ADR 0008 §6, model statuses ``in_progress`` / ``succeeded`` /
    ``failed``):

    * First claim inserts ``in_progress``, runs ``executor``, stores
      ``response_snapshot`` + ``succeeded`` on success.
    * Same key + same payload + ``succeeded`` → replay snapshot (no re-exec).
    * Same key + same payload + ``in_progress`` → ``ConflictError`` (retryable;
      callers may retry later).
    * Same key + same payload + ``failed`` → reset lease and re-execute.
    * Same key + different payload → ``ConflictError`` (409 payload mismatch).
    * Expired row (``expires_at`` < now) → reset lease and re-execute.
    * Concurrent callers: INSERT race decides the winner; the loser follows the
      row-exists path (replay or in-progress conflict).

    Transactional choice for executor failures
    ------------------------------------------
    The ``in_progress`` claim is **committed before** ``executor`` runs so
    concurrent callers can observe the lease and so the failure marker survives
    a later session rollback. If ``executor`` raises, this session is rolled
    back (undoing any uncommitted executor side effects), then the idempotency
    row is updated to ``failed`` in a fresh transaction and committed before the
    exception is re-raised.
    """
    request_hash = compute_request_hash(request_payload)
    expires_at = utcnow() + timedelta(hours=ttl_hours)

    claimed_id = await _try_claim(
        db,
        organization_id=organization_id,
        key=key,
        request_hash=request_hash,
        expires_at=expires_at,
    )
    if claimed_id is not None:
        gucs = await _snapshot_tenant_gucs(db)
        await db.commit()
        await _rebind_tenant_gucs(db, gucs)
        return await _execute_claimed(db, row_id=claimed_id, executor=executor)

    row = await _load_row(db, organization_id=organization_id, key=key, for_update=True)
    if row is None:
        # Rare: row vanished between conflict and load (TTL cleanup). Reclaim.
        claimed_id = await _try_claim(
            db,
            organization_id=organization_id,
            key=key,
            request_hash=request_hash,
            expires_at=expires_at,
        )
        if claimed_id is None:
            await db.rollback()
            raise ConflictError("command in progress")
        gucs = await _snapshot_tenant_gucs(db)
        await db.commit()
        await _rebind_tenant_gucs(db, gucs)
        return await _execute_claimed(db, row_id=claimed_id, executor=executor)

    now = utcnow()
    if row.expires_at < now:
        await _reset_lease(
            db,
            row,
            request_hash=request_hash,
            expires_at=expires_at,
        )
        gucs = await _snapshot_tenant_gucs(db)
        await db.commit()
        await _rebind_tenant_gucs(db, gucs)
        return await _execute_claimed(db, row_id=row.id, executor=executor)

    if row.request_hash != request_hash:
        await db.rollback()
        raise ConflictError("Idempotency key reused with a different request payload.")

    if row.status == "succeeded":
        snapshot = row.response_snapshot
        await db.commit()
        if snapshot is None:
            raise ConflictError("Idempotency snapshot missing for succeeded key.")
        return snapshot

    if row.status == "in_progress":
        await db.rollback()
        raise ConflictError("command in progress")

    if row.status == "failed":
        await _reset_lease(
            db,
            row,
            request_hash=request_hash,
            expires_at=expires_at,
        )
        gucs = await _snapshot_tenant_gucs(db)
        await db.commit()
        await _rebind_tenant_gucs(db, gucs)
        return await _execute_claimed(db, row_id=row.id, executor=executor)

    await db.rollback()
    raise ConflictError(f"Unexpected idempotency status: {row.status}")


async def _try_claim(
    db: AsyncSession,
    *,
    organization_id: UUID,
    key: str,
    request_hash: str,
    expires_at,
) -> UUID | None:
    """Insert ``in_progress`` row; return id if this caller won the claim.

    Uses INSERT … ON CONFLICT DO NOTHING inside a SAVEPOINT so a conflict does
    not poison the outer session transaction.
    """
    table = IdempotencyKey.__table__
    stmt = (
        pg_insert(table)
        .values(
            organization_id=organization_id,
            key=key,
            request_hash=request_hash,
            status="in_progress",
            expires_at=expires_at,
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_keys_organization_id_key")
        .returning(table.c.id)
    )
    async with db.begin_nested():
        result = await db.execute(stmt)
        row = result.first()
    return None if row is None else row.id


async def _load_row(
    db: AsyncSession,
    *,
    organization_id: UUID,
    key: str,
    for_update: bool = False,
) -> IdempotencyKey | None:
    stmt = select(IdempotencyKey).where(
        IdempotencyKey.organization_id == organization_id,
        IdempotencyKey.key == key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _reset_lease(
    db: AsyncSession,
    row: IdempotencyKey,
    *,
    request_hash: str,
    expires_at,
) -> None:
    row.request_hash = request_hash
    row.status = "in_progress"
    row.response_snapshot = None
    row.expires_at = expires_at
    await db.flush()


async def _execute_claimed(
    db: AsyncSession,
    *,
    row_id: UUID,
    executor: Executor,
) -> dict[str, Any]:
    # Capture GUCs before executor runs: executor commit/rollback drops SET LOCAL.
    gucs = await _snapshot_tenant_gucs(db)
    try:
        snapshot = await executor()
    except Exception:
        await db.rollback()
        # Rollback cleared tenant GUCs; rebind before any idempotency_keys touch.
        await _rebind_tenant_gucs(db, gucs)
        row = await db.get(IdempotencyKey, row_id)
        if row is not None:
            row.status = "failed"
            await db.commit()
        raise

    # Executor may have committed (dropping SET LOCAL); rebind before get+UPDATE.
    await _rebind_tenant_gucs(db, gucs)
    row = await db.get(IdempotencyKey, row_id)
    if row is None:
        raise ConflictError("Idempotency key disappeared during execution.")
    row.status = "succeeded"
    row.response_snapshot = snapshot
    await db.commit()
    return snapshot
