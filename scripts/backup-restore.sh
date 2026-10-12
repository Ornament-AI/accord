#!/usr/bin/env bash
# Accord Postgres backup / scratch-restore rehearsal helper.
#
# Creates a custom-format pg_dump (with ACLs, so grants and the ADR-0009
# immutable-table revokes survive the round trip) from a running compose
# Postgres container, then optionally restores into a scratch database,
# re-asserts the runtime grant posture from deploy/post-restore-grants.sql,
# and verifies forced RLS + immutability grants under the runtime roles.
#
# Usage (from repo root):
#   ./scripts/backup-restore.sh backup \
#     --container accord-postgres-1 --db accord --user accord \
#     --password "$ACCORD_DB_PASSWORD" --out /tmp/accord.dump \
#     [--minio-volume accord_minio-data]
#
#   ./scripts/backup-restore.sh restore-scratch \
#     --container accord-postgres-1 --db accord --user accord \
#     --password "$ACCORD_DB_PASSWORD" --dump /tmp/accord.dump \
#     --scratch accord_restore_scratch [--verify-table rehearsal_probe]
#
#   ./scripts/backup-restore.sh verify-counts \
#     --container accord-postgres-1 --db accord --user accord \
#     --password "$ACCORD_DB_PASSWORD" --verify-table rehearsal_probe
#
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  backup-restore.sh backup --container NAME --db NAME --user NAME --password SECRET --out PATH [--minio-volume VOLUME]
  backup-restore.sh restore-scratch --container NAME --db NAME --user NAME --password SECRET \
      --dump PATH --scratch NAME [--verify-table TABLE] [--grants-sql PATH]
  backup-restore.sh verify-counts --container NAME --db NAME --user NAME --password SECRET \
      --verify-table TABLE

Environment overrides (optional): ACCORD_PG_CONTAINER, ACCORD_DB_NAME, ACCORD_DB_USER,
ACCORD_DB_PASSWORD, ACCORD_BACKUP_OUT, ACCORD_SCRATCH_DB, ACCORD_VERIFY_TABLE,
ACCORD_MINIO_VOLUME, ACCORD_GRANTS_SQL.
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

CONTAINER="${ACCORD_PG_CONTAINER:-accord-postgres-1}"
DB_NAME="${ACCORD_DB_NAME:-accord}"
DB_USER="${ACCORD_DB_USER:-accord}"
DB_PASSWORD="${ACCORD_DB_PASSWORD:-}"
OUT_PATH="${ACCORD_BACKUP_OUT:-}"
DUMP_PATH=""
SCRATCH_DB="${ACCORD_SCRATCH_DB:-accord_restore_scratch}"
VERIFY_TABLE="${ACCORD_VERIFY_TABLE:-}"
MINIO_VOLUME="${ACCORD_MINIO_VOLUME:-}"
GRANTS_SQL="${ACCORD_GRANTS_SQL:-$REPO_ROOT/deploy/post-restore-grants.sql}"

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
    --minio-volume) MINIO_VOLUME="${2:-}"; shift 2 ;;
    --grants-sql) GRANTS_SQL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$CONTAINER" ]] || die "--container is required"
[[ -n "$DB_NAME" ]] || die "--db is required"
[[ -n "$DB_USER" ]] || die "--user is required"
[[ -n "$DB_PASSWORD" ]] || die "--password (or ACCORD_DB_PASSWORD) is required"

# These values are interpolated into SQL; restrict them to plain identifiers.
IDENT_RE='^[A-Za-z_][A-Za-z0-9_]{0,62}$'
[[ "$DB_NAME" =~ $IDENT_RE ]] || die "--db is not a valid SQL identifier"
[[ "$DB_USER" =~ $IDENT_RE ]] || die "--user is not a valid SQL identifier"
[[ "$SCRATCH_DB" =~ $IDENT_RE ]] || die "--scratch is not a valid SQL identifier"
if [[ -n "$VERIFY_TABLE" ]]; then
  [[ "$VERIFY_TABLE" =~ $IDENT_RE ]] || die "--verify-table is not a valid SQL identifier"
