#!/usr/bin/env bash
set -euo pipefail

die() { echo "stage-accord-release: $1" >&2; exit 1; }

[[ $# -eq 2 ]] || die "usage: stage-accord-release <40-character-sha> <ssh-target>"
SHA="$1"
SSH_TARGET="$2"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "SHA must be 40 lowercase hexadecimal characters"
[[ "$SSH_TARGET" =~ ^([A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "SSH target has an invalid format"

for command in docker gh git openssl python3 scp ssh; do
    command -v "$command" >/dev/null 2>&1 || die "missing required command: $command"
done
GHCR_READ_TOKEN="${ACCORD_GHCR_READ_TOKEN:-}"
[[ "${ACCORD_GHCR_USERNAME:-}" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] \
    || die "ACCORD_GHCR_USERNAME is missing or invalid"
[[ ${#GHCR_READ_TOKEN} -ge 20 && ${#GHCR_READ_TOKEN} -le 512 ]] \
    || die "ACCORD_GHCR_READ_TOKEN is missing or invalid"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LOCAL_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/accord-release.XXXXXXXXXX")"
REMOTE_NAME="accord-release-${SHA}-$$-${RANDOM}"
REMOTE_ROOT="/tmp/$REMOTE_NAME"
cleanup() { rm -rf "$LOCAL_ROOT"; }
trap cleanup EXIT

DOWNLOAD_ROOT="$LOCAL_ROOT/download"
EXTRACTED="$LOCAL_ROOT/extracted"
mkdir "$DOWNLOAD_ROOT" "$EXTRACTED"
LIVE_SHA="$(ssh "$SSH_TARGET" 'sudo -n /usr/local/bin/deploy-accord --current-sha' 2>/dev/null || true)"
[[ -z "$LIVE_SHA" || "$LIVE_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "VM returned an invalid live release SHA"
RELEASE_TAG="onprem-sha-$SHA"
ASSET_PREFIX=""
if [[ -n "$LIVE_SHA" && "$LIVE_SHA" != "$SHA" ]]; then
    transition_prefix="rollback-from-${LIVE_SHA}-to-${SHA}-"
    transition_count="$(gh release view "onprem-sha-$LIVE_SHA" --repo Ornament-AI/accord \
        --json assets --jq "[.assets[].name | select(startswith(\"$transition_prefix\"))] | length" 2>/dev/null || true)"
    if [[ "$transition_count" == "4" ]]; then
        RELEASE_TAG="onprem-sha-$LIVE_SHA"
        ASSET_PREFIX="$transition_prefix"
    fi
fi
gh release download "$RELEASE_TAG" \
    --repo Ornament-AI/accord \
    --pattern "${ASSET_PREFIX}accord-deploy-sha-$SHA.tar.gz" \
    --pattern "${ASSET_PREFIX}onprem-release-$SHA.json" \
    --pattern "${ASSET_PREFIX}onprem-checksums-$SHA.txt" \
    --pattern "${ASSET_PREFIX}onprem-signature-$SHA.sig" \
    --dir "$DOWNLOAD_ROOT"
if [[ -n "$ASSET_PREFIX" ]]; then
    for name in "accord-deploy-sha-$SHA.tar.gz" "onprem-release-$SHA.json" \
        "onprem-checksums-$SHA.txt" "onprem-signature-$SHA.sig"; do
        mv "$DOWNLOAD_ROOT/${ASSET_PREFIX}${name}" "$DOWNLOAD_ROOT/$name"
    done
fi

ARCHIVE="$DOWNLOAD_ROOT/accord-deploy-sha-$SHA.tar.gz"
MANIFEST="$DOWNLOAD_ROOT/onprem-release-$SHA.json"
CHECKSUMS="$DOWNLOAD_ROOT/onprem-checksums-$SHA.txt"
SIGNATURE="$DOWNLOAD_ROOT/onprem-signature-$SHA.sig"
for path in "$ARCHIVE" "$MANIFEST" "$CHECKSUMS" "$SIGNATURE"; do
    [[ -f "$path" && ! -L "$path" ]] || die "release file is missing or unsafe"
done

openssl pkeyutl -verify -pubin -rawin \
    -inkey "$ROOT/deploy/onprem-release-signing-public.pem" \
    -in "$CHECKSUMS" \
    -sigfile "$SIGNATURE" >/dev/null \
    || die "release signature verification failed"
python3 - "$DOWNLOAD_ROOT" "$SHA" <<'PY'
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

python3 - "$ARCHIVE" "$EXTRACTED" <<'PY'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
with tarfile.open(archive, "r:gz") as source:
    source.extractall(destination, filter="data")
PY
python3 "$ROOT/scripts/vendor/onprem_release.py" validate \
    "$MANIFEST" --bundle-root "$EXTRACTED" >/dev/null
[[ "$(cat "$EXTRACTED/deploy/release-source-sha")" == "$SHA" ]] \
    || die "release bundle identity does not match requested SHA"
[[ -f "$EXTRACTED/deploy/release-tooling-source-sha" ]] \
    || die "release tooling identity is missing"
TOOLING_SHA="$(cat "$EXTRACTED/deploy/release-tooling-source-sha")"
[[ "$TOOLING_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release tooling identity is invalid"
git -C "$ROOT" cat-file -e "${TOOLING_SHA}^{commit}" 2>/dev/null \
    || die "release tooling commit is unavailable locally"
git -C "$ROOT" merge-base --is-ancestor "$SHA" "$TOOLING_SHA" \
    || die "rollback target is not an ancestor of its release tooling"
cmp -s "$ROOT/deploy/onprem-release-signing-public.pem" \
    "$EXTRACTED/deploy/onprem-release-signing-public.pem" \
    || die "release bundle contains an unexpected signing key"

# Prove this invocation's read-only credential can pull the exact signed image
# manifests before staging anything for privileged installation. Docker auth is
# confined to the already temporary release directory.
REGISTRY_CONFIG="$LOCAL_ROOT/docker-config"
mkdir -m 0700 "$REGISTRY_CONFIG"
printf '%s' "$GHCR_READ_TOKEN" \
    | docker --config "$REGISTRY_CONFIG" login ghcr.io \
        -u "$ACCORD_GHCR_USERNAME" --password-stdin >/dev/null \
    || die "the invocation-only credential cannot authenticate to GHCR"
for service in api web; do
    reference="$(
        python3 - "$MANIFEST" "$service" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
matches = [item["reference"] for item in manifest["images"] if item["service"] == sys.argv[2]]
if len(matches) != 1:
    raise SystemExit(f"expected one signed image reference for {sys.argv[2]}")
print(matches[0])
PY
    )"
    [[ "$reference" =~ ^ghcr\.io/ornament-ai/accord/(backend|web)@sha256:[0-9a-f]{64}$ ]] \
        || die "signed $service image reference is invalid"
    docker --config "$REGISTRY_CONFIG" manifest inspect "$reference" >/dev/null \
        || die "the invocation-only credential cannot pull signed $service image $reference"
done

scp -q -r "$DOWNLOAD_ROOT" "$SSH_TARGET:$REMOTE_ROOT"
printf '%s\n' "$REMOTE_ROOT"
