"""HTTP organization create is removed (ADR 0011).

Bootstrap coverage lives in ``tests/services/test_bootstrap_organization.py``
(``app.services.bootstrap.provision_organization``, CLI-only).
Member provisioning is CLI-only via ``scripts/provision_member.py``.
"""

from __future__ import annotations

import pytest

from tests.identity_helpers import login_dev


@pytest.mark.asyncio
async def test_post_organizations_http_path_removed(client, dev_settings):
    await login_dev(client)
    resp = await client.post(
        "/api/organizations",
        json={"name": "Acme Payroll", "slug": "acme-payroll"},
    )
    assert resp.status_code in {404, 405}
