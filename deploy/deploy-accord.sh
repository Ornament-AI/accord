#!/usr/bin/env bash
set -euo pipefail

G='\033[0;32m'
R='\033[0;31m'
N='\033[0m'
info() { echo -e "${G}✓${N} $1"; }
die()  { echo -e "${R}✗${N} $1" >&2; exit 1; }

if [[ $# -ne 1 ]]; then
    die "usage: deploy-accord <40-character-git-sha>"
fi

DEPLOY_DIR="${ACCORD_DEPLOY_DIR:-/opt/accord/deploy}"
SHA="$(printf '%s' "$1" | tr 'A-F' 'a-f')"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "git SHA must contain exactly 40 hexadecimal characters"
TARGET_TAG="sha-$SHA"

compose_service_image() {
    local service="$1" image
    image="$(docker compose config --format json \
        | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service")" \
        || die "could not resolve the packaged $service image"
    [[ "$image" =~ ^ghcr\.io/ornament-ai/accord/(backend|web)@sha256:[0-9a-f]{64}$ ]] \
        || die "packaged $service image must be an exact Accord digest reference"
    printf '%s\n' "$image"
}

if [[ "$DEPLOY_DIR" != /* ]]; then
    DEPLOY_DIR="$PWD/$DEPLOY_DIR"
fi
command -v realpath >/dev/null 2>&1 || die "missing required command: realpath"

reject_symlink_components() {
    local path="$1" current="/" component
    path="${path#/}"
    while [[ -n "$path" ]]; do
        if [[ "$path" == */* ]]; then
            component="${path%%/*}"
            path="${path#*/}"
        else
            component="$path"
            path=""
        fi
        [[ -z "$component" || "$component" == "." ]] && continue
        current="${current%/}/$component"
        [[ -L "$current" ]] && return 1
    done
    return 0
}

reject_symlink_components "$DEPLOY_DIR" || die "deploy directory path must not contain symlinks: $DEPLOY_DIR"
DEPLOY_DIR="$(realpath "$DEPLOY_DIR" 2>/dev/null)" || die "deploy directory not found: $DEPLOY_DIR"
[[ -d "$DEPLOY_DIR" ]] || die "deploy directory not found: $DEPLOY_DIR"

secure_path_owner() {
    local path="$1" owner group mode group_mode other_mode effective_uid secret_file
    secret_file="${2:-false}"
    if owner="$(stat -c '%u' "$path" 2>/dev/null)"; then
        group="$(stat -c '%g' "$path" 2>/dev/null)"
        mode="$(stat -c '%a' "$path" 2>/dev/null)"
    else
        owner="$(stat -f '%u' "$path" 2>/dev/null)" || return 1
        group="$(stat -f '%g' "$path" 2>/dev/null)" || return 1
        mode="$(stat -f '%Lp' "$path" 2>/dev/null)" || return 1
    fi
    effective_uid="$(id -u)"
    if [[ "$owner" != "$effective_uid" ]]; then
        [[ -d "$path" && "$effective_uid" == "0" && "$owner" == "0" && "$group" == "0" ]] || return 1
    fi
    group_mode="${mode: -2:1}"
    other_mode="${mode: -1}"
    if [[ "$secret_file" == "true" ]]; then
        [[ "$group_mode" == "0" && "$other_mode" == "0" ]] || return 1
        return 0
    fi
    if [[ ! -d "$path" || "$effective_uid" != "0" || "$owner" != "0" || "$group" != "0" ]]; then
        [[ ! "$group_mode" =~ [2367] ]] || return 1
    fi
    [[ ! "$other_mode" =~ [2367] ]]
}

secure_trusted_ancestor() {
    local path="$1" owner group mode group_mode other_mode effective_uid
    if owner="$(stat -c '%u' "$path" 2>/dev/null)"; then
        group="$(stat -c '%g' "$path" 2>/dev/null)"
        mode="$(stat -c '%a' "$path" 2>/dev/null)"
    else
        owner="$(stat -f '%u' "$path" 2>/dev/null)" || return 1
        group="$(stat -f '%g' "$path" 2>/dev/null)" || return 1
        mode="$(stat -f '%Lp' "$path" 2>/dev/null)" || return 1
    fi
    effective_uid="$(id -u)"
    [[ "$owner" == "$effective_uid" || "$owner" == "0" ]] || return 1
    group_mode="${mode: -2:1}"
    other_mode="${mode: -1}"
    [[ ! "$group_mode" =~ [2367] ]] || return 1
    [[ ! "$other_mode" =~ [2367] ]]
}

