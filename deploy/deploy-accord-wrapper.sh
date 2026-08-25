#!/usr/bin/env bash
# accord-deploy-wrapper-v1
set -euo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

die() { echo "deploy-accord-wrapper: $1" >&2; exit 1; }

# Re-exec once with a descriptor opened relative to the trusted app lock
# directory. Shell redirection would follow an attacker-planted symlink.
if [[ "${ACCORD_RELEASE_LOCK_HELD:-}" != "1" ]]; then
    IFS= read -r ACCORD_RELEASE_GHCR_USERNAME \
        || die "ephemeral registry username was not provided on standard input"
    IFS= read -r ACCORD_RELEASE_GHCR_TOKEN \
        || die "ephemeral registry token was not provided on standard input"
    export ACCORD_RELEASE_GHCR_USERNAME ACCORD_RELEASE_GHCR_TOKEN
    exec /usr/bin/python3 - "${BASH_SOURCE[0]}" "$@" <<'PY'
import fcntl
import os
import stat
import sys

script, *arguments = sys.argv[1:]
directory = os.open("/run/lock/accord-release", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    details = os.fstat(directory)
    if details.st_uid != 0 or details.st_gid != 0 or stat.S_IMODE(details.st_mode) & 0o022:
        raise SystemExit("deploy-accord-wrapper: /run/lock/accord-release is not a trusted root directory")
    descriptor = os.open(
        "accord-release-install.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
finally:
    os.close(directory)
lock_details = os.fstat(descriptor)
if not stat.S_ISREG(lock_details.st_mode) or lock_details.st_uid != 0:
    raise SystemExit("deploy-accord-wrapper: release lock is not a trusted root-owned file")
os.fchmod(descriptor, 0o600)
try:
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("deploy-accord-wrapper: another Accord release installation is already running")
os.set_inheritable(descriptor, True)
environment = os.environ.copy()
environment["ACCORD_RELEASE_LOCK_HELD"] = "1"
environment["ACCORD_RELEASE_LOCK_FD"] = str(descriptor)
os.execve(script, [script, *arguments], environment)
PY
fi
[[ "${ACCORD_RELEASE_LOCK_FD:-}" =~ ^[0-9]+$ ]] \
    || die "release lock descriptor is missing"

[[ $# -eq 2 ]] || die "usage: deploy-accord <40-character-sha> <staged-release-root>"
SHA="$1"
STAGED_ROOT="$2"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "SHA must be 40 lowercase hexadecimal characters"
[[ "$STAGED_ROOT" =~ ^/tmp/accord-release-${SHA}-[0-9]+-[0-9]+$ ]] \
    || die "staged release path has an invalid format"
[[ -d "$STAGED_ROOT" && ! -L "$STAGED_ROOT" ]] \
    || die "staged release must be a real directory"
[[ "$ACCORD_RELEASE_GHCR_USERNAME" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] \
    || die "ephemeral registry username is invalid"
[[ ${#ACCORD_RELEASE_GHCR_TOKEN} -ge 20 && ${#ACCORD_RELEASE_GHCR_TOKEN} -le 512 ]] \
    || die "ephemeral registry token has an invalid length"

ARCHIVE_NAME="accord-deploy-sha-$SHA.tar.gz"
MANIFEST_NAME="onprem-release-$SHA.json"
CHECKSUMS_NAME="onprem-checksums-$SHA.txt"
SIGNATURE_NAME="onprem-signature-$SHA.sig"
for filename in "$ARCHIVE_NAME" "$MANIFEST_NAME" "$CHECKSUMS_NAME" "$SIGNATURE_NAME"; do
    [[ -f "$STAGED_ROOT/$filename" && ! -L "$STAGED_ROOT/$filename" ]] \
        || die "staged release file is missing or unsafe: $filename"
done

[[ -x /usr/bin/python3 ]] || die "Python is required at /usr/bin/python3"
[[ -x /usr/bin/sha256sum ]] || die "sha256sum is required at /usr/bin/sha256sum"
[[ -x /usr/bin/openssl ]] || die "OpenSSL is required at /usr/bin/openssl"

secure_root_directory() {
    local directory="$1" owner group mode group_mode other_mode
    [[ -d "$directory" && ! -L "$directory" ]] || return 1
    owner="$(stat -c '%u' "$directory")" || return 1
    group="$(stat -c '%g' "$directory")" || return 1
    mode="$(stat -c '%a' "$directory")" || return 1
    [[ "$owner" == "0" && "$group" == "0" ]] || return 1
    group_mode="${mode: -2:1}"
    other_mode="${mode: -1}"
    [[ ! "$group_mode" =~ [2367] && ! "$other_mode" =~ [2367] ]]
}

live_container_id() {
    local service="$1" output
    output="$(docker ps -q \
        --filter "label=com.docker.compose.service=$service" \
        --filter "label=com.docker.compose.project.working_dir=/opt/accord/deploy" 2>/dev/null)" \
        || die "could not inspect the running Accord $service container"
    [[ -n "$output" && "$output" != *$'\n'* ]] \
        || die "expected exactly one running Accord $service container"
    printf '%s\n' "$output"
}

LIVE_ROOT="/opt/accord/deploy"
CANDIDATE_ROOT="/opt/accord/.release-candidate-$SHA-$$"
BACKUP_ROOT="/opt/accord/.deploy-previous-$(date -u +%Y%m%d%H%M%S)-$$"
FAILED_ROOT="/opt/accord/.deploy-failed-$SHA-$$"
TRUSTED_PUBLIC_KEY=""
APP_CONTAINER_IDS=()
APP_QUIESCED=false
secure_root_directory /opt \
    || die "/opt must be a real root-owned directory without group/world write access"
secure_root_directory /opt/accord \
    || die "/opt/accord must be a real root-owned directory without group/world write access"
secure_root_directory "$LIVE_ROOT" \
    || die "the existing Accord deploy directory must be root-owned without group/world write access"
[[ -f "$LIVE_ROOT/.env" && ! -L "$LIVE_ROOT/.env" ]] \
    || die "the existing Accord environment file is missing or unsafe"
[[ ! -e "$CANDIDATE_ROOT" && ! -e "$BACKUP_ROOT" && ! -e "$FAILED_ROOT" ]] \
    || die "release installation paths already exist"

# Copy only the four expected files into a root-only directory without
# preserving any staging ownership, mode, ACL, or directory metadata.
install -d -o root -g root -m 0700 "$CANDIDATE_ROOT"
cleanup_wrapper() {
    if [[ "$APP_QUIESCED" == "true" && ${#APP_CONTAINER_IDS[@]} -eq 4 ]]; then
        docker start "${APP_CONTAINER_IDS[@]}" >/dev/null 2>&1 \
            || echo "deploy-accord-wrapper: could not restart the previous application containers" >&2
    fi
    if [[ -n "$TRUSTED_PUBLIC_KEY" ]]; then
        rm -f -- "$TRUSTED_PUBLIC_KEY"
    fi
    if [[ -d "$CANDIDATE_ROOT" && ! -L "$CANDIDATE_ROOT" ]]; then
        rm -rf -- "$CANDIDATE_ROOT"
    fi
}
trap cleanup_wrapper EXIT
/usr/bin/python3 - "$STAGED_ROOT" "$CANDIDATE_ROOT" "$SHA" <<'PY'
import os
import stat
import sys

source_root, destination_root, sha = sys.argv[1:]
expected = {
    f"accord-deploy-sha-{sha}.tar.gz": (1, 67_108_864),
    f"onprem-release-{sha}.json": (1, 1_048_576),
    f"onprem-checksums-{sha}.txt": (1, 512),
    f"onprem-signature-{sha}.sig": (64, 64),
}
source_directory = os.open(
    source_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
)
destination_directory = os.open(
    destination_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
)
try:
    for name, (minimum, maximum) in expected.items():
        source = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=source_directory,
        )
        try:
            source_stat = os.fstat(source)
            if not stat.S_ISREG(source_stat.st_mode):
                raise SystemExit(f"staged release file is not regular: {name}")
            if not minimum <= source_stat.st_size <= maximum:
                raise SystemExit(f"staged release file has an invalid size: {name}")
            destination = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=destination_directory,
            )
            copied = 0
            try:
                while True:
                    chunk = os.read(source, min(1_048_576, maximum + 1 - copied))
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > maximum:
                        raise SystemExit(f"staged release file grew while copying: {name}")
                    view = memoryview(chunk)
                    while view:
                        written = os.write(destination, view)
                        view = view[written:]
                if copied != source_stat.st_size:
                    raise SystemExit(f"staged release file changed while copying: {name}")
                os.fchmod(destination, 0o600)
                os.fchown(destination, 0, 0)
            finally:
                os.close(destination)
        finally:
            os.close(source)
finally:
    os.close(destination_directory)
    os.close(source_directory)
PY
CANDIDATE_ENTRY_COUNT="$(find "$CANDIDATE_ROOT" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d '[:space:]')"
[[ "$CANDIDATE_ENTRY_COUNT" == "4" ]] \
    || die "staged release must contain exactly the four expected files"
[[ "$(stat -c '%u:%g:%a' "$CANDIDATE_ROOT")" == "0:0:700" ]] \
    || die "release candidate directory lost its root-only ownership or mode"
for filename in "$ARCHIVE_NAME" "$MANIFEST_NAME" "$CHECKSUMS_NAME" "$SIGNATURE_NAME"; do
    [[ -f "$CANDIDATE_ROOT/$filename" && ! -L "$CANDIDATE_ROOT/$filename" ]] \
        || die "copied release file is missing or unsafe: $filename"
done

ARCHIVE="$CANDIDATE_ROOT/$ARCHIVE_NAME"
MANIFEST="$CANDIDATE_ROOT/$MANIFEST_NAME"
CHECKSUMS="$CANDIDATE_ROOT/$CHECKSUMS_NAME"
SIGNATURE="$CANDIDATE_ROOT/$SIGNATURE_NAME"
[[ "$(stat -c '%s' "$ARCHIVE")" -le 67108864 ]] || die "release archive is too large"
[[ "$(stat -c '%s' "$MANIFEST")" -le 1048576 ]] || die "release manifest is too large"
[[ "$(stat -c '%s' "$CHECKSUMS")" -le 512 ]] || die "release checksum file is too large"
[[ "$(stat -c '%s' "$SIGNATURE")" -eq 64 ]] || die "release signature has an invalid size"

secure_root_directory /run \
    || die "/run must be a real root-owned directory without group/world write access"
TRUSTED_PUBLIC_KEY="/run/accord-release-signing-public-$SHA-$$.pem"
[[ ! -e "$TRUSTED_PUBLIC_KEY" && ! -L "$TRUSTED_PUBLIC_KEY" ]] \
    || die "temporary release trust-key path already exists"
cat >"$TRUSTED_PUBLIC_KEY" <<'PEM'
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAhXIjlHdFpeqXULFoLUaHo5qJHd9Yz61xYbR40wM2zQA=
-----END PUBLIC KEY-----
PEM
chmod 0600 "$TRUSTED_PUBLIC_KEY"
/usr/bin/openssl pkeyutl -verify -pubin -rawin \
    -inkey "$TRUSTED_PUBLIC_KEY" \
    -in "$CHECKSUMS" \
    -sigfile "$SIGNATURE" >/dev/null \
    || die "release signature verification failed"
/usr/bin/python3 - "$CANDIDATE_ROOT" "$SHA" <<'PY'
import hashlib
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
sha = sys.argv[2]
expected_names = [
    f"accord-deploy-sha-{sha}.tar.gz",
    f"onprem-release-{sha}.json",
]
lines = (root / f"onprem-checksums-{sha}.txt").read_text(encoding="ascii").splitlines()
if len(lines) != len(expected_names):
    raise SystemExit("release checksum file must contain exactly two entries")
for line, name in zip(lines, expected_names, strict=True):
    match = re.fullmatch(rf"([0-9a-f]{{64}})  {re.escape(name)}", line)
    if match is None:
        raise SystemExit(f"invalid checksum entry for {name}")
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    if actual != match.group(1):
        raise SystemExit(f"checksum mismatch for {name}")
PY

EXTRACTED="$CANDIDATE_ROOT/extracted"
install -d -o root -g root -m 0700 "$EXTRACTED"
/usr/bin/python3 - "$ARCHIVE" "$EXTRACTED" <<'PY'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
with tarfile.open(archive, "r:gz") as source:
    source.extractall(destination, filter="data")
PY
[[ -f "$EXTRACTED/deploy/onprem_release.py" && ! -L "$EXTRACTED/deploy/onprem_release.py" ]] \
    || die "release validator is missing or unsafe"
cmp -s "$TRUSTED_PUBLIC_KEY" "$EXTRACTED/deploy/onprem-release-signing-public.pem" \
    || die "release signing public key does not match the installed trust root"

EXPECTED_VALIDATOR_SHA256="dfd6920f7f591cc337e834c771a22c0e458210db4aa0e0de592fc0df1522863b"
[[ "$(/usr/bin/sha256sum "$EXTRACTED/deploy/onprem_release.py" | awk '{print $1}')" == "$EXPECTED_VALIDATOR_SHA256" ]] \
    || die "release validator does not match the reviewed source"
/usr/bin/python3 "$EXTRACTED/deploy/onprem_release.py" validate \
    "$MANIFEST" --bundle-root "$EXTRACTED" >/dev/null \
    || die "release evidence is invalid"
MANIFEST_SHA="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source"]["commit_sha"])' "$MANIFEST")"
[[ "$MANIFEST_SHA" == "$SHA" ]] || die "release manifest does not match requested SHA"
[[ "$(cat "$EXTRACTED/deploy/release-source-sha")" == "$SHA" ]] \
    || die "release bundle identity does not match requested SHA"
[[ -f "$EXTRACTED/deploy/release-tooling-source-sha" \
    && ! -L "$EXTRACTED/deploy/release-tooling-source-sha" ]] \
    || die "release tooling identity is missing or unsafe"
TOOLING_SHA="$(cat "$EXTRACTED/deploy/release-tooling-source-sha")"
[[ "$TOOLING_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release tooling identity is invalid"
LEGACY_ROLLBACK_SHA="8cc2f95d00d35ab6eb9d4ace31b2f605af10d10d"
if [[ "$TOOLING_SHA" != "$SHA" && "$SHA" != "$LEGACY_ROLLBACK_SHA" ]]; then
    die "release tooling may differ only for the fixed pre-contract production rollback"
fi
# Preserve the live environment only after opening it below the already trusted
# live directory. Refuse to launder unsafe ownership or permissions into the
# authenticated candidate, and prove the source did not change while copied.
/usr/bin/python3 - "$LIVE_ROOT" "$EXTRACTED/deploy" <<'PY'
import os
import stat
import sys

source_root, destination_root = sys.argv[1:]
source_directory = os.open(
    source_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
)
destination_directory = os.open(
    destination_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
)
try:
    directory_stat = os.fstat(source_directory)
    if directory_stat.st_uid != 0 or directory_stat.st_gid != 0:
        raise SystemExit("live deploy directory must be owned by root:root")
    if stat.S_IMODE(directory_stat.st_mode) & 0o022:
        raise SystemExit("live deploy directory must not be group/world-writable")

    source = os.open(
        ".env",
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=source_directory,
    )
    try:
        before = os.fstat(source)
        if not stat.S_ISREG(before.st_mode):
            raise SystemExit("live environment file must be regular")
        if before.st_uid != 0 or before.st_gid != 0:
            raise SystemExit("live environment file must be owned by root:root")
        if stat.S_IMODE(before.st_mode) & 0o077:
            raise SystemExit("live environment file must have no group/other permissions")
        if not 1 <= before.st_size <= 1_048_576:
            raise SystemExit("live environment file has an invalid size")

        destination = os.open(
            ".env",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination_directory,
        )
        copied = 0
        try:
            while True:
                chunk = os.read(source, min(65_536, 1_048_577 - copied))
                if not chunk:
                    break
                copied += len(chunk)
                if copied > 1_048_576:
                    raise SystemExit("live environment file grew while copying")
                view = memoryview(chunk)
                while view:
                    written = os.write(destination, view)
                    if written <= 0:
                        raise SystemExit("could not copy live environment file")
                    view = view[written:]
            after = os.fstat(source)
            snapshot_fields = (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_gid",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            changed = any(
                getattr(before, field) != getattr(after, field)
                for field in snapshot_fields
            )
            if changed:
                raise SystemExit("live environment file changed while copying")
            if copied != before.st_size:
                raise SystemExit("live environment file changed while copying")
            os.fchmod(destination, 0o600)
            os.fchown(destination, 0, 0)
            os.fsync(destination)
        finally:
            os.close(destination)
    finally:
        os.close(source)
finally:
    os.close(destination_directory)
    os.close(source_directory)
PY
install -o root -g root -m 600 "$MANIFEST" "$EXTRACTED/deploy/release-manifest.json"
install -o root -g root -m 600 "$CHECKSUMS" "$EXTRACTED/deploy/release-checksums.txt"
install -o root -g root -m 600 "$SIGNATURE" "$EXTRACTED/deploy/release-signature.sig"
chown -R root:root "$EXTRACTED/deploy"
find "$EXTRACTED/deploy" -type d -exec chmod go-w {} +
find "$EXTRACTED/deploy" -type f -exec chmod go-w {} +

BOOTSTRAP_MARKER="/opt/accord/.allow-first-release-$SHA"
BOOTSTRAP_MODE=false
if [[ -f "$BOOTSTRAP_MARKER" && ! -L "$BOOTSTRAP_MARKER" \
    && "$(stat -c '%u:%g:%a' "$BOOTSTRAP_MARKER")" == "0:0:600" \
    && "$(cat "$BOOTSTRAP_MARKER")" == "$SHA" ]]; then
    BOOTSTRAP_MODE=true
    for service in api worker web minio; do
        [[ -z "$(docker ps -aq --filter "label=com.docker.compose.service=$service" --filter "label=com.docker.compose.project.working_dir=/opt/accord/deploy")" ]] \
            || die "fresh-host bootstrap found an existing Accord $service container"
    done
    for volume in accord_pgdata accord_minio-data deploy_pgdata deploy_minio-data; do
        ! docker volume inspect "$volume" >/dev/null 2>&1 \
            || die "fresh-host bootstrap found existing volume $volume"
    done
    printf '%s\n' "$SHA" >"$EXTRACTED/deploy/release-bootstrap-evidence"
    chmod 0600 "$EXTRACTED/deploy/release-bootstrap-evidence"
else
    API_CID="$(live_container_id api)"
    WORKER_CID="$(live_container_id worker)"
    WEB_CID="$(live_container_id web)"
    MINIO_CID="$(live_container_id minio)"
    [[ "$API_CID" != "$WORKER_CID" && "$API_CID" != "$WEB_CID" \
        && "$API_CID" != "$MINIO_CID" && "$WORKER_CID" != "$WEB_CID" \
        && "$WORKER_CID" != "$MINIO_CID" && "$WEB_CID" != "$MINIO_CID" ]] \
        || die "application services resolved to duplicate containers"
    APP_CONTAINER_IDS=("$API_CID" "$WORKER_CID" "$WEB_CID" "$MINIO_CID")
    APP_QUIESCED=true
    docker stop "${APP_CONTAINER_IDS[@]}" >/dev/null \
        || die "could not quiesce the existing Accord application and object store before backup"

    BACKUP_EVIDENCE="$(ACCORD_RELEASE_BACKUP_DIR=/opt/accord/backups/releases \
        ACCORD_LIVE_DEPLOY_DIR=/opt/accord/deploy \
        bash "$EXTRACTED/deploy/backup-before-migrate.sh" "$SHA")" \
        || die "verified pre-migration backup failed; the live release was not changed"
    [[ "$BACKUP_EVIDENCE" =~ ^/opt/accord/backups/releases/accord-pre-migrate-[0-9]{8}T[0-9]{6}Z-${SHA}\.dump$ ]] \
        || die "release backup helper returned an invalid evidence path"
    [[ -f "$BACKUP_EVIDENCE" && ! -L "$BACKUP_EVIDENCE" ]] \
        || die "verified pre-migration backup is missing or unsafe"
    printf '%s\n%s\n' "$SHA" "$BACKUP_EVIDENCE" \
        >"$EXTRACTED/deploy/release-backup-evidence"
    chmod 0600 "$EXTRACTED/deploy/release-backup-evidence"
fi

mv "$LIVE_ROOT" "$BACKUP_ROOT"
if ! mv "$EXTRACTED/deploy" "$LIVE_ROOT"; then
    mv "$BACKUP_ROOT" "$LIVE_ROOT"
    die "could not activate the authenticated release bundle"
fi
MIGRATION_STATE_FILE="/run/accord-release-migration-$SHA"
if ACCORD_RELEASE_BACKUP_DIR=/opt/accord/backups/releases \
    bash "$LIVE_ROOT/deploy-accord.sh" "$SHA"; then
    APP_QUIESCED=false
    [[ "$BOOTSTRAP_MODE" != "true" ]] || rm -f -- "$BOOTSTRAP_MARKER"
    rm -f -- "$MIGRATION_STATE_FILE"
    rm -rf "$BACKUP_ROOT" "$CANDIDATE_ROOT" "$STAGED_ROOT"
    exit 0
fi

if [[ -f "$MIGRATION_STATE_FILE" ]]; then
    APP_QUIESCED=false
    docker compose -f "$LIVE_ROOT/docker-compose.yml" --env-file "$LIVE_ROOT/.env" \
        stop api worker web >/dev/null 2>&1 \
        || echo "deploy-accord-wrapper: could not stop failed application services" >&2
    if [[ "$BOOTSTRAP_MODE" == "true" ]]; then
        mv "$BOOTSTRAP_MARKER" "/opt/accord/.first-release-attempted-$SHA"
    fi
    die "Accord rollout failed after migrations started; the authenticated release files remain active, application services are stopped, the previous files are retained at $BACKUP_ROOT, and recovery must follow the release evidence"
fi
FAILURE_DETAIL="migrations were not attempted, so the previous application containers will be restarted"
mv "$LIVE_ROOT" "$FAILED_ROOT"
mv "$BACKUP_ROOT" "$LIVE_ROOT"
die "Accord rollout failed after the verified backup; the previous deploy files were restored, $FAILURE_DETAIL, and the failed bundle is at $FAILED_ROOT"
