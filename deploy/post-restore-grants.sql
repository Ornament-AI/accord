-- Accord post-restore grant posture (ADR-0001 roles + ADR-0009 immutability).
--
-- Apply to a database AFTER pg_restore to re-assert the exact runtime grant
-- posture the application expects. pg_dump archives taken with --no-acl (or
-- restores into databases with different default privileges) otherwise leave
-- runtime roles with either no access or full DML on immutable tables.
--
-- Idempotent: safe to re-run. Roles must already exist (deploy/create_roles.sql).
-- Run as a superuser or the database owner:
--   psql -d accord -f deploy/post-restore-grants.sql

-- Schema + table DML the runtime roles rely on (mirrors the ALTER DEFAULT
-- PRIVILEGES set in create_roles.sql, applied to already-restored objects).
GRANT USAGE ON SCHEMA public TO accord_app, accord_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO accord_app, accord_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO accord_app, accord_worker;

-- alembic_version is migration bookkeeping: runtime roles must not be able to
-- rewrite version_num (it would let a compromised role re-run/skip migrations).
REVOKE ALL ON TABLE alembic_version FROM accord_app, accord_worker;

-- ADR-0009 immutability backstop: insert-and-read only on append-only tables.
-- Matches migrations b33a3a7b5f84, f2a7c9d4e601, and a9f3c2e81b04.
REVOKE ALL ON TABLE audit_events FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events
  FROM accord_app, accord_worker;
REVOKE ALL ON TABLE outbox_events FROM PUBLIC;
REVOKE DELETE, TRUNCATE ON TABLE outbox_events
  FROM accord_app, accord_worker;
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE
  payroll_run_versions,
  payroll_employee_results,
  payroll_result_lines,
  payroll_approvals,
  payroll_report_snapshots
  FROM accord_app, accord_worker;
