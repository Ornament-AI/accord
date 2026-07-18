#!/usr/bin/env bash
# Stop Accord dev backend and frontend processes. Postgres is left running.
# Adapted from Atlas scripts/stop.sh (v1.1.0): state dir renamed .atlas-dev ->
# .accord-dev; listen ports come from cache / env (see scripts/lib/ports.sh).

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
info() { ui_step "$1"; }
warn() { ui_warn "$1"; }
die() { ui_die "$1"; }
# shellcheck source=scripts/lib/ports.sh
source "$SCRIPT_DIR/lib/ports.sh"

# Prefer explicit env, then cache, then defaults — never allocate a new free port.
load_backend_port
load_frontend_port

ui_header "Stop Local Dev"

usage() {
	echo "Usage: ./scripts/stop.sh"
}

case "${1:-}" in
	"") ;;
	-h|--help) usage; exit 0 ;;
	*) usage >&2; exit 2 ;;
esac

stopped=0

wait_for_pid_exit() {
	local pid="$1" name="$2"
	for _attempt in {1..25}; do
		if ! kill -0 "$pid" 2>/dev/null; then
			return 0
		fi
		sleep 0.2
	done
	warn "$name (pid $pid) still running"
	return 1
}

stop_pid() {
	local pid="$1" name="$2"
	if ! kill -0 "$pid" 2>/dev/null; then
		return 0
	fi
	kill "$pid" 2>/dev/null || true
	if wait_for_pid_exit "$pid" "$name"; then
		return 0
	fi
	kill -9 "$pid" 2>/dev/null || true
	wait_for_pid_exit "$pid" "$name" || die "failed to stop $name (pid $pid)"
}

stop_pidfile() {
	local name="$1" pid
	local pidfile="$STATE_DIR/$name.pid"
	[[ -f "$pidfile" ]] || return 0
	pid="$(cat "$pidfile" 2>/dev/null || true)"
	if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
		stop_pid "$pid" "$name"
		info "stopped $name (pid $pid)"
		stopped=1
	fi
	rm -f "$pidfile"
}

stop_port() {
	local port="$1" name="$2" pid
	local pids
	# Only free a port when it still matches our (now-removed) pidfile ownership
	# pattern, or when the caller passed an explicit override. Default stop path
	# relies on pidfiles; this is a safety net for orphan listeners on the
	# *cached* Accord port only.
	pids="$(lsof -ti:"$port" 2>/dev/null || true)"
	if [[ -z "$pids" ]]; then
		return 0
	fi
	for pid in $pids; do
		stop_pid "$pid" "$name"
	done
	pids="$(lsof -ti:"$port" 2>/dev/null || true)"
	[[ -z "$pids" ]] || die "failed to stop $name on port $port"
	info "freed port $port ($name)"
	stopped=1
}

stop_pidfile backend
stop_pidfile frontend
# Only reclaim cached Accord ports — never the hard-coded defaults when cache
# pointed elsewhere (avoids killing Atlas on 5173/8000).
if cached="$(read_cached_port backend)" && [[ "$BACKEND_PORT" == "$cached" ]]; then
	stop_port "$BACKEND_PORT" "backend"
fi
if cached="$(read_cached_port frontend)" && [[ "$FRONTEND_PORT" == "$cached" ]]; then
	stop_port "$FRONTEND_PORT" "frontend (vite)"
fi

if [[ "$stopped" -eq 1 ]]; then
	info "Accord app processes stopped"
else
	info "Nothing was running"
fi
warn "Postgres was left running."
