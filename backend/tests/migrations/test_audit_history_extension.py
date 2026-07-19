from __future__ import annotations

from sqlalchemy import create_engine, inspect

from tests.migrations.conftest import run_alembic


def test_audit_history_extension_upgrade_downgrade(scratch_db: str) -> None:
    assert run_alembic(scratch_db, "upgrade", "f4b7c1d9e205").returncode == 0
    assert run_alembic(scratch_db, "upgrade", "e6a8c4d2f901").returncode == 0

    engine = create_engine(scratch_db.replace("+asyncpg", "+psycopg"))
    columns = {column["name"]: column for column in inspect(engine).get_columns("audit_events")}
    assert columns["event_kind"]["nullable"] is True
    assert columns["before_state"]["nullable"] is True
    assert columns["after_state"]["nullable"] is True
    assert columns["actor_snapshot"]["nullable"] is True
    assert columns["entity_label"]["nullable"] is True
    assert columns["metadata"]["nullable"] is False
    assert columns["changed_count"]["nullable"] is False
    indexes = {index["name"] for index in inspect(engine).get_indexes("audit_events")}
    assert "ix_audit_events_org_request_id" in indexes

    assert run_alembic(scratch_db, "downgrade", "f4b7c1d9e205").returncode == 0
    downgraded = {column["name"] for column in inspect(engine).get_columns("audit_events")}
    assert "event_kind" not in downgraded
    assert "before_state" not in downgraded