TRUSTED_ANCESTOR="$DEPLOY_DIR"
while [[ "$TRUSTED_ANCESTOR" != "/" ]]; do
    TRUSTED_ANCESTOR="${TRUSTED_ANCESTOR%/*}"
    [[ -n "$TRUSTED_ANCESTOR" ]] || TRUSTED_ANCESTOR="/"
    secure_trusted_ancestor "$TRUSTED_ANCESTOR" \
        || die "deploy path ancestor must be trusted and not group/world-writable: $TRUSTED_ANCESTOR"
done

secure_path_owner "$DEPLOY_DIR" || die "deploy directory must be owned by the deploy user and not group/world-writable: $DEPLOY_DIR"
[[ -f "$DEPLOY_DIR/.env" ]] || die "deployment environment not found: $DEPLOY_DIR/.env"
secure_path_owner "$DEPLOY_DIR/.env" true || die "deployment environment must be owned by the deploy user with no group/other permissions"
[[ -f "$DEPLOY_DIR/setup.sh" ]] || die "setup script not found: $DEPLOY_DIR/setup.sh"
[[ -f "$DEPLOY_DIR/docker-compose.yml" ]] || die "compose file not found: $DEPLOY_DIR/docker-compose.yml"
[[ -f "$DEPLOY_DIR/release-source-sha" ]] || die "release identity not found: $DEPLOY_DIR/release-source-sha"
[[ -f "$DEPLOY_DIR/backup-before-migrate.sh" ]] || die "release backup helper not found: $DEPLOY_DIR/backup-before-migrate.sh"
secure_path_owner "$DEPLOY_DIR/setup.sh" || die "setup script must be owned by the deploy user and not group/world-writable"
secure_path_owner "$DEPLOY_DIR/docker-compose.yml" || die "compose file must be owned by the deploy user and not group/world-writable"
secure_path_owner "$DEPLOY_DIR/release-source-sha" || die "release identity must be owned by the deploy user and not group/world-writable"
[[ "$(cat "$DEPLOY_DIR/release-source-sha")" == "$SHA" ]] \
    || die "installed release bundle does not match requested SHA $SHA"
secure_path_owner "$DEPLOY_DIR/backup-before-migrate.sh" || die "release backup helper must be owned by the deploy user and not group/world-writable"

if [[ -f "$DEPLOY_DIR/release-bootstrap-evidence" && ! -L "$DEPLOY_DIR/release-bootstrap-evidence" ]]; then
    secure_path_owner "$DEPLOY_DIR/release-bootstrap-evidence" true \
        || die "bootstrap evidence must be owned by the deploy user with no group/other permissions"
    [[ "$(cat "$DEPLOY_DIR/release-bootstrap-evidence")" == "$SHA" ]] \
        || die "bootstrap evidence does not match requested SHA $SHA"
    BACKUP_EVIDENCE=""
else
    [[ -f "$DEPLOY_DIR/release-backup-evidence" && ! -L "$DEPLOY_DIR/release-backup-evidence" ]] \
        || die "verified release backup evidence not found"
    secure_path_owner "$DEPLOY_DIR/release-backup-evidence" true \
        || die "release backup evidence must be owned by the deploy user with no group/other permissions"
BACKUP_EVIDENCE_LINE_COUNT="$(wc -l <"$DEPLOY_DIR/release-backup-evidence" | tr -d '[:space:]')"
BACKUP_EVIDENCE_SHA="$(sed -n '1p' "$DEPLOY_DIR/release-backup-evidence")"
[[ "$BACKUP_EVIDENCE_LINE_COUNT" == "2" && "$BACKUP_EVIDENCE_SHA" == "$SHA" ]] \
    || die "release backup evidence does not match requested SHA $SHA"
BACKUP_EVIDENCE="$(sed -n '2p' "$DEPLOY_DIR/release-backup-evidence")"
BACKUP_ROOT="${ACCORD_RELEASE_BACKUP_DIR:-/opt/accord/backups/releases}"
[[ "$(dirname "$BACKUP_EVIDENCE")" == "$BACKUP_ROOT" ]] \
    || die "release backup evidence is outside the approved backup directory"
[[ "$(basename "$BACKUP_EVIDENCE")" =~ ^accord-pre-migrate-[0-9]{8}T[0-9]{6}Z-${SHA}\.dump$ ]] \
    || die "release backup evidence name does not match requested SHA $SHA"
for evidence_file in "$BACKUP_EVIDENCE" "$BACKUP_EVIDENCE.list" "$BACKUP_EVIDENCE.sha256"; do
    [[ -f "$evidence_file" && ! -L "$evidence_file" ]] \
        || die "release backup evidence file is missing or unsafe: $evidence_file"
    secure_path_owner "$evidence_file" true \
        || die "release backup evidence file must be owned by the deploy user with no group/other permissions"
