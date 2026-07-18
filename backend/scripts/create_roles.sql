-- Accord database roles bootstrap (ADR-0001 section 4).
--
-- NOT run by Alembic. Apply manually (or via ops tooling) once per database
-- cluster / database before pointing app/migrator DSNs at these roles.
-- Safe to re-run: role creation is guarded; default-privilege grants are
-- additive and idempotent for the same privilege set.
--
-- REPLACE_WITH_SECRET: replace the placeholder passwords below (or ALTER ROLE
-- after creation) before any non-local use. Never commit real secrets.
--
-- Example with psql variables (optional):
--   psql -v migrator_password='...' -v app_password='...' -v worker_password='...' \
--     -f backend/scripts/create_roles.sql

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'accord_migrator') THEN
    -- Owns schema/tables; runs Alembic; may bypass RLS for DDL/data migrations.
    CREATE ROLE accord_migrator WITH
      LOGIN
      PASSWORD 'REPLACE_WITH_SECRET'  -- REPLACE_WITH_SECRET
      NOSUPERUSER
      NOCREATEDB
      NOCREATEROLE
      BYPASSRLS;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'accord_app') THEN
    -- Runtime API role: RLS always applies; DML only; does not own tables.
    CREATE ROLE accord_app WITH
      LOGIN
      PASSWORD 'REPLACE_WITH_SECRET'  -- REPLACE_WITH_SECRET
      NOSUPERUSER
      NOBYPASSRLS
      NOCREATEDB
      NOCREATEROLE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'accord_worker') THEN
    -- Background workers / jobs: same RLS constraint as accord_app.
    CREATE ROLE accord_worker WITH
      LOGIN
      PASSWORD 'REPLACE_WITH_SECRET'  -- REPLACE_WITH_SECRET
      NOSUPERUSER
      NOBYPASSRLS
      NOCREATEDB
      NOCREATEROLE;
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Schema usage + default privileges
--
-- Tables created later by accord_migrator automatically receive DML grants for
-- accord_app / accord_worker via ALTER DEFAULT PRIVILEGES. Individual Alembic
-- migrations therefore do not need per-table GRANT statements for the standard
-- SELECT/INSERT/UPDATE/DELETE set (still add narrower grants if a table
-- should not be fully writable by the worker role).
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA public TO accord_app, accord_worker;

ALTER DEFAULT PRIVILEGES FOR ROLE accord_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO accord_app, accord_worker;

ALTER DEFAULT PRIVILEGES FOR ROLE accord_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO accord_app, accord_worker;
