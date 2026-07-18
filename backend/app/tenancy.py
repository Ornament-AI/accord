"""Transaction-local tenant context helpers (ADR-0001).

Accord binds tenant scope via PostgreSQL GUCs that are **transaction-local**:

* ``app.organization_id``
* ``app.user_id``
* ``app.request_id``

These are set with ``SELECT set_config(name, value, true)`` where the third
argument ``true`` means *is_local* — equivalent to ``SET LOCAL``. That matters
because Accord uses a pooled asyncpg engine:

(a) ``SET LOCAL`` / ``set_config(..., true)`` auto-clears at transaction end
    (COMMIT or ROLLBACK). No explicit reset call is needed, and relying on a
    post-request ``RESET`` would be racy with pool reuse.

(b) Pooled asyncpg connections MUST NEVER receive tenant context via plain
    session-scoped ``SET`` / ``set_config(..., false)``. A leaked GUC would
    bleed into the next tenant's request on the same pooled connection.

(c) ``tenant_context`` does **not** commit or roll back the session. The caller
    owns transaction boundaries; this helper only issues the ``set_config``
    calls inside the session's current transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

_SET_CONFIG = text("SELECT set_config(:name, :value, true)")


async def set_config_local(
    target: AsyncSession | AsyncConnection,
    name: str,
    value: str,
) -> None:
    """Set a transaction-local GUC via bound parameters (SQL-injection-safe)."""
    await target.execute(_SET_CONFIG, {"name": name, "value": value})


async def bind_tenant_context(
    target: AsyncSession | AsyncConnection,
    *,
    organization_id: str | uuid.UUID,
    user_id: str | uuid.UUID | None = None,
    request_id: str | None = None,
) -> None:
    """Issue the ADR-0001 ``set_config(..., true)`` calls on ``target``.

    Does not begin/commit/rollback — must run inside an open transaction.
    """
    await set_config_local(target, "app.organization_id", str(organization_id))
    if user_id is not None:
        await set_config_local(target, "app.user_id", str(user_id))
    if request_id is not None:
        await set_config_local(target, "app.request_id", request_id)


@asynccontextmanager
async def tenant_context(
    session: AsyncSession,
    *,
    organization_id: str | uuid.UUID,
    user_id: str | uuid.UUID | None = None,
    request_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Bind tenant GUCs for the remainder of the current transaction, then yield.

    See module docstring for SET LOCAL / pool-safety invariants. The caller
    controls commit/rollback; this context manager never closes the transaction.
    """
    # Ensure we are inside a transaction so set_config(..., true) sticks until
    # COMMIT/ROLLBACK rather than being a no-op outside a transaction block.
    if not session.in_transaction():
        await session.begin()

    await bind_tenant_context(
        session,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
    )
    yield session
