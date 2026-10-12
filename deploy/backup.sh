#!/usr/bin/env bash
# Routine Accord backup: paired Postgres dump + MinIO volume snapshot with
# read-back verification, checksums, and bounded retention.
#
# Run on the deploy host (root or the deploy operator with docker access):
#   /opt/accord/deploy/backup.sh [--keep N]
#
# Suggested cadence (operations runbook): cron daily, e.g.
#   30 3 * * * /opt/accord/deploy/backup.sh --keep 14 >>/var/log/accord-backup.log 2>&1
set -euo pipefail

die() { echo "backup: $1" >&2; exit 1; }

KEEP=14
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep) KEEP="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done
[[ "$KEEP" =~ ^[0-9]+$ && "$KEEP" -ge 1 ]] || die "--keep must be a positive integer"

BACKUP_ROOT="${ACCORD_ROUTINE_BACKUP_DIR:-/opt/accord/backups/routine}"
LIVE_DEPLOY_DIR="${ACCORD_LIVE_DEPLOY_DIR:-/opt/accord/deploy}"
[[ "$BACKUP_ROOT" == /* && "$BACKUP_ROOT" != *".."* ]] \
    || die "backup directory must be an absolute path without parent traversal"
[[ "$BACKUP_ROOT" != "/" ]] || die "backup directory must not be the filesystem root"

umask 077
install -d -m 0700 "$BACKUP_ROOT" 2>/dev/null || mkdir -p "$BACKUP_ROOT"

# One routine backup at a time: overlapping runs (or a same-second retry)
# must not interleave dumps or overwrite a completed artifact set.
exec 9>"$BACKUP_ROOT/.accord-routine.lock"
flock -n 9 || die "another routine backup is already running"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL_DUMP="$BACKUP_ROOT/accord-routine-$TIMESTAMP.dump"
FINAL_LIST="$FINAL_DUMP.list"
FINAL_CHECKSUM="$FINAL_DUMP.sha256"
FINAL_OBJECTS="$FINAL_DUMP.minio.tar.gz"
FINAL_OBJECTS_LIST="$FINAL_OBJECTS.list"
FINAL_OBJECTS_CHECKSUM="$FINAL_OBJECTS.sha256"

for existing in \
    "$FINAL_DUMP" "$FINAL_LIST" "$FINAL_CHECKSUM" \
    "$FINAL_OBJECTS" "$FINAL_OBJECTS_LIST" "$FINAL_OBJECTS_CHECKSUM"; do
    [[ ! -e "$existing" ]] || die "backup target already exists: $existing"
done

TEMP_DUMP="$(mktemp "$BACKUP_ROOT/.accord-routine.XXXXXXXXXX.dump")"
TEMP_LIST="$(mktemp "$BACKUP_ROOT/.accord-routine.XXXXXXXXXX.list")"
TEMP_CHECKSUM="$(mktemp "$BACKUP_ROOT/.accord-routine.XXXXXXXXXX.sha256")"
TEMP_OBJECTS="$(mktemp "$BACKUP_ROOT/.accord-routine-minio.XXXXXXXXXX.tar.gz")"
TEMP_OBJECTS_LIST="$(mktemp "$BACKUP_ROOT/.accord-routine-minio.XXXXXXXXXX.list")"
TEMP_OBJECTS_CHECKSUM="$(mktemp "$BACKUP_ROOT/.accord-routine-minio.XXXXXXXXXX.sha256")"
PUBLISHING=""
cleanup() {
    rm -f -- \
        "$TEMP_DUMP" "$TEMP_LIST" "$TEMP_CHECKSUM" \
        "$TEMP_OBJECTS" "$TEMP_OBJECTS_LIST" "$TEMP_OBJECTS_CHECKSUM"
    if [[ "$PUBLISHING" == "1" ]]; then
        rm -f -- \
            "$FINAL_DUMP" "$FINAL_LIST" "$FINAL_CHECKSUM" \
            "$FINAL_OBJECTS" "$FINAL_OBJECTS_LIST" "$FINAL_OBJECTS_CHECKSUM"
    fi
}
trap cleanup EXIT

DB_CID_OUTPUT="$(docker ps -q \
    --filter "label=com.docker.compose.service=postgres" \
    --filter "label=com.docker.compose.project.working_dir=$LIVE_DEPLOY_DIR" 2>/dev/null)" \
    || die "could not inspect the running Accord PostgreSQL container"
[[ -n "$DB_CID_OUTPUT" && "$DB_CID_OUTPUT" != *$'\n'* ]] \
    || die "expected exactly one running Accord database container"
DB_ENVIRONMENT="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$DB_CID_OUTPUT")" \
    || die "could not inspect the running Accord database configuration"
DB_USER="$(printf '%s\n' "$DB_ENVIRONMENT" | awk -F= '$1 == "POSTGRES_USER" { print substr($0, index($0, "=") + 1) }')"
DB_NAME="$(printf '%s\n' "$DB_ENVIRONMENT" | awk -F= '$1 == "POSTGRES_DB" { print substr($0, index($0, "=") + 1) }')"
[[ "$DB_USER" =~ ^[A-Za-z_][A-Za-z0-9_-]{0,62}$ ]] \
    || die "running Accord database user is missing or unsafe"
[[ "$DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_-]{0,62}$ ]] \
    || die "running Accord database name is missing or unsafe"

# ACLs are kept so the dump preserves grants and the ADR-0009 revokes.
docker exec -i "$DB_CID_OUTPUT" pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom >"$TEMP_DUMP" \
    || die "database backup failed"
[[ -s "$TEMP_DUMP" ]] || die "database backup is empty"
docker exec -i "$DB_CID_OUTPUT" pg_restore --list <"$TEMP_DUMP" >"$TEMP_LIST" \
    || die "database backup could not be read back"
grep -F "TABLE DATA" "$TEMP_LIST" >/dev/null \
    || die "database backup contains no table data entries"

DIGEST="$(sha256sum "$TEMP_DUMP" | awk '{print $1}')"
[[ "$DIGEST" =~ ^[0-9a-f]{64}$ ]] || die "could not hash database backup"
printf '%s  %s\n' "$DIGEST" "$(basename "$FINAL_DUMP")" >"$TEMP_CHECKSUM"

MINIO_VOLUME="accord_minio-data"
MINIO_MOUNT="$(docker volume inspect "$MINIO_VOLUME" --format '{{.Mountpoint}}')" \
    || die "could not inspect the Accord MinIO volume"
[[ "$MINIO_MOUNT" == /* && "$MINIO_MOUNT" != *".."* && -d "$MINIO_MOUNT" && ! -L "$MINIO_MOUNT" ]] \
    || die "Accord MinIO volume mountpoint is unsafe"
tar --one-file-system --numeric-owner -czf "$TEMP_OBJECTS" -C "$MINIO_MOUNT" . \
    || die "MinIO volume snapshot failed"
tar -tzf "$TEMP_OBJECTS" >"$TEMP_OBJECTS_LIST" \
    || die "MinIO volume snapshot could not be read back"
OBJECTS_DIGEST="$(sha256sum "$TEMP_OBJECTS" | awk '{print $1}')"
[[ "$OBJECTS_DIGEST" =~ ^[0-9a-f]{64}$ ]] || die "could not hash MinIO volume snapshot"
printf '%s  %s\n' "$OBJECTS_DIGEST" "$(basename "$FINAL_OBJECTS")" >"$TEMP_OBJECTS_CHECKSUM"

chmod 0600 "$TEMP_DUMP" "$TEMP_LIST" "$TEMP_CHECKSUM" \
    "$TEMP_OBJECTS" "$TEMP_OBJECTS_LIST" "$TEMP_OBJECTS_CHECKSUM"
# From here on a failure must also remove partially published FINAL_*
# artifacts; before this point cleanup touches only TEMP_* files.
PUBLISHING=1
mv "$TEMP_DUMP" "$FINAL_DUMP"
mv "$TEMP_LIST" "$FINAL_LIST"
mv "$TEMP_CHECKSUM" "$FINAL_CHECKSUM"
mv "$TEMP_OBJECTS" "$FINAL_OBJECTS"
mv "$TEMP_OBJECTS_LIST" "$FINAL_OBJECTS_LIST"
mv "$TEMP_OBJECTS_CHECKSUM" "$FINAL_OBJECTS_CHECKSUM"
sync "$FINAL_DUMP" "$FINAL_OBJECTS" 2>/dev/null || true
trap - EXIT

# Bounded retention: prune oldest routine backups beyond --keep.
ls -1t "$BACKUP_ROOT"/accord-routine-*.dump 2>/dev/null \
    | tail -n "+$((KEEP + 1))" \
    | while IFS= read -r old; do
        rm -f -- "$old" "$old.list" "$old.sha256" \
            "$old.minio.tar.gz" "$old.minio.tar.gz.list" "$old.minio.tar.gz.sha256"
    done

printf '%s\n' "$FINAL_DUMP"
