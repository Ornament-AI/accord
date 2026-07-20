"""Report test fixtures: keep identity tables clean between report tests.

Report tests seed and COMMIT their own organization per test. With the
singleton-organization unique index (``uq_organizations_singleton``), a
leftover org committed by a prior test collides on the next insert, so
truncate identity tables before each test (CASCADE clears dependent org data).
This mirrors the autouse cleanup used by the e2e/api/services/gate_d suites.
"""

from __future__ import annotations

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _autouse_clean_identity_tables(clean_identity_tables):
    """TRUNCATE identity tables before each report test (CASCADE clears org data)."""
    yield
