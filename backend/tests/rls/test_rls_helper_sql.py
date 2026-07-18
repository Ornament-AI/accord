"""String-shape assertions for ADR-0001 ``rls_policy_sql`` helper."""

from __future__ import annotations

from app.models.base import rls_policy_sql


def test_rls_policy_sql_matches_adr_0001_pattern() -> None:
    sql = rls_policy_sql("employees")

    assert "ALTER TABLE employees ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE employees FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY tenant_isolation ON employees" in sql
    assert "FOR ALL" in sql
    assert "TO accord_app" in sql
    assert "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid" in sql
    assert "WITH CHECK" in sql
    assert sql.count("NULLIF(current_setting('app.organization_id', true), '')::uuid") == 2


def test_rls_policy_sql_accepts_role_and_policy_name_overrides() -> None:
    sql = rls_policy_sql(
        "idempotency_keys",
        role="accord_worker",
        policy_name="tenant_isolation_worker",
    )
    assert "ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY tenant_isolation_worker ON idempotency_keys" in sql
    assert "TO accord_worker" in sql
