#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SSH_TARGET="${MSIDC_SSH_TARGET:-msidc}"
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || {
    echo "usage: $0 <exact-live-sha>" >&2
    exit 2
}
command -v gh >/dev/null && command -v python3 >/dev/null && command -v ssh >/dev/null
python3 "$ROOT/scripts/run-release-with-receipt.py" --repair "$SSH_TARGET" "$1"
