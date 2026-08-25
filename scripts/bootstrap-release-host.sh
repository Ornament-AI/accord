#!/usr/bin/env bash
# Explicit first-host bootstrap. This is intentionally separate from updates.
set -euo pipefail

die() { echo "bootstrap-release-host: $1" >&2; exit 1; }
info() { echo "bootstrap-release-host: $1"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SSH_TARGET="${MSIDC_SSH_TARGET:-msidc}"
OPERATOR="${ACCORD_VM_OPERATOR:-msidcadmin}"
ENV_FILE="${ACCORD_BOOTSTRAP_ENV_FILE:-}"
STAGER="$ROOT/scripts/stage-accord-release.sh"

[[ $# -le 1 ]] || die "usage: ACCORD_BOOTSTRAP_ENV_FILE=/secure/path/.env $0 [main-sha]"
[[ -n "$ENV_FILE" && "$ENV_FILE" == /* && -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] \
    || die "ACCORD_BOOTSTRAP_ENV_FILE must be an absolute regular non-symlink file"
[[ "$(stat -f '%u:%Lp' "$ENV_FILE")" == "$(id -u):600" ]] \
    || die "bootstrap environment must be owned by the operator with mode 0600"
[[ "$SSH_TARGET" =~ ^([A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "MSIDC_SSH_TARGET has an invalid format"
[[ "$OPERATOR" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "ACCORD_VM_OPERATOR has an invalid format"
for command_name in gh git scp shasum ssh; do
    command -v "$command_name" >/dev/null 2>&1 || die "missing command: $command_name"
done

ACCORD_GHCR_USERNAME="${ACCORD_GHCR_USERNAME:-$(gh api user --jq .login)}"
ACCORD_GHCR_READ_TOKEN="${ACCORD_GHCR_READ_TOKEN:-}"
if [[ -z "$ACCORD_GHCR_READ_TOKEN" ]] && command -v security >/dev/null 2>&1; then
    ACCORD_GHCR_READ_TOKEN="$(
        security find-generic-password \
            -s ornament-ai-accord-ghcr-read \
            -a "$ACCORD_GHCR_USERNAME" -w 2>/dev/null || true
    )"
fi
[[ "$ACCORD_GHCR_USERNAME" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] \
    || die "could not resolve a valid GitHub registry username"
[[ ${#ACCORD_GHCR_READ_TOKEN} -ge 20 && ${#ACCORD_GHCR_READ_TOKEN} -le 512 ]] \
    || die "set ACCORD_GHCR_READ_TOKEN or install the read-packages token in the ornament-ai-accord-ghcr-read keychain item"
export ACCORD_GHCR_USERNAME ACCORD_GHCR_READ_TOKEN

MAIN_SHA="$(gh api repos/Ornament-AI/accord/git/ref/heads/main --jq .object.sha)"
[[ "$MAIN_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "could not resolve Ornament-AI/accord main from the authenticated GitHub API"
SHA="${1:-$MAIN_SHA}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ && "$SHA" == "$MAIN_SHA" ]] \
    || die "fresh bootstrap is allowed only for the exact current Ornament-AI/accord main SHA"
[[ "$(git -C "$ROOT" rev-parse HEAD)" == "$MAIN_SHA" ]] \
    || die "run bootstrap only from the exact reviewed Ornament-AI/accord main checkout"
[[ -z "$(git -C "$ROOT" status --short --untracked-files=no -- \
    scripts/bootstrap-release-host.sh scripts/stage-accord-release.sh \
    deploy/deploy-accord-wrapper.sh deploy/onprem-release-signing-public.pem \
    scripts/vendor/onprem_release.py)" ]] \
    || die "refusing modified bootstrap trust-path files"
SUCCESSFUL_CI="$(gh api \
    "repos/Ornament-AI/accord/actions/workflows/ci.yml/runs?head_sha=${MAIN_SHA}&status=success&per_page=100" \
    --jq "[.workflow_runs[] | select(.conclusion == \"success\" and .event == \"push\" and .head_branch == \"main\" and .head_sha == \"$MAIN_SHA\")] | length")"
[[ "$SUCCESSFUL_CI" =~ ^[1-9][0-9]*$ ]] \
    || die "exact canonical main SHA does not have successful push CI"
LOCAL_TRUST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/accord-bootstrap-trust.XXXXXXXXXX")"
REMOTE_WRAPPER=""
REMOTE_ENV=""
cleanup() {
    [[ -z "$REMOTE_WRAPPER" && -z "$REMOTE_ENV" ]] \
        || ssh "$SSH_TARGET" "rm -f '$REMOTE_WRAPPER' '$REMOTE_ENV'" >/dev/null 2>&1 \
        || true
    rm -rf -- "$LOCAL_TRUST_ROOT"
}
trap cleanup EXIT
WRAPPER="$LOCAL_TRUST_ROOT/deploy-accord-wrapper.sh"
ENV_SNAPSHOT="$LOCAL_TRUST_ROOT/accord.env"
git -C "$ROOT" show "$MAIN_SHA:deploy/deploy-accord-wrapper.sh" >"$WRAPPER" \
    || die "could not materialize the canonical deploy wrapper"
chmod 0500 "$WRAPPER"
/usr/bin/python3 - "$ENV_FILE" "$ENV_SNAPSHOT" "$(id -u)" <<'PY'
import os
import re
import stat
import sys

source_path, destination_path, expected_uid_text = sys.argv[1:]
expected_uid = int(expected_uid_text)
allowed = {
    "ACCORD_DB_PASSWORD", "ACCORD_DB_USER", "ACCORD_DB_NAME", "ACCORD_TAG",
    "ACCORD_WEB_PORT", "DATABASE_URL", "MIGRATIONS_DATABASE_URL",
    "WORKER_DATABASE_URL", "WORKOS_CLIENT_ID", "WORKOS_API_KEY",
    "WORKOS_REDIRECT_URI", "WORKOS_WEBHOOK_SECRET", "SESSION_SECRET_KEY",
    "SESSION_COOKIE_NAME", "ENVIRONMENT", "CORS_ORIGINS", "PUBLIC_APP_URL",
    "BASE_URL", "LOG_LEVEL", "DEV_AUTH_BYPASS", "DB_POOL_SIZE",
    "DB_STATEMENT_TIMEOUT_MS", "OBJECT_STORAGE_ENDPOINT", "OBJECT_STORAGE_BUCKET",
    "OBJECT_STORAGE_ACCESS_KEY", "OBJECT_STORAGE_SECRET_KEY",
}
source = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    before = os.fstat(source)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != expected_uid:
        raise SystemExit("bootstrap environment is not an operator-owned regular file")
    if stat.S_IMODE(before.st_mode) != 0o600 or not 1 <= before.st_size <= 1_048_576:
        raise SystemExit("bootstrap environment ownership, mode, or size is invalid")
    content = os.read(source, 1_048_577)
    after = os.fstat(source)
    stable_fields = (
        "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_size",
        "st_mtime_ns", "st_ctime_ns",
    )
    if len(content) != before.st_size or any(
        getattr(before, field) != getattr(after, field) for field in stable_fields
    ):
        raise SystemExit("bootstrap environment changed while being snapshotted")
finally:
    os.close(source)
text = content.decode("utf-8")
for lineno, raw in enumerate(text.splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:]
    if "=" not in line:
        continue
    key = line.split("=", 1)[0].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key not in allowed:
        raise SystemExit(f"bootstrap environment line {lineno} uses unsupported variable {key!r}")
destination = os.open(
    destination_path,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
    0o600,
)
try:
    view = memoryview(content)
    while view:
        written = os.write(destination, view)
        view = view[written:]
    os.fchmod(destination, 0o600)
    os.fsync(destination)
finally:
    os.close(destination)
PY
ssh -o BatchMode=yes "$SSH_TARGET" true >/dev/null 2>&1 || die "SSH key access is not ready"

info "Authenticating and staging signed release $SHA before host mutation"
REMOTE_RELEASE_ROOT="$(bash "$STAGER" "$SHA" "$SSH_TARGET")"
[[ "$REMOTE_RELEASE_ROOT" =~ ^/tmp/accord-release-${SHA}-[0-9]+-[0-9]+$ ]] \
    || die "release stager returned an invalid remote path"
REMOTE_WRAPPER="$(ssh "$SSH_TARGET" 'mktemp /tmp/accord-bootstrap-wrapper.XXXXXXXXXX')"
REMOTE_ENV="$(ssh "$SSH_TARGET" 'mktemp /tmp/accord-bootstrap-env.XXXXXXXXXX')"
[[ "$REMOTE_WRAPPER" =~ ^/tmp/accord-bootstrap-wrapper\.[A-Za-z0-9._-]+$ \
    && "$REMOTE_ENV" =~ ^/tmp/accord-bootstrap-env\.[A-Za-z0-9._-]+$ ]] \
    || die "remote bootstrap staging paths are invalid"
scp -q "$WRAPPER" "$SSH_TARGET:$REMOTE_WRAPPER"
scp -q "$ENV_SNAPSHOT" "$SSH_TARGET:$REMOTE_ENV"
ssh "$SSH_TARGET" "chmod 0600 '$REMOTE_WRAPPER' '$REMOTE_ENV'"
WRAPPER_DIGEST="$(shasum -a 256 "$WRAPPER" | awk '{print $1}')"
ENV_DIGEST="$(shasum -a 256 "$ENV_SNAPSHOT" | awk '{print $1}')"

info "Enter the VM sudo password once to create the empty-host trust boundary"
ssh -t "$SSH_TARGET" "set -e;
  test -z \"\$(docker ps -aq --filter label=com.docker.compose.project.working_dir=/opt/accord/deploy)\";
  ! docker volume inspect accord_pgdata >/dev/null 2>&1;
  ! docker volume inspect accord_minio-data >/dev/null 2>&1;
  sudo test ! -e /opt/accord/deploy;
  sudo install -o root -g root -m 0600 '$REMOTE_WRAPPER' /usr/local/bin/.deploy-accord.new;
  printf '%s  %s\n' '$WRAPPER_DIGEST' /usr/local/bin/.deploy-accord.new | sudo sha256sum --check --status;
  sudo chmod 0755 /usr/local/bin/.deploy-accord.new;
  sudo mv -f /usr/local/bin/.deploy-accord.new /usr/local/bin/deploy-accord;
  sudo install -d -o root -g root -m 0755 /opt/accord /opt/accord/deploy;
  sudo install -o root -g root -m 0600 '$REMOTE_ENV' /opt/accord/deploy/.env.new;
  printf '%s  %s\n' '$ENV_DIGEST' /opt/accord/deploy/.env.new | sudo sha256sum --check --status;
  sudo mv /opt/accord/deploy/.env.new /opt/accord/deploy/.env;
  sudo install -d -o root -g root -m 0700 /opt/accord/backups /opt/accord/backups/releases /run/lock/accord-release;
  printf '%s\n' '$OPERATOR ALL=(root) NOPASSWD: /usr/local/bin/deploy-accord *' | sudo tee /etc/sudoers.d/accord-release >/dev/null;
  sudo chown root:root /etc/sudoers.d/accord-release;
  sudo chmod 0440 /etc/sudoers.d/accord-release;
  sudo visudo -cf /etc/sudoers.d/accord-release;
  printf '%s\n' '$SHA' | sudo tee '/opt/accord/.allow-first-release-$SHA' >/dev/null;
  sudo chown root:root '/opt/accord/.allow-first-release-$SHA';
  sudo chmod 0600 '/opt/accord/.allow-first-release-$SHA'"

printf '%s\n%s\n' "$ACCORD_GHCR_USERNAME" "$ACCORD_GHCR_READ_TOKEN" \
    | ssh "$SSH_TARGET" "sudo -n /usr/local/bin/deploy-accord '$SHA' '$REMOTE_RELEASE_ROOT'"
unset ACCORD_GHCR_READ_TOKEN
ssh "$SSH_TARGET" "rm -f '$REMOTE_WRAPPER' '$REMOTE_ENV'"
REMOTE_WRAPPER=""
REMOTE_ENV=""
rm -rf -- "$LOCAL_TRUST_ROOT"
LOCAL_TRUST_ROOT=""
trap - EXIT
info "Fresh Accord host deployed at signed exact SHA $SHA"
