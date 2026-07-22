"""A fresh database must upgrade cleanly to ``head``."""

from __future__ import annotations

import psycopg

from .conftest import as_psycopg_url, diag, run_alembic

HEAD_REVISION = "a7d3e5f9b102"
PREVIOUS_REVISION = "c9f2e4a8b013"


def _alembic_version(database_url: str) -> str | None:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else row[0]


def _extension_exists(database_url: str, name: str) -> bool:
    with psycopg.connect(as_psycopg_url(database_url)) as conn:
        return (
            conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = %s)",
                (name,),
            ).fetchone()[0]
            is True
        )


def _parse_heads(stdout: str) -> set[str]:
    heads: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # e.g. "c8d4e2f1a9b7 (head)"
        rev = line.split()[0]
        heads.add(rev)
    return heads


def test_fresh_database_upgrades_to_head(scratch_db: str) -> None:
    result = run_alembic(scratch_db, "upgrade", "head")
    assert result.returncode == 0, diag("alembic upgrade head on fresh DB", result)

    heads = run_alembic(scratch_db, "heads")
    assert heads.returncode == 0, diag("alembic heads", heads)
    head_revs = _parse_heads(heads.stdout)
    assert head_revs == {HEAD_REVISION}

    assert _alembic_version(scratch_db) == HEAD_REVISION
    assert _extension_exists(scratch_db, "btree_gist")
    assert not _extension_exists(scratch_db, "pgcrypto")

    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after upgrade head", check)


def test_initial_migration_upgrade_downgrade_upgrade_roundtrip(scratch_db: str) -> None:
    """Round-trip: ``base -> head -> base -> head``."""
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("upgrade #1", up)
    assert _alembic_version(scratch_db) == HEAD_REVISION
    assert _extension_exists(scratch_db, "btree_gist")

    down = run_alembic(scratch_db, "downgrade", "base")
    assert down.returncode == 0, diag("downgrade base", down)
    assert _alembic_version(scratch_db) is None
    assert not _extension_exists(scratch_db, "btree_gist")

    up2 = run_alembic(scratch_db, "upgrade", "head")
    assert up2.returncode == 0, diag("upgrade #2", up2)
    assert _alembic_version(scratch_db) == HEAD_REVISION
    assert _extension_exists(scratch_db, "btree_gist")

    heads = run_alembic(scratch_db, "heads")
    assert heads.returncode == 0, diag("alembic heads after roundtrip", heads)
    assert _parse_heads(heads.stdout) == {HEAD_REVISION}
    assert _alembic_version(scratch_db) in _parse_heads(heads.stdout)

    check = run_alembic(scratch_db, "check")
    assert check.returncode == 0, diag("alembic check after roundtrip", check)


def test_report_export_migration_backfills_existing_organization_catalog(
    scratch_db: str,
) -> None:
    up = run_alembic(scratch_db, "upgrade", PREVIOUS_REVISION)
    assert up.returncode == 0, diag(f"upgrade {PREVIOUS_REVISION}", up)

    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        organization_id = conn.execute(
            "INSERT INTO organizations (name, slug) VALUES (%s, %s) RETURNING id",
            ("Existing Organization", "existing-org"),
        ).fetchone()[0]

    head = run_alembic(scratch_db, "upgrade", "head")
    assert head.returncode == 0, diag("upgrade report export migration", head)

    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        rows = conn.execute(
            "SELECT code, classification, is_standard, schedule_kind "
            "FROM pay_components WHERE organization_id = %s",
            (organization_id,),
        ).fetchall()
    catalog = {row[0]: row[1:] for row in rows}
    assert len(catalog) == 26
    assert catalog["ADDITIONAL_ALLOWANCE"][:2] == ("earning", True)
    assert catalog["CLA"] == ("earning", True, None)
    assert catalog["FOREGONE_HRA"] == ("informational", True, None)
    assert catalog["MOTOR_CAR_ADVANCE_INSTALLMENT"] == (
        "external_recovery",
        True,
        "loan_installment",
    )
