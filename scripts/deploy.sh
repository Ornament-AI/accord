#!/usr/bin/env bash
# Sync the minimal Accord deploy bundle to MSIDC and deploy an immutable SHA.

set -euo pipefail

G='\033[0;32m' R='\033[0;31m' N='\033[0m'
info() { echo -e "${G}✓${N} $1"; }
die() { echo -e "${R}✗${N} $1" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_TARGET="${MSIDC_SSH_TARGET:-msidcadmin@msidcacct}"
REMOTE_ROOT="${ACCORD_REMOTE_ROOT:-/opt/accord}"
FRESH_INSTALL="${ACCORD_CONFIRMED_FRESH_INSTALL:-false}"

[[ "$REMOTE_ROOT" =~ ^/[A-Za-z0-9._/+@:-]+$ && "$REMOTE_ROOT" != *..* ]] \
	|| die "ACCORD_REMOTE_ROOT must be a safe absolute path"
[[ "$FRESH_INSTALL" == "true" || "$FRESH_INSTALL" == "false" ]] \
	|| die "ACCORD_CONFIRMED_FRESH_INSTALL must be true or false"
command -v git >/dev/null 2>&1 || die "git is required"
command -v ssh >/dev/null 2>&1 || die "ssh is required"

git -C "$ROOT" fetch --quiet origin \
	+refs/heads/main:refs/remotes/origin/main

if [[ $# -gt 1 ]]; then
	die "Usage: scripts/deploy.sh [40-character-git-sha]"
fi
if [[ $# -eq 1 ]]; then
	TARGET_SHA="$(printf '%s' "$1" | tr 'A-F' 'a-f')"
else
	TARGET_SHA="$(git -C "$ROOT" ls-remote --exit-code origin refs/heads/main | awk 'NR == 1 {print $1}')"
fi
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] \
	|| die "Target must be a full 40-character Git SHA"
git -C "$ROOT" cat-file -e "$TARGET_SHA^{commit}" 2>/dev/null \
	|| die "Target commit is not present locally"
git -C "$ROOT" merge-base --is-ancestor "$TARGET_SHA" origin/main \
	|| die "Target commit is not reachable from origin/main"
if git -C "$ROOT" ls-tree -r --name-only "$TARGET_SHA" -- deploy/.env | grep -q .; then
	die "Target commit tracks deploy/.env; refusing to overwrite host-owned secrets"
fi

ssh -o BatchMode=yes "$SSH_TARGET" true >/dev/null 2>&1 \
	|| die "SSH key access is not ready for $SSH_TARGET"

info "Syncing the exact $TARGET_SHA deploy bundle to $SSH_TARGET:$REMOTE_ROOT"
git -C "$ROOT" archive --format=tar.gz "$TARGET_SHA" -- \
	deploy backend/scripts/create_roles.sql scripts/smoke-test.sh \
	scripts/provision_organization.py scripts/provision_member.py \
	| ssh "$SSH_TARGET" "mkdir -p '$REMOTE_ROOT' && tar -xzf - -C '$REMOTE_ROOT'"

info "Deploying Accord sha-$TARGET_SHA"
ssh "$SSH_TARGET" \
	"cd '$REMOTE_ROOT/deploy' && ACCORD_EXPECTED_SHA='$TARGET_SHA' ACCORD_CONFIRMED_FRESH_INSTALL='$FRESH_INSTALL' bash setup.sh"
info "Accord sha-$TARGET_SHA deployment finished"