fi
if [[ -n "$MINIO_VOLUME" ]]; then
  [[ "$MINIO_VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "--minio-volume is not a valid volume name"
fi

docker inspect "$CONTAINER" >/dev/null 2>&1 || die "container not found: $CONTAINER"

pg_exec() {
  local db="$1"
  shift
  docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
    psql -U "$DB_USER" -d "$db" -v ON_ERROR_STOP=1 "$@"
}

pg_exec_stdin() {
  local db="$1"
  shift
  docker exec -i -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
    psql -U "$DB_USER" -d "$db" -v ON_ERROR_STOP=1 "$@"
}

count_rows() {
  local db="$1"
  local table="$2"
  docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
    psql -U "$DB_USER" -d "$db" -tAc "SELECT count(*) FROM ${table};"
}

# Post-restore verification: run as the runtime roles (never the superuser)
# and prove that (a) forced RLS still filters every org-column table, and
# (b) UPDATE/DELETE on immutable tables is still denied. This discharges the
# release-acceptance checklist restore-under-runtime-role RLS proof.
verify_rls_posture() {
  local db="$1"
  local role
  for role in accord_app accord_worker; do
    pg_exec_stdin "$db" -v "role_name=$role" <<'SQL'
SET ROLE :"role_name";
BEGIN;
-- Tenant GUC is transaction-local in app code; a foreign org id must yield
-- zero rows on every org-column table.
SELECT set_config('app.organization_id', 'ffffffff-ffff-ffff-ffff-ffffffffffff', true);
DO $$
DECLARE
  probe RECORD;
  visible bigint;
  missing_force integer;
BEGIN
  SELECT count(*) INTO missing_force
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'r'
     AND EXISTS (
       SELECT 1 FROM pg_attribute a
        WHERE a.attrelid = c.oid AND a.attname = 'organization_id'
          AND NOT a.attisdropped
     )
     AND NOT c.relforcerowsecurity;
  IF missing_force > 0 THEN
    RAISE EXCEPTION 'RLS probe failed: % org-column tables lack FORCE ROW LEVEL SECURITY', missing_force;
  END IF;

  FOR probe IN
    SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r'
       AND EXISTS (
         SELECT 1 FROM pg_attribute a
          WHERE a.attrelid = c.oid AND a.attname = 'organization_id'
            AND NOT a.attisdropped
       )
     ORDER BY c.relname
  LOOP
    EXECUTE format('SELECT count(*) FROM %I', probe.relname) INTO visible;
    IF visible <> 0 THEN
      RAISE EXCEPTION 'RLS probe failed: % exposes % rows under a foreign organization context',
        probe.relname, visible;
    END IF;
  END LOOP;
END $$;
COMMIT;
RESET ROLE;
SQL
    echo "[verify] forced RLS filters every org-column table under ${role}"
  done

  # Immutability backstop: runtime roles must be denied UPDATE/DELETE on the
  # append-only tables (privilege check, independent of row presence).
  pg_exec_stdin "$db" <<'SQL'
DO $$
DECLARE
  probe RECORD;
BEGIN
  FOR probe IN
    SELECT t.table_name, t.privilege
      FROM (VALUES
        ('payroll_run_versions', 'UPDATE'),
        ('payroll_run_versions', 'DELETE'),
        ('payroll_employee_results', 'UPDATE'),
        ('payroll_employee_results', 'DELETE'),
        ('payroll_result_lines', 'UPDATE'),
        ('payroll_result_lines', 'DELETE'),
        ('payroll_approvals', 'UPDATE'),
        ('payroll_approvals', 'DELETE'),
        ('payroll_report_snapshots', 'UPDATE'),
        ('payroll_report_snapshots', 'DELETE'),
        ('audit_events', 'UPDATE'),
        ('audit_events', 'DELETE'),
        ('outbox_events', 'DELETE'),
        ('alembic_version', 'SELECT'),
        ('alembic_version', 'UPDATE')
      ) AS t(table_name, privilege)
  LOOP
    IF has_table_privilege('accord_app', probe.table_name, probe.privilege)
       OR has_table_privilege('accord_worker', probe.table_name, probe.privilege) THEN
      RAISE EXCEPTION 'grant probe failed: runtime role retains % on %',
        probe.privilege, probe.table_name;
    END IF;
  END LOOP;
END $$;
SQL
  echo "[verify] immutable-table and alembic_version revokes hold under accord_app/accord_worker"
}

case "$COMMAND" in
  backup)
    [[ -n "$OUT_PATH" ]] || die "--out is required for backup"
    mkdir -p "$(dirname "$OUT_PATH")"
    echo "[backup] dumping ${DB_NAME} from ${CONTAINER} → ${OUT_PATH}"
    # Keep ACLs in the archive: grants and the ADR-0009 revokes are part of the
    # data being protected. --no-owner still normalizes ownership on restore.
    docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
      pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner \
      >"$OUT_PATH"
    [[ -s "$OUT_PATH" ]] || die "dump file empty: $OUT_PATH"
    echo "[backup] ok bytes=$(wc -c <"$OUT_PATH" | tr -d ' ')"
    if [[ -n "$MINIO_VOLUME" ]]; then
      mount="$(docker volume inspect "$MINIO_VOLUME" --format '{{.Mountpoint}}')" \
        || die "could not inspect MinIO volume $MINIO_VOLUME"
      [[ "$mount" == /* && "$mount" != *".."* && -d "$mount" && ! -L "$mount" ]] \
        || die "MinIO volume mountpoint is unsafe"
      objects_out="${OUT_PATH}.minio.tar.gz"
      echo "[backup] snapshotting MinIO volume ${MINIO_VOLUME} → ${objects_out}"
      tar --one-file-system --numeric-owner -czf "$objects_out" -C "$mount" .
      tar -tzf "$objects_out" >/dev/null || die "MinIO snapshot unreadable"
      echo "[backup] minio ok bytes=$(wc -c <"$objects_out" | tr -d ' ')"
    fi
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
    [[ -f "$GRANTS_SQL" ]] || die "grants SQL not found: $GRANTS_SQL"
    [[ "$SCRATCH_DB" != "$DB_NAME" ]] || die "--scratch must differ from --db"
    # The scratch database is dropped unconditionally; require the naming
    # convention and refuse known primary names regardless of --db.
    [[ "$SCRATCH_DB" == *_scratch ]] || die "--scratch name must end in _scratch"
    [[ "$SCRATCH_DB" != "accord" && "$SCRATCH_DB" != "postgres" ]] \
      || die "refusing scratch name '$SCRATCH_DB'"

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
    cleanup_remote_dump() {
      docker exec "$CONTAINER" rm -f "$remote_dump" >/dev/null 2>&1 || true
    }
    trap cleanup_remote_dump EXIT
    docker cp "$DUMP_PATH" "${CONTAINER}:${remote_dump}"
    # --no-owner only: ACLs recorded in the dump are restored (grants and the
    # ADR-0009 revokes included). Older --no-acl dumps are repaired below by
    # re-asserting the intended posture explicitly.
    docker exec -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER" \
      pg_restore -U "$DB_USER" -d "$SCRATCH_DB" --no-owner --clean --if-exists \
      "$remote_dump"
    cleanup_remote_dump
    trap - EXIT

    echo "[restore] re-asserting runtime grant posture ($GRANTS_SQL)"
    pg_exec_stdin "$SCRATCH_DB" <"$GRANTS_SQL" \
      || die "could not re-assert the runtime grant posture on the restored database"

    echo "[restore] verifying forced RLS + immutability under runtime roles"
    verify_rls_posture "$SCRATCH_DB"

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
