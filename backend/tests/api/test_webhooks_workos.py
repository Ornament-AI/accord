"""WorkOS webhook signature verification and replay tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.auth.webhooks import clear_webhook_dedup_cache
from app.models.identity import User
from tests.identity_helpers import clear_settings_cache, patch_get_settings, settings


def _sign(body: bytes, secret: str, ts_ms: int | None = None) -> str:
    """WorkOS header format: ``t=<ms>, v1=<hex>`` (comma-SPACE)."""
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    sig = hmac.new(
        secret.encode(),
        f"{ts}.{body.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts}, v1={sig}"


@pytest.fixture(autouse=True)
def _clear_dedup():
    clear_webhook_dedup_cache()
    yield
    clear_webhook_dedup_cache()


@pytest.fixture
def webhook_settings(monkeypatch):
    value = settings(
        workos_webhook_secret="whsec_test_secret",
        workos_webhook_tolerance_seconds=300,
        dev_auth_bypass=True,
    )
    patch_get_settings(monkeypatch, value)
    yield value
    clear_settings_cache()


@pytest.mark.asyncio
async def test_webhook_valid_signature_returns_200(client, webhook_settings):
    payload = {"id": "evt_valid_1", "event": "ping", "data": {}}
    body = json.dumps(payload).encode()
    resp = await client.post(
        "/api/auth/webhooks/workos",
        content=body,
        headers={
            "Content-Type": "application/json",
            "WorkOS-Signature": _sign(body, webhook_settings.workos_webhook_secret),
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_401(client, webhook_settings):
    body = json.dumps({"id": "evt_bad", "event": "ping"}).encode()
    resp = await client.post(
        "/api/auth/webhooks/workos",
        content=body,
        headers={
            "Content-Type": "application/json",
            "WorkOS-Signature": "t=1, v1=deadbeef",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "WebhookUnauthorized"


@pytest.mark.asyncio
async def test_webhook_stale_timestamp_returns_401(client, webhook_settings):
    body = json.dumps({"id": "evt_stale", "event": "ping"}).encode()
    stale_ms = int(time.time() * 1000) - (
        (webhook_settings.workos_webhook_tolerance_seconds + 60) * 1000
    )
    resp = await client.post(
        "/api/auth/webhooks/workos",
        content=body,
        headers={
            "Content-Type": "application/json",
            "WorkOS-Signature": _sign(body, webhook_settings.workos_webhook_secret, ts_ms=stale_ms),
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "WebhookUnauthorized"


@pytest.mark.asyncio
async def test_webhook_replay_same_event_id_is_noop(client, webhook_settings, session):
    user = User(
        workos_user_id="wh_user_1",
        email="before@example.com",
        name="Before",
    )
    session.add(user)
    await session.commit()
    user_id = user.id

    payload = {
        "id": "evt_replay_1",
        "event": "user.updated",
        "data": {
            "id": "wh_user_1",
            "email": "after@example.com",
            "name": "After Name",
        },
    }
    body = json.dumps(payload).encode()
    sig = _sign(body, webhook_settings.workos_webhook_secret)
    headers = {"Content-Type": "application/json", "WorkOS-Signature": sig}

    first = await client.post("/api/auth/webhooks/workos", content=body, headers=headers)
    assert first.status_code == 200

    session.expire_all()
    refreshed = await session.get(User, user_id)
    assert refreshed is not None
    assert refreshed.email == "after@example.com"
    first_updated_at = refreshed.updated_at

    # Replay with different payload email — must not apply (same event id).
    replay_payload = {
        "id": "evt_replay_1",
        "event": "user.updated",
        "data": {
            "id": "wh_user_1",
            "email": "replayed@example.com",
            "name": "Replayed",
        },
    }
    replay_body = json.dumps(replay_payload).encode()
    # Dedup keys on parsed event id after verify — signature must match body.
    replay_sig = _sign(replay_body, webhook_settings.workos_webhook_secret)
    second = await client.post(
        "/api/auth/webhooks/workos",
        content=replay_body,
        headers={"Content-Type": "application/json", "WorkOS-Signature": replay_sig},
    )
    assert second.status_code == 200

    session.expire_all()
    refreshed = await session.get(User, user_id)
    assert refreshed is not None
    assert refreshed.email == "after@example.com"
    assert refreshed.name == "After Name"
    assert refreshed.updated_at == first_updated_at
