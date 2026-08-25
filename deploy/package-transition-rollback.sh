#!/usr/bin/env bash
# Build a rollback bundle authenticated by the previous signed release.
set -euo pipefail

[[ $# -eq 3 ]] || { echo "usage: package-transition-rollback <from-sha> <to-sha> <output>" >&2; exit 2; }
FROM_SHA="$1"
TO_SHA="$2"
OUTPUT_ROOT="$3"
[[ "$FROM_SHA" =~ ^[0-9a-f]{40}$ && "$TO_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$FROM_SHA" != "$TO_SHA" ]] || exit 2
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEMP_ROOT="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/accord-transition.XXXXXXXXXX")"
trap 'rm -rf "$TEMP_ROOT"' EXIT
mkdir "$TEMP_ROOT/download" "$TEMP_ROOT/extracted"

gh release download "onprem-sha-$TO_SHA" --repo Ornament-AI/accord \
    --pattern "accord-deploy-sha-$TO_SHA.tar.gz" \
    --pattern "onprem-release-$TO_SHA.json" \
    --pattern "onprem-checksums-$TO_SHA.txt" \
    --pattern "onprem-signature-$TO_SHA.sig" --dir "$TEMP_ROOT/download"
cd "$TEMP_ROOT/download"
openssl pkeyutl -verify -pubin -rawin \
    -inkey "$ROOT/deploy/onprem-release-signing-public.pem" \
    -in "onprem-checksums-$TO_SHA.txt" -sigfile "onprem-signature-$TO_SHA.sig" >/dev/null
sha256sum --check --status "onprem-checksums-$TO_SHA.txt"
tar -xzf "accord-deploy-sha-$TO_SHA.tar.gz" -C "$TEMP_ROOT/extracted"
python3 "$ROOT/scripts/vendor/onprem_release.py" validate \
    "onprem-release-$TO_SHA.json" --bundle-root "$TEMP_ROOT/extracted" >/dev/null
[[ "$(cat "$TEMP_ROOT/extracted/deploy/release-source-sha")" == "$TO_SHA" ]]

readarray -t DIGESTS < <(python3 - "onprem-release-$TO_SHA.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for service in ("api", "web"):
    values = [item["reference"].rsplit("@", 1)[-1] for item in manifest["images"] if item["service"] == service]
    if len(values) != 1:
        raise SystemExit(f"expected one {service} image")
    print(values[0])
PY
)
[[ ${#DIGESTS[@]} -eq 2 ]]
cd "$ROOT"
SOURCE_SHA="$FROM_SHA" ACCORD_RELEASE_SHA="$TO_SHA" \
    ACCORD_PREVIOUS_DEPLOYED_SHA="$FROM_SHA" \
    ACCORD_BACKEND_DIGEST="${DIGESTS[0]}" ACCORD_WEB_DIGEST="${DIGESTS[1]}" \
    bash deploy/package-release.sh "$OUTPUT_ROOT"
