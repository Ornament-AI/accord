"""Catch-all RLS coverage proof (T1.17).

Per-table RLS test lists (``TENANT_RLS_TABLES`` etc.) can silently miss a new
tenant table — ``organization_invitations``, ``payroll_run_employees``, and
``payroll_report_snapshots`` were absent from every list for a while. This test
derives the set from ``information_schema`` instead: **every** public table
carrying an ``organization_id`` column must have row security enabled AND
forced AND at least one policy granting ``accord_app`` access.
"""

from __future__ import annotations

import psycopg

from tests.migrations.conftest import as_psycopg_url, diag, run_alembic

_ORG_COLUMN_TABLES_SQL = """
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
  AND EXISTS (
      SELECT 1 FROM information_schema.columns ic
      WHERE ic.table_schema = 'public'
        AND ic.table_name = c.relname
        AND ic.column_name = 'organization_id'
  )
ORDER BY c.relname
"""

_APP_POLICY_SQL = """
SELECT COUNT(*) FROM pg_policies
WHERE schemaname = 'public' AND tablename = %s
  AND 'accord_app' = ANY(roles)
"""


def test_every_org_column_table_has_forced_rls_and_app_policy(scratch_db: str) -> None:
    up = run_alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, diag("alembic upgrade head", up)

    with psycopg.connect(as_psycopg_url(scratch_db)) as conn:
        rows = conn.execute(_ORG_COLUMN_TABLES_SQL).fetchall()
        assert rows, "expected tenant tables with an organization_id column"
        for relname, rowsecurity, forced in rows:
            assert rowsecurity, f"{relname}: expected relrowsecurity"
            assert forced, f"{relname}: expected relforcerowsecurity"
            policy_count = conn.execute(_APP_POLICY_SQL, (relname,)).fetchone()[0]
            assert policy_count >= 1, f"{relname}: no policy covering accord_app"
