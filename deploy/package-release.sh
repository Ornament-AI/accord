#!/usr/bin/env bash
# Assemble Accord's exact committed VM bundle and shared release evidence.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
OUTPUT_ROOT="${1:-${RUNNER_TEMP:-$REPO_ROOT/.release-output}}"
TOOLING_SHA="${SOURCE_SHA:-${GITHUB_SHA:-}}"
COMMIT_SHA="${ACCORD_RELEASE_SHA:-$TOOLING_SHA}"
LEGACY_ROLLBACK_SHA="8cc2f95d00d35ab6eb9d4ace31b2f605af10d10d"
WORKFLOW_RUN_ID="${GITHUB_RUN_ID:-}"
BACKEND_DIGEST="${ACCORD_BACKEND_DIGEST:-}"
WEB_DIGEST="${ACCORD_WEB_DIGEST:-}"

die() {
    echo "package-release: $1" >&2
    exit 1
}

replace_compose_image() {
    local file="$1" old="$2" new="$3" expected="$4" count temporary
    count="$(grep -Fxc "    image: $old" "$file" || true)"
    [[ "$count" == "$expected" ]] \
        || die "expected $expected exact Compose image entries for $old, found $count"
    temporary="$(mktemp "${file}.XXXXXXXXXX")"
    awk -v old="    image: $old" -v new="    image: $new" \
        '{ if ($0 == old) $0 = new; print }' "$file" >"$temporary"
    mv -f "$temporary" "$file"
}

replace_exact_line() {
    local file="$1" old="$2" new="$3" expected="$4" count temporary
    count="$(grep -Fxc "$old" "$file" || true)"
    [[ "$count" == "$expected" ]] \
        || die "expected $expected exact entries for $old, found $count"
    temporary="$(mktemp "${file}.XXXXXXXXXX")"
    awk -v old="$old" -v new="$new" \
        '{ if ($0 == old) $0 = new; print }' "$file" >"$temporary"
    mv -f "$temporary" "$file"
}

[[ "$TOOLING_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "SOURCE_SHA must be the exact 40-character lowercase release commit."
[[ "$COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "ACCORD_RELEASE_SHA must be a 40-character lowercase commit."
if [[ "$COMMIT_SHA" != "$TOOLING_SHA" && "$COMMIT_SHA" != "$LEGACY_ROLLBACK_SHA" ]]; then
    die "only the fixed pre-contract production rollback commit may differ from SOURCE_SHA"
fi
[[ "$WORKFLOW_RUN_ID" =~ ^[1-9][0-9]*$ ]] \
    || die "GITHUB_RUN_ID must identify the successful publication workflow."
[[ "$BACKEND_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || die "ACCORD_BACKEND_DIGEST must be a SHA-256 manifest digest."
[[ "$WEB_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || die "ACCORD_WEB_DIGEST must be a SHA-256 manifest digest."
git -C "$REPO_ROOT" cat-file -e "${TOOLING_SHA}^{commit}" 2>/dev/null \
    || die "SOURCE_SHA is not available in the checked-out repository."
git -C "$REPO_ROOT" cat-file -e "${COMMIT_SHA}^{commit}" 2>/dev/null \
    || die "ACCORD_RELEASE_SHA is not available in the checked-out repository."
[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$TOOLING_SHA" ]] \
    || die "The checked-out commit does not match SOURCE_SHA."

mkdir -p "$OUTPUT_ROOT"
MANIFEST_PATH="$OUTPUT_ROOT/onprem-release-$COMMIT_SHA.json"
ARCHIVE_PATH="$OUTPUT_ROOT/accord-deploy-sha-$COMMIT_SHA.tar.gz"
[[ ! -e "$MANIFEST_PATH" ]] || die "refusing to overwrite $MANIFEST_PATH"
[[ ! -e "$ARCHIVE_PATH" ]] || die "refusing to overwrite $ARCHIVE_PATH"

STAGE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/accord-release.XXXXXXXXXX")"
cleanup() {
    rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

# Keep this list aligned with package.sh. Git supplies the bytes, so local
# secrets, generated files, and untracked scripts cannot enter the release.
DEPLOY_FILES=(
    deploy/docker-compose.yml
    deploy/.env.example
    deploy/create_roles.sql
    deploy/setup.sh
    deploy/deploy-accord.sh
    deploy/deploy-accord-wrapper.sh
    deploy/backup-before-migrate.sh
    deploy/onprem-release-signing-public.pem
    deploy/nginx
    deploy/object-storage
    scripts/smoke-test.sh
    scripts/vendor/onprem_release.py
)
git -C "$REPO_ROOT" archive --format=tar "$TOOLING_SHA" "${DEPLOY_FILES[@]}" \
    | tar -xf - -C "$STAGE_ROOT"
printf '%s\n' "$COMMIT_SHA" >"$STAGE_ROOT/deploy/release-source-sha"
printf '%s\n' "$TOOLING_SHA" >"$STAGE_ROOT/deploy/release-tooling-source-sha"
replace_exact_line \
    "$STAGE_ROOT/deploy/.env.example" \
    'ACCORD_TAG=latest' \
    "ACCORD_TAG=sha-$COMMIT_SHA" 1
mv "$STAGE_ROOT/scripts/vendor/onprem_release.py" \
    "$STAGE_ROOT/deploy/onprem_release.py"
mv "$STAGE_ROOT/scripts/smoke-test.sh" "$STAGE_ROOT/deploy/smoke-test.sh"
rmdir "$STAGE_ROOT/scripts/vendor" "$STAGE_ROOT/scripts"

BACKEND_REF="ghcr.io/ornament-ai/accord/backend@$BACKEND_DIGEST"
WEB_REF="ghcr.io/ornament-ai/accord/web@$WEB_DIGEST"
replace_compose_image \
    "$STAGE_ROOT/deploy/docker-compose.yml" \
    'ghcr.io/ornament-ai/accord/backend:${ACCORD_TAG:-latest}' \
    "$BACKEND_REF" 3
replace_compose_image \
    "$STAGE_ROOT/deploy/docker-compose.yml" \
    'ghcr.io/ornament-ai/accord/web:${ACCORD_TAG:-latest}' \
    "$WEB_REF" 1
python3 "$STAGE_ROOT/deploy/onprem_release.py" build \
    --adapter "$SCRIPT_DIR/onprem-release-adapter.json" \
    --bundle-root "$STAGE_ROOT" \
    --commit-sha "$COMMIT_SHA" \
    --workflow-run-id "$WORKFLOW_RUN_ID" \
    --output "$MANIFEST_PATH"
python3 "$STAGE_ROOT/deploy/onprem_release.py" validate \
    "$MANIFEST_PATH" \
    --bundle-root "$STAGE_ROOT"

COPYFILE_DISABLE=1 tar -czf "$ARCHIVE_PATH" -C "$STAGE_ROOT" deploy
echo "Created release archive: $ARCHIVE_PATH"
echo "Created standard release evidence: $MANIFEST_PATH"
