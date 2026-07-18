#!/usr/bin/env bash
# Show local Accord dev process and port status.
# Adapted from Atlas scripts/status.sh (v1.1.0): state dir renamed .atlas-dev
# -> .accord-dev; Postgres / app ports are auto-resolved via scripts/lib.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACCORD_ROOT="$ROOT"
STATE_DIR="$ROOT/.accord-dev"

DEV_UI_APP_ID="accord"
DEV_UI_APP_NAME="Accord"
DEV_UI_COLOR="35"
# shellcheck source=scripts/lib/dev-ui.sh
source "$SCRIPT_DIR/lib/dev-ui.sh"
# shellcheck source=scripts/lib/postgres.sh
source "$SCRIPT_DIR/lib/postgres.sh"
# shellcheck source=scripts/lib/ports.sh
source "$SCRIPT_DIR/lib/ports.sh"

# Quiet resolve for status (no step spam); still honors overrides / cache.
# App ports are load-only so status never steals a new free port / rewrites cache.
info() { :; }
warn() { :; }
resolve_pg_port
load_backend_port
load_frontend_port
PGHOST="${PGHOST:-127.0.0.1}"

is_running() {
	local pid="$1"
	[[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

print_pidfile_status() {
	local name="$1"
	local pidfile="$STATE_DIR/$name.pid"
	if [[ ! -f "$pidfile" ]]; then
		ui_kv "$name" "stopped"
		return 0
	fi

	local pid
	pid="$(cat "$pidfile" 2>/dev/null || true)"
	if is_running "$pid"; then
		ui_kv "$name" "running pid=$pid"
	else
		ui_kv "$name" "stale pid=${pid:-unknown}"
	fi
}

print_port_status() {
	local name="$1"
	local port="$2"
	if ! command -v lsof >/dev/null 2>&1; then
		ui_kv "$name port" "unknown (lsof missing)"
	elif port_is_listening "$port"; then
		ui_kv "$name port" "listening on $port"
	else
		ui_kv "$name port" "not listening on $port"
	fi
}

ui_header "Local Status"
print_pidfile_status backend
print_pidfile_status frontend
print_port_status backend "$BACKEND_PORT"
print_port_status frontend "$FRONTEND_PORT"
print_port_status postgres "$PGPORT"
if pg_is_ready_on "$PGPORT"; then
	ui_kv "postgres" "ready at $PGHOST:$PGPORT"
else
	ui_kv "postgres" "not ready at $PGHOST:$PGPORT"
fi
