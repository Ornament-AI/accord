"""WorkOS webhook signature verification and durable replay tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.models.identity import User
from app.models.platform import WebhookEvent
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


@pytest_asyncio.fixture(autouse=True)
async def _clean_webhook_events(session):
    """Truncate durable dedup rows; identity cleanup does not cover this table."""
    await session.execute(text("TRUNCATE TABLE webhook_events RESTART IDENTITY CASCADE"))
    await session.commit()
    yield


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
async def test_webhook_valid_signature_returns_200(client, webhook_settings, session):
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

    session.expire_all()
    row = (
        await session.execute(select(WebhookEvent).where(WebhookEvent.event_id == "evt_valid_1"))
    ).scalar_one()
    assert row.provider == "workos"
    assert row.event_type == "ping"
    assert row.payload_digest == hashlib.sha256(body).hexdigest()
    assert row.processed_at is not None


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_401(client, webhook_settings, session):
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

    session.expire_all()
    count = (await session.execute(select(func.count()).select_from(WebhookEvent))).scalar_one()
    assert count == 0


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

    rows_after_first = (
        (await session.execute(select(WebhookEvent).where(WebhookEvent.event_id == "evt_replay_1")))
        .scalars()
        .all()
    )
    assert len(rows_after_first) == 1
    assert rows_after_first[0].provider == "workos"
    assert rows_after_first[0].event_type == "user.updated"
    assert rows_after_first[0].payload_digest == hashlib.sha256(body).hexdigest()
    assert rows_after_first[0].processed_at is not None

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

    rows_after_replay = (
        (await session.execute(select(WebhookEvent).where(WebhookEvent.event_id == "evt_replay_1")))
        .scalars()
        .all()
    )
    assert len(rows_after_replay) == 1


@pytest.mark.asyncio
async def test_webhook_different_event_id_processes_and_creates_second_row(
    client, webhook_settings, session
):
    user = User(
        workos_user_id="wh_user_2",
        email="alice@example.com",
        name="Alice",
    )
    session.add(user)
    await session.commit()
    user_id = user.id

    first_payload = {
        "id": "evt_diff_1",
        "event": "user.updated",
        "data": {
            "id": "wh_user_2",
            "email": "alice1@example.com",
            "name": "Alice One",
        },
    }
    first_body = json.dumps(first_payload).encode()
    first = await client.post(
        "/api/auth/webhooks/workos",
        content=first_body,
        headers={
            "Content-Type": "application/json",
            "WorkOS-Signature": _sign(first_body, webhook_settings.workos_webhook_secret),
        },
    )
    assert first.status_code == 200

    second_payload = {
        "id": "evt_diff_2",
        "event": "user.updated",
        "data": {
            "id": "wh_user_2",
            "email": "alice2@example.com",
            "name": "Alice Two",
        },
    }
    second_body = json.dumps(second_payload).encode()
    second = await client.post(
        "/api/auth/webhooks/workos",
        content=second_body,
        headers={
            "Content-Type": "application/json",
            "WorkOS-Signature": _sign(second_body, webhook_settings.workos_webhook_secret),
        },
    )
    assert second.status_code == 200

    session.expire_all()
    refreshed = await session.get(User, user_id)
    assert refreshed is not None
    assert refreshed.email == "alice2@example.com"
    assert refreshed.name == "Alice Two"

    rows = (
        (
            await session.execute(
                select(WebhookEvent)
                .where(WebhookEvent.event_id.in_(["evt_diff_1", "evt_diff_2"]))
                .order_by(WebhookEvent.event_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0].event_id == "evt_diff_1"
    assert rows[0].payload_digest == hashlib.sha256(first_body).hexdigest()
    assert rows[0].processed_at is not None
    assert rows[1].event_id == "evt_diff_2"
    assert rows[1].payload_digest == hashlib.sha256(second_body).hexdigest()
    assert rows[1].processed_at is not None
