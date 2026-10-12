#!/bin/sh
# Re-asserts ADR-0001 role passwords on every deploy. docker-entrypoint-initdb.d
# runs only on an empty volume, so rotating ACCORD_*_PASSWORD in .env would
# otherwise update the runtime DSNs while the roles keep stale credentials.
# Resolution mirrors postgres-init-roles.sh and the compose DSN defaults:
# per-role value -> ACCORD_ROLE_PASSWORD -> Postgres superuser password.
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

APP_PASSWORD="${ACCORD_APP_PASSWORD:-${ACCORD_ROLE_PASSWORD:-$POSTGRES_PASSWORD}}"
WORKER_PASSWORD="${ACCORD_WORKER_PASSWORD:-${ACCORD_ROLE_PASSWORD:-$POSTGRES_PASSWORD}}"
MIGRATOR_PASSWORD="${ACCORD_MIGRATOR_PASSWORD:-${ACCORD_ROLE_PASSWORD:-$POSTGRES_PASSWORD}}"

export PGPASSWORD="$POSTGRES_PASSWORD"

# Re-assert schema/default-privilege posture every deploy, not just passwords:
# a restore or manual change can silently drop runtime grants otherwise.
# create_roles.sql is idempotent (guarded CREATE ROLE + additive grants).
ROLES_SQL="${ACCORD_CREATE_ROLES_SQL:-/roles/create_roles.sql}"
if [ -f "$ROLES_SQL" ]; then
  psql -v ON_ERROR_STOP=1 \
    --host postgres --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -f "$ROLES_SQL"
fi

psql -v ON_ERROR_STOP=1 \
  --host postgres --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
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
EOSQL

echo "[sync-role-passwords] ADR role passwords + grants reconciled"
