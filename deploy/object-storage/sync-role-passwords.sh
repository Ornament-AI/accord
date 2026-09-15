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
psql -v ON_ERROR_STOP=1 \
  --host postgres --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_PASSWORD" \
  -v worker_password="$WORKER_PASSWORD" \
  -v migrator_password="$MIGRATOR_PASSWORD" <<'EOSQL'
ALTER ROLE accord_migrator WITH PASSWORD :'migrator_password';
ALTER ROLE accord_app WITH PASSWORD :'app_password';
ALTER ROLE accord_worker WITH PASSWORD :'worker_password';
EOSQL

echo "[sync-role-passwords] ADR role passwords reconciled"