done
for evidence_file in \
    "$BACKUP_EVIDENCE.minio.tar.gz" \
    "$BACKUP_EVIDENCE.minio.tar.gz.list" \
    "$BACKUP_EVIDENCE.minio.tar.gz.sha256"; do
    [[ -f "$evidence_file" && ! -L "$evidence_file" ]] \
        || die "release MinIO backup evidence file is missing or unsafe: $evidence_file"
    secure_path_owner "$evidence_file" true \
        || die "release MinIO backup evidence must be owned by the deploy user with no group/other permissions"
done
(cd "$BACKUP_ROOT" && sha256sum -c --status "$(basename "$BACKUP_EVIDENCE").sha256") \
    || die "release backup checksum verification failed"
(cd "$BACKUP_ROOT" && sha256sum -c --status "$(basename "$BACKUP_EVIDENCE").minio.tar.gz.sha256") \
    || die "release MinIO backup checksum verification failed"
grep -F "TABLE DATA" "$BACKUP_EVIDENCE.list" >/dev/null \
    || die "release backup listing has no table data entries"
tar -tzf "$BACKUP_EVIDENCE.minio.tar.gz" >/dev/null \
    || die "release MinIO backup archive could not be read back"
info "Verified paired PostgreSQL and MinIO pre-migration backup: $BACKUP_EVIDENCE"
fi

cd "$DEPLOY_DIR"
EXPECTED_BACKEND="$(compose_service_image api)"
EXPECTED_WEB="$(compose_service_image web)"
MIGRATION_STATE_FILE="/run/accord-release-migration-$SHA"
rm -f -- "$MIGRATION_STATE_FILE"
ACCORD_EXPECTED_SHA="$SHA" ACCORD_TAG="$TARGET_TAG" \
    ACCORD_MIGRATION_STATE_FILE="$MIGRATION_STATE_FILE" bash setup.sh

API_CID_OUTPUT="$(docker compose ps -q api 2>/dev/null)" \
    || die "could not inspect Accord API containers"
WORKER_CID_OUTPUT="$(docker compose ps -q worker 2>/dev/null)" \
    || die "could not inspect Accord worker containers"
WEB_CID_OUTPUT="$(docker compose ps -q web 2>/dev/null)" \
    || die "could not inspect Accord web containers"
[[ -n "$API_CID_OUTPUT" && "$API_CID_OUTPUT" != *$'\n'* ]] \
    || die "expected exactly one Accord API container"
[[ -n "$WORKER_CID_OUTPUT" && "$WORKER_CID_OUTPUT" != *$'\n'* ]] \
    || die "expected exactly one Accord worker container"
[[ -n "$WEB_CID_OUTPUT" && "$WEB_CID_OUTPUT" != *$'\n'* ]] \
    || die "expected exactly one Accord web container"
API_CID="$API_CID_OUTPUT"
WORKER_CID="$WORKER_CID_OUTPUT"
WEB_CID="$WEB_CID_OUTPUT"

ACTUAL_API="$(docker inspect --format '{{.Config.Image}}' "$API_CID")"
ACTUAL_WORKER="$(docker inspect --format '{{.Config.Image}}' "$WORKER_CID")"
ACTUAL_WEB="$(docker inspect --format '{{.Config.Image}}' "$WEB_CID")"

[[ "$ACTUAL_API" == "$EXPECTED_BACKEND" ]] || die "API image mismatch: expected $EXPECTED_BACKEND, found $ACTUAL_API"
[[ "$ACTUAL_WORKER" == "$EXPECTED_BACKEND" ]] || die "worker image mismatch: expected $EXPECTED_BACKEND, found $ACTUAL_WORKER"
[[ "$ACTUAL_WEB" == "$EXPECTED_WEB" ]] || die "web image mismatch: expected $EXPECTED_WEB, found $ACTUAL_WEB"
for cid in "$API_CID" "$WORKER_CID"; do
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$cid" \
        | grep -Fx "APP_VERSION=$TARGET_TAG" >/dev/null \
        || die "runtime APP_VERSION does not match $TARGET_TAG"
done
info "Verified API, worker, web, and APP_VERSION at $TARGET_TAG"

WEB_BINDING="$(docker port "$WEB_CID" 80/tcp)" \
    || die "could not resolve the running Accord web port"
[[ "$WEB_BINDING" =~ ^127\.0\.0\.1:([0-9]+)$ ]] \
    || die "Accord web must publish exactly one loopback port, found: $WEB_BINDING"
WEB_PORT="${BASH_REMATCH[1]}"
curl -fsS --max-time 10 "http://127.0.0.1:$WEB_PORT/api/healthz" >/dev/null \
    || die "Accord health check failed"
curl -fsS --max-time 10 "http://127.0.0.1:$WEB_PORT/api/readyz" >/dev/null \
    || die "Accord readiness check failed"

docker compose ps
info "Accord deployment verified"
