#!/usr/bin/env bash
# One-time installation of Accord's narrow password-free release entrypoint.
set -euo pipefail

die() { echo "install-release-wrapper: $1" >&2; exit 1; }
info() { echo "install-release-wrapper: $1"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SSH_TARGET="${MSIDC_SSH_TARGET:-msidc}"
OPERATOR="${ACCORD_VM_OPERATOR:-msidcadmin}"

[[ "$SSH_TARGET" =~ ^([A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "MSIDC_SSH_TARGET has an invalid format"
[[ "$OPERATOR" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "ACCORD_VM_OPERATOR has an invalid format"
for command_name in gh git scp ssh shasum; do
    command -v "$command_name" >/dev/null 2>&1 || die "missing command: $command_name"
done
CANONICAL_MAIN_SHA="$(gh api repos/Ornament-AI/accord/git/ref/heads/main --jq .object.sha)"
[[ "$CANONICAL_MAIN_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "could not resolve Ornament-AI/accord main from the authenticated GitHub API"
[[ "$(git -C "$ROOT" rev-parse HEAD)" == "$CANONICAL_MAIN_SHA" ]] \
    || die "install the wrapper only from the exact reviewed Ornament-AI/accord main head"
SUCCESSFUL_CI="$(gh api \
    "repos/Ornament-AI/accord/actions/workflows/ci.yml/runs?head_sha=${CANONICAL_MAIN_SHA}&status=success&per_page=100" \
    --jq "[.workflow_runs[] | select(.conclusion == \"success\" and .event == \"push\" and .head_branch == \"main\" and .head_sha == \"$CANONICAL_MAIN_SHA\")] | length")"
[[ "$SUCCESSFUL_CI" =~ ^[1-9][0-9]*$ ]] \
    || die "exact canonical main SHA does not have successful push CI"
LOCAL_TRUST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/accord-wrapper-trust.XXXXXXXXXX")"
REMOTE_PATH=""
REMOTE_VALIDATOR=""
cleanup() {
    [[ -z "$REMOTE_PATH" && -z "$REMOTE_VALIDATOR" ]] \
        || ssh "$SSH_TARGET" "rm -f '$REMOTE_PATH' '$REMOTE_VALIDATOR'" >/dev/null 2>&1 \
        || true
    rm -rf -- "$LOCAL_TRUST_ROOT"
}
trap cleanup EXIT
WRAPPER="$LOCAL_TRUST_ROOT/deploy-accord-wrapper.sh"
ENV_VALIDATOR="$LOCAL_TRUST_ROOT/validate-deploy-env.py"
git -C "$ROOT" show \
    "$CANONICAL_MAIN_SHA:deploy/deploy-accord-wrapper.sh" >"$WRAPPER" \
    || die "could not materialize the canonical deploy wrapper"
git -C "$ROOT" show \
    "$CANONICAL_MAIN_SHA:deploy/validate-deploy-env.py" >"$ENV_VALIDATOR" \
    || die "could not materialize the canonical environment validator"
chmod 0500 "$WRAPPER"
chmod 0500 "$ENV_VALIDATOR"
ssh -o BatchMode=yes "$SSH_TARGET" true >/dev/null 2>&1 \
    || die "SSH key access is not ready for $SSH_TARGET"

REMOTE_PATH="$(ssh "$SSH_TARGET" 'mktemp /tmp/accord-wrapper.XXXXXXXXXX')"
REMOTE_VALIDATOR="$(ssh "$SSH_TARGET" 'mktemp /tmp/accord-env-validator.XXXXXXXXXX')"
[[ "$REMOTE_PATH" =~ ^/tmp/accord-wrapper\.[A-Za-z0-9._-]+$ ]] \
    || die "remote wrapper staging path is invalid"
[[ "$REMOTE_VALIDATOR" =~ ^/tmp/accord-env-validator\.[A-Za-z0-9._-]+$ ]] \
    || die "remote environment validator staging path is invalid"

DIGEST="$(shasum -a 256 "$WRAPPER" | awk '{print $1}')"
VALIDATOR_DIGEST="$(shasum -a 256 "$ENV_VALIDATOR" | awk '{print $1}')"
scp -q "$WRAPPER" "$SSH_TARGET:$REMOTE_PATH"
scp -q "$ENV_VALIDATOR" "$SSH_TARGET:$REMOTE_VALIDATOR"
ssh "$SSH_TARGET" "chmod 0600 '$REMOTE_PATH' '$REMOTE_VALIDATOR'"
info "Enter the VM sudo password once. Routine signed releases will use only /usr/local/bin/deploy-accord."
ssh -t "$SSH_TARGET" "set -e;
  sudo test ! -L /opt;
  sudo chown root:root /opt;
  sudo chmod 0755 /opt;
  sudo test ! -L /opt/accord;
  sudo install -d -o root -g root -m 0755 /opt/accord;
  sudo test ! -L /opt/accord/deploy;
  sudo chown root:root /opt/accord/deploy;
  sudo chmod 0755 /opt/accord/deploy;
  sudo test -f /opt/accord/deploy/.env;
  sudo test ! -L /opt/accord/deploy/.env;
  sudo install -o root -g root -m 0600 '$REMOTE_VALIDATOR' /usr/local/bin/.accord-env-validator.new;
  printf '%s  %s\n' '$VALIDATOR_DIGEST' /usr/local/bin/.accord-env-validator.new | sudo sha256sum --check --status;
  if ! sudo /usr/bin/python3 /usr/local/bin/.accord-env-validator.new /opt/accord/deploy/.env --sanitize /opt/accord/deploy/.env.trusted-new; then
    sudo rm -f /usr/local/bin/.accord-env-validator.new;
    exit 1;
  fi;
  sudo chown root:root /opt/accord/deploy/.env.trusted-new;
  sudo chmod 0600 /opt/accord/deploy/.env.trusted-new;
  sudo mv -f /opt/accord/deploy/.env.trusted-new /opt/accord/deploy/.env;
  sudo rm -f /usr/local/bin/.accord-env-validator.new;
  sudo install -o root -g root -m 0600 '$REMOTE_PATH' /usr/local/bin/.deploy-accord.new;
  printf '%s  %s\n' '$DIGEST' /usr/local/bin/.deploy-accord.new | sudo sha256sum --check --status;
  sudo chmod 0755 /usr/local/bin/.deploy-accord.new;
  sudo mv -f /usr/local/bin/.deploy-accord.new /usr/local/bin/deploy-accord;
  printf '%s\n' '$OPERATOR ALL=(root) NOPASSWD: /usr/local/bin/deploy-accord *' | sudo tee /etc/sudoers.d/.accord-release.new >/dev/null;
  sudo chown root:root /etc/sudoers.d/.accord-release.new;
  sudo chmod 0440 /etc/sudoers.d/.accord-release.new;
  sudo visudo -cf /etc/sudoers.d/.accord-release.new;
  sudo mv -f /etc/sudoers.d/.accord-release.new /etc/sudoers.d/accord-release;
  sudo install -d -o root -g root -m 0700 /opt/accord/backups /opt/accord/backups/releases;
  sudo install -d -o root -g root -m 0700 /run/lock/accord-release;
  printf '%s  %s\n' '$DIGEST' /usr/local/bin/deploy-accord | sudo sha256sum --check --status"

ssh "$SSH_TARGET" "rm -f '$REMOTE_PATH' '$REMOTE_VALIDATOR'"
REMOTE_PATH=""
REMOTE_VALIDATOR=""
rm -rf -- "$LOCAL_TRUST_ROOT"
LOCAL_TRUST_ROOT=""
trap - EXIT
info "Accord's exact-SHA release wrapper is installed. Routine releases no longer need a sudo password."
