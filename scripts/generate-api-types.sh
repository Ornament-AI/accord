#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND/.venv/bin/python}"
SCHEMA_PATH="$ROOT/tmp/openapi-spec.json"
OUTPUT_PATH="${1:-$FRONTEND/src/types/api.generated.ts}"

DEV_UI_APP_ID="accord"
DEV_UI_APP_NAME="Accord"
DEV_UI_COLOR="34"
# shellcheck source=scripts/lib/dev-ui.sh
source "$ROOT/scripts/lib/dev-ui.sh"
ui_header "Generate API Types"
die() { ui_die "$1"; }
# shellcheck source=scripts/lib/package-manager.sh
source "$ROOT/scripts/lib/package-manager.sh"

if [[ "$PYTHON_BIN" != */* ]]; then
	if ! PYTHON_BIN_RESOLVED="$(command -v "$PYTHON_BIN")"; then
		die "Python executable not found: $PYTHON_BIN"
	fi
else
	PYTHON_BIN_RESOLVED="$PYTHON_BIN"
fi

if [[ ! -x "$PYTHON_BIN_RESOLVED" ]]; then
	if [[ "$PYTHON_BIN" == "$BACKEND/.venv/bin/python" ]]; then
		die "Backend venv missing. Run: ./scripts/dev-setup.sh"
	else
		die "Python executable is not executable: $PYTHON_BIN"
	fi
fi

mkdir -p "$(dirname "$SCHEMA_PATH")" "$(dirname "$OUTPUT_PATH")"

ui_step "exporting OpenAPI spec from backend"
"$PYTHON_BIN_RESOLVED" "$BACKEND/scripts/export_openapi.py" "$SCHEMA_PATH"

cd "$FRONTEND"
ui_step "generating TypeScript types"
run_pnpm exec openapi-typescript "$SCHEMA_PATH" -o "$OUTPUT_PATH"
ui_kv "generated" "$OUTPUT_PATH"
