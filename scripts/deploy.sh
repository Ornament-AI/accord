#!/usr/bin/env bash
set -euo pipefail

# Deploy the current origin/main commit, or an explicit immutable commit, to the
# MSIDC VM. Requires SSH key auth to the VM (via Tailscale or direct).

G='\033[0;32m'
R='\033[0;31m'
N='\033[0m'
info() { echo -e "${G}✓${N} $1"; }
die()  { echo -e "${R}✗${N} $1" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER_SOURCE="$ROOT/deploy/deploy-accord-wrapper.sh"
RELEASE_STAGER="${ACCORD_RELEASE_STAGER:-$ROOT/scripts/stage-accord-release.sh}"

usage() {
    cat <<'EOF'
Usage: ./scripts/deploy.sh [40-character-git-sha]

With no argument, deploys the current origin/main commit. An explicit full SHA
can be supplied to deploy or roll back to a published immutable image.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 2
fi

command -v ssh >/dev/null 2>&1 || die "Missing required command: ssh"
command -v gh >/dev/null 2>&1 || die "Missing required command: gh"
[[ -x "$RELEASE_STAGER" ]] || die "Missing executable release stager: $RELEASE_STAGER"

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
    || die "Could not resolve a valid GitHub registry username"
[[ ${#ACCORD_GHCR_READ_TOKEN} -ge 20 && ${#ACCORD_GHCR_READ_TOKEN} -le 512 ]] \
    || die "Set ACCORD_GHCR_READ_TOKEN or install the read-packages token in the ornament-ai-accord-ghcr-read keychain item"
export ACCORD_GHCR_USERNAME ACCORD_GHCR_READ_TOKEN

if [[ $# -eq 1 ]]; then
    TARGET_SHA="$(printf '%s' "$1" | tr 'A-F' 'a-f')"
else
    command -v git >/dev/null 2>&1 || die "Missing required command: git"
    info "Resolving the current origin/main commit..."
    TARGET_SHA="$(git -C "$ROOT" ls-remote --exit-code origin refs/heads/main | awk 'NR == 1 { print $1 }')"
fi

[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "Target must be a full 40-character Git commit SHA"
[[ -f "$WRAPPER_SOURCE" ]] || die "Missing deploy wrapper source: $WRAPPER_SOURCE"

if [[ -n "${MSIDC_SSH_TARGET:-}" ]]; then
    SSH_CANDIDATES=("$MSIDC_SSH_TARGET")
else
    SSH_CANDIDATES=("msidc" "msidcadmin@msidcacct")
fi

MSIDC_SSH_TARGET=""
REACHABLE_TARGET=false
for candidate in "${SSH_CANDIDATES[@]}"; do
    if ssh -o BatchMode=yes "$candidate" true >/dev/null 2>&1; then
        REACHABLE_TARGET=true
        if ssh "$candidate" "cmp -s - /usr/local/bin/deploy-accord" <"$WRAPPER_SOURCE"; then
            MSIDC_SSH_TARGET="$candidate"
            break
        fi
    fi
done
if [[ -z "$MSIDC_SSH_TARGET" && "$REACHABLE_TARGET" == "true" ]]; then
    die "The VM deploy wrapper is stale. Sync the deploy bundle and install deploy/deploy-accord-wrapper.sh before retrying."
fi
[[ -n "$MSIDC_SSH_TARGET" ]] \
    || die "SSH key auth is not ready for msidc or msidcadmin@msidcacct. Check Tailscale connectivity and the MSIDC deploy key."

info "Downloading, validating, and staging Accord sha-$TARGET_SHA..."
REMOTE_RELEASE_ROOT="$(
    bash "$RELEASE_STAGER" "$TARGET_SHA" "$MSIDC_SSH_TARGET"
)"
[[ "$REMOTE_RELEASE_ROOT" =~ ^/tmp/accord-release-${TARGET_SHA}-[0-9]+-[0-9]+$ ]] \
    || die "Release stager returned an invalid remote path"
info "Deploying Accord sha-$TARGET_SHA to $MSIDC_SSH_TARGET..."
printf '%s\n%s\n' "$ACCORD_GHCR_USERNAME" "$ACCORD_GHCR_READ_TOKEN" \
    | ssh "$MSIDC_SSH_TARGET" \
        "sudo -n /usr/local/bin/deploy-accord '$TARGET_SHA' '$REMOTE_RELEASE_ROOT'"
unset ACCORD_GHCR_READ_TOKEN
printf '%s' "$TARGET_SHA" \
    | gh secret set ONPREM_DEPLOYED_SHA \
        --repo Ornament-AI/accord --env onprem-release \
    || die "Accord is live at $TARGET_SHA, but protected deployed-state evidence could not be updated"
info "Accord sha-$TARGET_SHA deploy finished"
