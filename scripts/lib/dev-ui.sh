#!/usr/bin/env bash
# Minimal, dependency-free terminal UI helpers for local dev scripts.
# Adapted from Atlas scripts/lib/dev-ui.sh (v1.1.0) — no behavior change,
# just the branding defaults below are Accord's.

if [[ -n "${DEV_UI_LOADED:-}" ]]; then
	return 0
fi
DEV_UI_LOADED=1

DEV_UI_APP_ID="${DEV_UI_APP_ID:-app}"
DEV_UI_APP_NAME="${DEV_UI_APP_NAME:-$DEV_UI_APP_ID}"
DEV_UI_COLOR="${DEV_UI_COLOR:-36}"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
	DEV_UI_RESET=$'\033[0m'
	DEV_UI_BOLD=$'\033[1m'
	DEV_UI_DIM=$'\033[2m'
	DEV_UI_ACCENT="$(printf '\033[%sm' "$DEV_UI_COLOR")"
	DEV_UI_GREEN=$'\033[32m'
	DEV_UI_YELLOW=$'\033[33m'
	DEV_UI_RED=$'\033[31m'
else
	DEV_UI_RESET=""
	DEV_UI_BOLD=""
	DEV_UI_DIM=""
	DEV_UI_ACCENT=""
	DEV_UI_GREEN=""
	DEV_UI_YELLOW=""
	DEV_UI_RED=""
fi

dev_ui_label() {
	printf "%b%-9s%b" "$DEV_UI_ACCENT" "[$DEV_UI_APP_ID]" "$DEV_UI_RESET"
}

ui_header() {
	local title="$1"
	printf "\n%b%s%b %b%s%b\n" "$DEV_UI_ACCENT" "$DEV_UI_APP_NAME" "$DEV_UI_RESET" "$DEV_UI_BOLD" "$title" "$DEV_UI_RESET"
	printf "%s %s\n" "$(dev_ui_label)" "----------------------------------------"
}

ui_step() {
	printf "%s %b>%b %s\n" "$(dev_ui_label)" "$DEV_UI_DIM" "$DEV_UI_RESET" "$*"
}

ui_ok() {
	printf "%s %bok%b   %s\n" "$(dev_ui_label)" "$DEV_UI_GREEN" "$DEV_UI_RESET" "$*"
}

ui_warn() {
	printf "%s %bwarn%b %s\n" "$(dev_ui_label)" "$DEV_UI_YELLOW" "$DEV_UI_RESET" "$*"
}

ui_error() {
	printf "%s %berr%b  %s\n" "$(dev_ui_label)" "$DEV_UI_RED" "$DEV_UI_RESET" "$*" >&2
}

ui_die() {
	ui_error "$*"
	exit 1
}

ui_kv() {
	local key="$1"
	local value="$2"
	printf "%s %-13s %s\n" "$(dev_ui_label)" "$key:" "$value"
}
