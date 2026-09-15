#!/bin/sh
# First-boot Postgres init (docker-entrypoint-initdb.d): create ADR-0001 roles
# from backend/scripts/create_roles.sql, set passwords, and grant schema/DB access
# so the one-shot migrations service can reach alembic head under accord_migrator.
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

# Per-role passwords; each falls back to the shared ACCORD_ROLE_PASSWORD, then
# the Postgres superuser password, so existing deployments keep working.
APP_PASSWORD="${ACCORD_APP_PASSWORD:-${ACCORD_ROLE_PASSWORD:-$POSTGRES_PASSWORD}}"
WORKER_PASSWORD="${ACCORD_WORKER_PASSWORD:-${ACCORD_ROLE_PASSWORD:-$POSTGRES_PASSWORD}}"
MIGRATOR_PASSWORD="${ACCORD_MIGRATOR_PASSWORD:-${ACCORD_ROLE_PASSWORD:-$POSTGRES_PASSWORD}}"
ROLES_SQL="${ACCORD_CREATE_ROLES_SQL:-/roles/create_roles.sql}"

echo "[postgres-init-roles] applying $ROLES_SQL"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$ROLES_SQL"

echo "[postgres-init-roles] setting role passwords and grants"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_PASSWORD" \
  -v worker_password="$WORKER_PASSWORD" \
  -v migrator_password="$MIGRATOR_PASSWORD" \
  -v db_name="$POSTGRES_DB" <<'EOSQL'
ALTER ROLE accord_migrator WITH PASSWORD :'migrator_password';
ALTER ROLE accord_app WITH PASSWORD :'app_password';
ALTER ROLE accord_worker WITH PASSWORD :'worker_password';
GRANT ALL ON SCHEMA public TO accord_migrator;
GRANT USAGE ON SCHEMA public TO accord_app, accord_worker;
GRANT CONNECT ON DATABASE :"db_name" TO accord_app, accord_migrator, accord_worker;
ALTER DATABASE :"db_name" OWNER TO accord_migrator;
EOSQL

echo "[postgres-init-roles] ADR roles ready (accord_migrator / accord_app / accord_worker)"
