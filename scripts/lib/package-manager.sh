#!/usr/bin/env bash
# Shared package-manager resolution for local dev scripts.
# Load-guarded helper shared by local verification and start scripts.

if [[ -n "${ACCORD_PACKAGE_MANAGER_LOADED:-}" ]]; then
	return 0
fi
ACCORD_PACKAGE_MANAGER_LOADED=1

PNPM_CMD=()
PNPM_REQUIRED_VERSION="12.1.0"

resolve_pnpm() {
	if [[ -n "${PNPM:-}" ]]; then
		PNPM_CMD=("$PNPM")
	elif command -v corepack >/dev/null 2>&1; then
		local corepack_bin
		corepack_bin="$(command -v corepack)"
		if COREPACK_ENABLE_DOWNLOAD_PROMPT=0 "$corepack_bin" pnpm --version >/dev/null 2>&1; then
			PNPM_CMD=("$corepack_bin" "pnpm")
		elif command -v pnpm >/dev/null 2>&1; then
			PNPM_CMD=("$(command -v pnpm)")
		else
			if declare -F die >/dev/null 2>&1; then
				die "pnpm not found. Enable Corepack or set PNPM=/path/to/pnpm."
			fi
			echo "pnpm not found. Enable Corepack or set PNPM=/path/to/pnpm." >&2
			return 1
		fi
	elif command -v pnpm >/dev/null 2>&1; then
		PNPM_CMD=("$(command -v pnpm)")
	else
		if declare -F die >/dev/null 2>&1; then
			die "pnpm not found. Enable Corepack or set PNPM=/path/to/pnpm."
		fi
		echo "pnpm not found. Enable Corepack or set PNPM=/path/to/pnpm." >&2
		return 1
	fi

	local pnpm_version
	pnpm_version="$(COREPACK_ENABLE_DOWNLOAD_PROMPT=0 "${PNPM_CMD[@]}" --version 2>/dev/null || true)"
	if [[ "$pnpm_version" != "$PNPM_REQUIRED_VERSION" ]]; then
		local message="pnpm $PNPM_REQUIRED_VERSION is required; resolved ${pnpm_version:-an unusable command}. Enable Corepack or set PNPM to the pinned pnpm executable."
		if declare -F die >/dev/null 2>&1; then
			die "$message"
			return 1
		fi
		echo "$message" >&2
		return 1
	fi
}

run_pnpm() {
	resolve_pnpm || return 1
	"${PNPM_CMD[@]}" "$@"
}
