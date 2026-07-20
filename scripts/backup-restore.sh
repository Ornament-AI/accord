#!/usr/bin/env bash
# Accord Postgres backup / scratch-restore rehearsal helper.
#
# Creates a custom-format pg_dump from a running compose Postgres container,
# then optionally restores into a scratch database and prints row counts for a
# verification table so operators can confirm data survived.
#
# Usage (from repo root):
#   ./scripts/backup-restore.sh backup \
#     --container accord-postgres-1 --db accord --user accord \
#     --password "$ACCORD_DB_PASSWORD" --out /tmp/accord.dump
#
#   ./scripts/backup-restore.sh restore-scratch \
#     --container accord-postgres-1 --db accord --user accord \
#     --password "$ACCORD_DB_PASSWORD" --dump /tmp/accord.dump \
#     --scratch accord_restore_scratch --verify-table rehearsal_probe
#
#   ./scripts/backup-restore.sh verify-counts \
#     --container accord-postgres-1 --db accord --user accord \
#     --password "$ACCORD_DB_PASSWORD" --verify-table rehearsal_probe
#
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  backup-restore.sh backup --container NAME --db NAME --user NAME --password SECRET --out PATH
  backup-restore.sh restore-scratch --container NAME --db NAME --user NAME --password SECRET \
      --dump PATH --scratch NAME [--verify-table TABLE]
  backup-restore.sh verify-counts --container NAME --db NAME --user NAME --password SECRET \
      --verify-table TABLE

Environment overrides (optional): ACCORD_PG_CONTAINER, ACCORD_DB_NAME, ACCORD_DB_USER,
ACCORD_DB_PASSWORD, ACCORD_BACKUP_OUT, ACCORD_SCRATCH_DB, ACCORD_VERIFY_TABLE.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

COMMAND="${1:-}"
if [[ -z "$COMMAND" || "$COMMAND" == "-h" || "$COMMAND" == "--help" ]]; then
  usage
  exit 0
fi
shift

CONTAINER="${ACCORD_PG_CONTAINER:-accord-postgres-1}"
DB_NAME="${ACCORD_DB_NAME:-accord}"
DB_USER="${ACCORD_DB_USER:-accord}"
DB_PASSWORD="${ACCORD_DB_PASSWORD:-}"
OUT_PATH="${ACCORD_BACKUP_OUT:-}"
DUMP_PATH=""
SCRATCH_DB="${ACCORD_SCRATCH_DB:-accord_restore_scratch}"
VERIFY_TABLE="${ACCORD_VERIFY_TABLE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --container) CONTAINER="${2:-}"; shift 2 ;;
    --db) DB_NAME="${2:-}"; shift 2 ;;
    --user) DB_USER="${2:-}"; shift 2 ;;
    --password) DB_PASSWORD="${2:-}"; shift 2 ;;
    --out) OUT_PATH="${2:-}"; shift 2 ;;
    --dump) DUMP_PATH="${2:-}"; shift 2 ;;
    --scratch) SCRATCH_DB="${2:-}"; shift 2 ;;
    --verify-table) VERIFY_TABLE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$CONTAINER" ]] || die "--container is required"
[[ -n "$DB_NAME" ]] || die "--db is required"
[[ -n "$DB_USER" ]] || die "--user is required"
[[ -n "$DB_PASSWORD" ]] || die "--password (or ACCORD_DB_PASSWORD) is required"

docker inspect "$CONTAINER" >/dev/null 2>&1 || die "container not found: $CONTAINER"

pg_exec() {
  local db="$1"
  shift
  docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
    psql -U "$DB_USER" -d "$db" -v ON_ERROR_STOP=1 "$@"
}

count_rows() {
  local db="$1"
  local table="$2"
  docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
    psql -U "$DB_USER" -d "$db" -tAc "SELECT count(*) FROM ${table};"
}

case "$COMMAND" in
  backup)
    [[ -n "$OUT_PATH" ]] || die "--out is required for backup"
    mkdir -p "$(dirname "$OUT_PATH")"
    echo "[backup] dumping ${DB_NAME} from ${CONTAINER} → ${OUT_PATH}"
    docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
      pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner --no-acl \
      >"$OUT_PATH"
    [[ -s "$OUT_PATH" ]] || die "dump file empty: $OUT_PATH"
    echo "[backup] ok bytes=$(wc -c <"$OUT_PATH" | tr -d ' ')"
    if [[ -n "$VERIFY_TABLE" ]]; then
      before="$(count_rows "$DB_NAME" "$VERIFY_TABLE")"
      echo "[backup] ${VERIFY_TABLE} row_count=${before}"
    fi
    ;;

  verify-counts)
    [[ -n "$VERIFY_TABLE" ]] || die "--verify-table is required for verify-counts"
    count="$(count_rows "$DB_NAME" "$VERIFY_TABLE")"
    echo "[verify] db=${DB_NAME} table=${VERIFY_TABLE} row_count=${count}"
    ;;

  restore-scratch)
    [[ -n "$DUMP_PATH" ]] || die "--dump is required for restore-scratch"
    [[ -f "$DUMP_PATH" ]] || die "dump not found: $DUMP_PATH"
    [[ "$SCRATCH_DB" != "$DB_NAME" ]] || die "--scratch must differ from --db"

    before=""
    if [[ -n "$VERIFY_TABLE" ]]; then
      before="$(count_rows "$DB_NAME" "$VERIFY_TABLE")"
      echo "[restore] source ${VERIFY_TABLE} row_count_before=${before}"
    fi

    echo "[restore] drop+create scratch database ${SCRATCH_DB}"
    pg_exec postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${SCRATCH_DB}' AND pid <> pg_backend_pid();" >/dev/null || true
    pg_exec postgres -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";"
    pg_exec postgres -c "CREATE DATABASE \"${SCRATCH_DB}\" OWNER \"${DB_USER}\";"

    echo "[restore] pg_restore → ${SCRATCH_DB}"
    # Copy dump into the container so pg_restore can read it locally.
    remote_dump="/tmp/accord-restore-$$.dump"
    docker cp "$DUMP_PATH" "${CONTAINER}:${remote_dump}"
    docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
      pg_restore -U "$DB_USER" -d "$SCRATCH_DB" --no-owner --no-acl --clean --if-exists \
      "$remote_dump"
    docker exec "$CONTAINER" rm -f "$remote_dump"

    if [[ -n "$VERIFY_TABLE" ]]; then
      after="$(count_rows "$SCRATCH_DB" "$VERIFY_TABLE")"
      echo "[restore] scratch ${VERIFY_TABLE} row_count_after=${after}"
      if [[ -n "$before" && "$before" != "$after" ]]; then
        die "row count mismatch: before=${before} after=${after}"
      fi
      echo "[restore] row counts match (${after})"
    fi
    echo "[restore] ok"
    ;;

  *)
    die "unknown command: $COMMAND (expected backup|restore-scratch|verify-counts)"
    ;;
esac
