#!/usr/bin/env bash
# Create and verify a root-only database backup before a release migration.
set -euo pipefail

die() { echo "backup-before-migrate: $1" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: backup-before-migrate <40-character-sha>"
SHA="$1"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "SHA must be 40 lowercase hexadecimal characters"

BACKUP_ROOT="${ACCORD_RELEASE_BACKUP_DIR:-/opt/accord/backups/releases}"
LIVE_DEPLOY_DIR="${ACCORD_LIVE_DEPLOY_DIR:-/opt/accord/deploy}"
[[ "$BACKUP_ROOT" == /* && "$BACKUP_ROOT" != *".."* ]] \
    || die "backup directory must be an absolute path without parent traversal"
[[ "$BACKUP_ROOT" != "/" ]] || die "backup directory must not be the filesystem root"
[[ "$LIVE_DEPLOY_DIR" == /* && "$LIVE_DEPLOY_DIR" != *".."* ]] \
    || die "live deploy directory must be an absolute path without parent traversal"

umask 077
/usr/bin/python3 - "$BACKUP_ROOT" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
parts = [part for part in path.split("/") if part]
effective_uid = os.geteuid()
directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    root_details = os.fstat(directory)
    root_mode = stat.S_IMODE(root_details.st_mode)
    if root_details.st_uid != 0 or root_details.st_gid != 0 or root_mode & 0o022:
        raise SystemExit("filesystem root is not a trusted backup ancestor")
    for index, part in enumerate(parts):
        final = index == len(parts) - 1
        created = False
        try:
            os.mkdir(part, 0o700, dir_fd=directory)
            created = True
        except FileExistsError:
            pass
        try:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
        except OSError as error:
            raise SystemExit(f"unsafe backup directory component {part}: {error}") from error
        try:
            details = os.fstat(child)
            mode = stat.S_IMODE(details.st_mode)
            if effective_uid == 0:
                if details.st_uid != 0 or details.st_gid != 0:
                    raise SystemExit(
                        f"backup directory component must be owned by root:root: {part}"
                    )
                shared_sticky_parent = False
            else:
                if details.st_uid not in {0, effective_uid}:
                    raise SystemExit(
                        f"backup directory component has an untrusted owner: {part}"
                    )
                shared_sticky_parent = (
                    not final
                    and details.st_uid == 0
                    and bool(mode & stat.S_ISVTX)
                )
            if mode & 0o022 and not shared_sticky_parent:
                raise SystemExit(
                    f"backup directory component is group/world-writable: {part}"
                )
            if final:
                if details.st_uid != effective_uid:
                    raise SystemExit("final backup directory must be owned by the deploy user")
                os.fchmod(child, 0o700)
            if created:
                os.fsync(directory)
        except BaseException:
            os.close(child)
            raise
        os.close(directory)
        directory = child
finally:
    os.close(directory)
PY
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL_DUMP="$BACKUP_ROOT/accord-pre-migrate-$TIMESTAMP-$SHA.dump"
FINAL_LIST="$FINAL_DUMP.list"
FINAL_CHECKSUM="$FINAL_DUMP.sha256"
FINAL_OBJECTS="$FINAL_DUMP.minio.tar.gz"
FINAL_OBJECTS_LIST="$FINAL_OBJECTS.list"
FINAL_OBJECTS_CHECKSUM="$FINAL_OBJECTS.sha256"
[[ ! -e "$FINAL_DUMP" && ! -e "$FINAL_LIST" && ! -e "$FINAL_CHECKSUM" \
    && ! -e "$FINAL_OBJECTS" && ! -e "$FINAL_OBJECTS_LIST" \
    && ! -e "$FINAL_OBJECTS_CHECKSUM" ]] \
    || die "backup evidence already exists for this timestamp and release"

TEMP_DUMP="$(mktemp "$BACKUP_ROOT/.accord-pre-migrate.XXXXXXXXXX.dump")"
TEMP_LIST="$(mktemp "$BACKUP_ROOT/.accord-pre-migrate.XXXXXXXXXX.list")"
TEMP_CHECKSUM="$(mktemp "$BACKUP_ROOT/.accord-pre-migrate.XXXXXXXXXX.sha256")"
TEMP_OBJECTS="$(mktemp "$BACKUP_ROOT/.accord-minio-pre-migrate.XXXXXXXXXX.tar.gz")"
TEMP_OBJECTS_LIST="$(mktemp "$BACKUP_ROOT/.accord-minio-pre-migrate.XXXXXXXXXX.list")"
TEMP_OBJECTS_CHECKSUM="$(mktemp "$BACKUP_ROOT/.accord-minio-pre-migrate.XXXXXXXXXX.sha256")"
cleanup() {
    rm -f -- \
        "$TEMP_DUMP" "$TEMP_LIST" "$TEMP_CHECKSUM" \
        "$TEMP_OBJECTS" "$TEMP_OBJECTS_LIST" "$TEMP_OBJECTS_CHECKSUM" \
        "$FINAL_DUMP" "$FINAL_LIST" "$FINAL_CHECKSUM" \
        "$FINAL_OBJECTS" "$FINAL_OBJECTS_LIST" "$FINAL_OBJECTS_CHECKSUM"
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

docker exec -i "$DB_CID_OUTPUT" pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom >"$TEMP_DUMP" \
    || die "database backup failed; migrations were not started"
[[ -s "$TEMP_DUMP" ]] || die "database backup is empty; migrations were not started"
docker exec -i "$DB_CID_OUTPUT" pg_restore --list <"$TEMP_DUMP" >"$TEMP_LIST" \
    || die "database backup could not be read back; migrations were not started"
grep -F "TABLE DATA" "$TEMP_LIST" >/dev/null \
    || die "database backup contains no table data entries; migrations were not started"

DIGEST="$(sha256sum "$TEMP_DUMP" | awk '{print $1}')"
[[ "$DIGEST" =~ ^[0-9a-f]{64}$ ]] || die "could not hash database backup"
printf '%s  %s\n' "$DIGEST" "$(basename "$FINAL_DUMP")" >"$TEMP_CHECKSUM"

MINIO_VOLUME="accord_minio-data"
MINIO_MOUNT="$(docker volume inspect "$MINIO_VOLUME" --format '{{.Mountpoint}}')" \
    || die "could not inspect the Accord MinIO volume"
[[ "$MINIO_MOUNT" == /* && "$MINIO_MOUNT" != *".."* && -d "$MINIO_MOUNT" && ! -L "$MINIO_MOUNT" ]] \
    || die "Accord MinIO volume mountpoint is unsafe"
tar --one-file-system --numeric-owner -czf "$TEMP_OBJECTS" -C "$MINIO_MOUNT" . \
    || die "MinIO volume snapshot failed; migrations were not started"
tar -tzf "$TEMP_OBJECTS" >"$TEMP_OBJECTS_LIST" \
    || die "MinIO volume snapshot could not be read back; migrations were not started"
OBJECTS_DIGEST="$(sha256sum "$TEMP_OBJECTS" | awk '{print $1}')"
[[ "$OBJECTS_DIGEST" =~ ^[0-9a-f]{64}$ ]] || die "could not hash MinIO volume snapshot"
printf '%s  %s\n' "$OBJECTS_DIGEST" "$(basename "$FINAL_OBJECTS")" >"$TEMP_OBJECTS_CHECKSUM"

chmod 0600 "$TEMP_DUMP" "$TEMP_LIST" "$TEMP_CHECKSUM" \
    "$TEMP_OBJECTS" "$TEMP_OBJECTS_LIST" "$TEMP_OBJECTS_CHECKSUM"
mv "$TEMP_DUMP" "$FINAL_DUMP"
mv "$TEMP_LIST" "$FINAL_LIST"
mv "$TEMP_CHECKSUM" "$FINAL_CHECKSUM"
mv "$TEMP_OBJECTS" "$FINAL_OBJECTS"
mv "$TEMP_OBJECTS_LIST" "$FINAL_OBJECTS_LIST"
mv "$TEMP_OBJECTS_CHECKSUM" "$FINAL_OBJECTS_CHECKSUM"
/usr/bin/python3 - \
    "$FINAL_DUMP" "$FINAL_LIST" "$FINAL_CHECKSUM" \
    "$FINAL_OBJECTS" "$FINAL_OBJECTS_LIST" "$FINAL_OBJECTS_CHECKSUM" \
    "$BACKUP_ROOT" <<'PY'
import os
import stat
import sys

*files, directory = sys.argv[1:]
for path in files:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SystemExit(f"backup evidence is not a regular file: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

directory_descriptor = os.open(
    directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
)
try:
    os.fsync(directory_descriptor)
finally:
    os.close(directory_descriptor)
PY
trap - EXIT

printf '%s\n' "$FINAL_DUMP"
