"""Repair migration backfills audit columns on DBs that skipped e6a8c4d2f901."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from tests.migrations.conftest import run_alembic


def test_ensure_audit_history_extension_backfills_skipped_columns(scratch_db: str) -> None:
    assert run_alembic(scratch_db, "upgrade", "b2e7f4a1c093").returncode == 0

    engine = create_engine(scratch_db.replace("+asyncpg", "+psycopg"))
    # Simulate the drift seen in local DBs: alembic at/after e6a8 without its DDL.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS event_kind"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS actor_snapshot"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS entity_label"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS before_state"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS after_state"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS metadata"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS idempotency_key"))
        conn.execute(text("ALTER TABLE audit_events DROP COLUMN IF EXISTS changed_count"))
        conn.execute(
            text("ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS ck_audit_events_event_kind")
        )
        conn.execute(text("DROP INDEX IF EXISTS ix_audit_events_org_request_id"))

    assert run_alembic(scratch_db, "upgrade", "c9f2e4a8b013").returncode == 0

    columns = {column["name"] for column in inspect(engine).get_columns("audit_events")}
    assert {
        "event_kind",
        "actor_snapshot",
        "entity_label",
        "before_state",
        "after_state",
        "metadata",
        "idempotency_key",
        "changed_count",
    }.issubset(columns)
    indexes = {index["name"] for index in inspect(engine).get_indexes("audit_events")}
    assert "ix_audit_events_org_request_id" in indexes

    # Idempotent on databases that already have the extension.
    assert run_alembic(scratch_db, "upgrade", "head").returncode == 0
