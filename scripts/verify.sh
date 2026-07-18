#!/usr/bin/env bash
# Canonical local verification contract for Accord.
# Adapted from Atlas scripts/verify.sh (v1.1.0): env/venv paths renamed for
# Accord, no Firebase, and every backend/frontend step is guarded so a
# lane that hasn't landed a given piece yet prints a clear notice and is
# skipped rather than crashing with an unclear stack trace. A step that DID
# run and failed still fails the whole script (non-zero exit).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/backend/.venv/bin/python}"

# shellcheck source=scripts/lib/package-manager.sh
source "$ROOT/scripts/lib/package-manager.sh"
PNPM_RESOLVED=0

FAILED=0
SKIPPED=0

die_step() {
	printf 'error: %s\n' "$1" >&2
	FAILED=1
}

skip_step() {
	printf 'skip:  %s\n' "$1"
	SKIPPED=1
}

step() {
	printf '\n==> %s\n' "$1"
}

run_step() {
	# run_step <description> <command...>
	local desc="$1"
	shift
	if "$@"; then
		return 0
	fi
	die_step "$desc failed"
	return 1
}

cd "$ROOT"

step "Validate shell syntax"
while IFS= read -r -d '' script; do
	if ! bash -n "$script"; then
		die_step "bash -n failed for $script"
	fi
done < <(find scripts deploy -type f -name '*.sh' -print0 2>/dev/null)

step "Lint backend"
if [[ -x "$PYTHON_BIN" && -f "$ROOT/backend/requirements.txt" ]]; then
	run_step "ruff check" "$PYTHON_BIN" -m ruff check backend/app backend/tests
	run_step "ruff format --check" "$PYTHON_BIN" -m ruff format --check backend/app backend/tests
else
	skip_step "backend lint — backend/.venv or backend/requirements.txt not found (backend lane not fully landed / venv not created; run ./scripts/start.sh --backend-only once to bootstrap the venv)"
fi

step "Run backend tests"
if [[ -x "$PYTHON_BIN" && -d "$ROOT/backend/tests" ]]; then
	run_step "backend pytest" "$PYTHON_BIN" -m pytest backend/tests -q
else
	skip_step "backend tests — backend/.venv or backend/tests not found"
fi

step "Check generated API types"
if [[ -x "$ROOT/scripts/generate-api-types.sh" ]]; then
	PYTHON_BIN="$PYTHON_BIN" "$ROOT/scripts/generate-api-types.sh" || die_step "generate-api-types.sh failed"
	if ! git diff --exit-code -- frontend/src/types/api.generated.ts; then
		die_step "frontend/src/types/api.generated.ts is out of date — run ./scripts/generate-api-types.sh and commit the diff"
	fi
else
	skip_step "API type drift check — scripts/generate-api-types.sh does not exist yet (pending wiring of backend/scripts/export_openapi.py -> frontend/src/types/api.generated.ts; see docs/atlas-upstream-manifest.md §2A)"
fi

step "Lint frontend"
if [[ -f "$ROOT/frontend/package.json" ]]; then
	if (( ! PNPM_RESOLVED )); then resolve_pnpm && PNPM_RESOLVED=1 || die_step "pnpm not found"; fi
	run_step "frontend lint" "${PNPM_CMD[@]}" --filter frontend lint
else
	skip_step "frontend lint — frontend/package.json not found"
fi

step "Check frontend formatting"
if [[ -f "$ROOT/frontend/package.json" ]]; then
	if (( ! PNPM_RESOLVED )); then resolve_pnpm && PNPM_RESOLVED=1 || die_step "pnpm not found"; fi
	run_step "frontend format:check" "${PNPM_CMD[@]}" --filter frontend format:check
else
	skip_step "frontend format check — frontend/package.json not found"
fi

step "Typecheck frontend"
if [[ -f "$ROOT/frontend/package.json" ]]; then
	if (( ! PNPM_RESOLVED )); then resolve_pnpm && PNPM_RESOLVED=1 || die_step "pnpm not found"; fi
	run_step "frontend typecheck" "${PNPM_CMD[@]}" --filter frontend typecheck
else
	skip_step "frontend typecheck — frontend/package.json not found"
fi

step "Run frontend tests"
if [[ -f "$ROOT/frontend/package.json" ]]; then
	if (( ! PNPM_RESOLVED )); then resolve_pnpm && PNPM_RESOLVED=1 || die_step "pnpm not found"; fi
	run_step "frontend test:run" "${PNPM_CMD[@]}" --filter frontend test:run
else
	skip_step "frontend tests — frontend/package.json not found"
fi

step "Build frontend"
if [[ -f "$ROOT/frontend/package.json" ]]; then
	if (( ! PNPM_RESOLVED )); then resolve_pnpm && PNPM_RESOLVED=1 || die_step "pnpm not found"; fi
	run_step "frontend build" "${PNPM_CMD[@]}" --filter frontend build
else
	skip_step "frontend build — frontend/package.json not found"
fi

echo
if [[ "$FAILED" -ne 0 ]]; then
	printf 'Verification FAILED — see errors above.\n' >&2
	exit 1
fi
if [[ "$SKIPPED" -ne 0 ]]; then
	printf 'Verification passed all steps that ran, but some steps were SKIPPED (see "skip:" lines above) because a cross-lane dependency has not landed yet.\n'
	exit 0
fi
printf 'All local verification checks passed.\n'
