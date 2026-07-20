"""Migration coverage for ADR 0011 singleton org + invitations."""

from __future__ import annotations

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

HEAD_REVISION = "c9f2e4a8b013"
PREV_REVISION = "d7a2e4f6b809"


def _alembic_version(database_url: str) -> str | None:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else row[0]


def test_upgrade_head_has_singleton_index(scratch_db: str) -> None:
    result = run_alembic(scratch_db, "upgrade", "head")
    assert result.returncode == 0, diag("alembic upgrade head", result)
    assert _alembic_version(scratch_db) == HEAD_REVISION
    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check", check)
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        exists = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = %s)",
            ("uq_organizations_singleton",),
        ).fetchone()[0]
        assert exists is True
        tables = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'organization_invitations')"
        ).fetchone()[0]
        assert tables is True


def test_populated_one_org_upgrades(scratch_db: str) -> None:
    # Land at previous revision without singleton index
    down = run_alembic(scratch_db, "upgrade", PREV_REVISION)
    assert down.returncode == 0, diag("upgrade to prev", down)
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute("TRUNCATE organizations CASCADE")
        conn.execute(
            "INSERT INTO organizations (name, slug, is_active) VALUES ('Only', 'only', true)"
        )
        conn.commit()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("upgrade populated-one", up)
    assert _alembic_version(scratch_db) == HEAD_REVISION
    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after populated-one", check)


def test_multi_row_preflight_fails_with_message(scratch_db: str) -> None:
    down = run_alembic(scratch_db, "upgrade", PREV_REVISION)
    assert down.returncode == 0, diag("upgrade to prev", down)
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute("TRUNCATE organizations CASCADE")
        conn.execute(
            "INSERT INTO organizations (name, slug, is_active) VALUES "
            "('A', 'org-a', true), ('B', 'org-b', true)"
        )
        conn.commit()
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode != 0
    combined = (up.stdout or "") + (up.stderr or "")
    assert "Refusing to create singleton organization index" in combined
    # Repair for fixture teardown / subsequent tests sharing nothing — scratch is per-test
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        conn.execute("TRUNCATE organizations CASCADE")
        conn.commit()
    repair = run_alembic(scratch_db, "upgrade", "head")
    assert repair.returncode == 0, diag("repair upgrade", repair)


def test_downgrade_removes_singleton_artifacts(scratch_db: str) -> None:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("upgrade head", up)
    down = run_alembic(scratch_db, "downgrade", PREV_REVISION)
    assert down.returncode == 0, diag("downgrade", down)
    assert _alembic_version(scratch_db) == PREV_REVISION
    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        exists = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = %s)",
            ("uq_organizations_singleton",),
        ).fetchone()[0]
        assert exists is False
        tables = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'organization_invitations')"
        ).fetchone()[0]
        assert tables is False
