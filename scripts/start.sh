#!/usr/bin/env bash
# Start local dev environment for Accord.
#
# Usage:
#   ./scripts/start.sh                  # backend + frontend
#   ./scripts/start.sh --backend-only   # backend only
#   ./scripts/start.sh --frontend-only  # frontend only, assumes backend is up
# Stop:
#   ./scripts/stop.sh
#
# Adapted from Atlas scripts/start.sh (v1.1.0): env vars renamed to the
# ADR-0003 app-settings matrix (no ATLAS_* app vars), local-Postgres-bootstrap
# vars renamed ATLAS_DB_* -> ACCORD_DB_*, state dir renamed .atlas-dev ->
# .accord-dev. No Firebase/WorkOS dev-auth-bypass DB seeding — Accord has no
# users/auth schema yet (a later auth lane); that step is skipped with a
# clear message until it lands.

set -euo pipefail

START_BACKEND=1
START_FRONTEND=1
for arg in "$@"; do
	case "$arg" in
		--backend-only) START_FRONTEND=0 ;;
		--frontend-only) START_BACKEND=0 ;;
		-h|--help)
			sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*) echo "Unknown flag: $arg" >&2; exit 2 ;;
	esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
STATE_DIR="$ROOT/.accord-dev"
LOG_DIR="$STATE_DIR/logs"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
READY_PATH=/api/readyz

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
APP_USER="${ACCORD_DB_USER:-accord}"
APP_PASSWORD="${ACCORD_DB_PASSWORD:-accord}"
APP_DB="${ACCORD_DB_NAME:-accord}"
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://$APP_USER:$APP_PASSWORD@$PGHOST:$PGPORT/$APP_DB}"
MIGRATIONS_DATABASE_URL="${MIGRATIONS_DATABASE_URL:-$DATABASE_URL}"
CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT}"
DEV_AUTH_BYPASS="${DEV_AUTH_BYPASS:-true}"
SESSION_SECRET_KEY="${SESSION_SECRET_KEY:-dev-only-local-session-secret}"
API_PROXY_TARGET="${API_PROXY_TARGET:-http://127.0.0.1:$BACKEND_PORT}"

mkdir -p "$LOG_DIR"

DEV_UI_APP_ID="accord"
DEV_UI_APP_NAME="Accord"
DEV_UI_COLOR="35"
# shellcheck source=scripts/lib/dev-ui.sh
source "$SCRIPT_DIR/lib/dev-ui.sh"
info() { ui_step "$1"; }
warn() { ui_warn "$1"; }
die() { ui_die "$1"; }
# shellcheck source=scripts/lib/package-manager.sh
source "$SCRIPT_DIR/lib/package-manager.sh"

ui_header "Start Local Dev"

free_port() {
	local port="$1" name="$2" pid
	local pids
	pids="$(lsof -ti:"$port" 2>/dev/null || true)"
	if [[ -z "$pids" ]]; then
		return 0
	fi

	warn "freeing $name on port $port (pids: $pids)"
	for pid in $pids; do
		kill "$pid" 2>/dev/null || true
	done
	sleep 0.5

	pids="$(lsof -ti:"$port" 2>/dev/null || true)"
	for pid in $pids; do
		kill -9 "$pid" 2>/dev/null || true
	done
}

http_status() {
	curl -s -o /dev/null -m 2 -w '%{http_code}' "$1" 2>/dev/null || true
}

backend_ready() {
	[[ "$(http_status "http://127.0.0.1:$BACKEND_PORT$READY_PATH")" == "200" ]]
}

frontend_ready() {
	local status
	status="$(http_status "http://127.0.0.1:$FRONTEND_PORT/")"
	[[ "$status" == "200" || "$status" == "304" ]] || return 1
	[[ "$(http_status "http://127.0.0.1:$FRONTEND_PORT$READY_PATH")" == "200" ]]
}

find_postgres_tool() {
	local tool="$1" prefix formula
	if command -v "$tool" >/dev/null 2>&1; then
		command -v "$tool"
		return 0
	fi

	if command -v brew >/dev/null 2>&1; then
		for formula in postgresql@18 postgresql; do
			prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
			if [[ -n "$prefix" && -x "$prefix/bin/$tool" ]]; then
				printf '%s\n' "$prefix/bin/$tool"
				return 0
			fi
		done
	fi

	return 1
}

if (( START_BACKEND )); then
	if [[ ! -d "$BACKEND" || ! -f "$BACKEND/requirements.txt" ]]; then
		die "backend/ lane not yet landed (missing backend/requirements.txt) — cannot start backend. Run ./scripts/start.sh --frontend-only, or wait for the backend lane."
	fi

	PSQL="$(find_postgres_tool psql || true)"
	[[ -n "$PSQL" ]] || die "psql missing. Install PostgreSQL 18 (e.g. 'brew install postgresql@18') and ensure it is running."

	if [[ ! -f "$BACKEND/.venv/bin/activate" ]]; then
		warn "Creating backend virtualenv..."
		python3 -m venv "$BACKEND/.venv"
		"$BACKEND/.venv/bin/pip" install -q --upgrade pip
		"$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements.txt"
		"$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements-dev.txt"
		info "Backend venv created"
	fi

	if ! PGPASSWORD="$APP_PASSWORD" "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$APP_USER" -d "$APP_DB" -Atqc "SELECT 1" >/dev/null 2>&1; then
		die "Postgres not ready for $APP_DB at $PGHOST:$PGPORT as $APP_USER. Create the role/database (e.g. 'createuser -s $APP_USER && createdb -O $APP_USER $APP_DB') and retry."
	fi
	info "Postgres $APP_DB at $PGHOST:$PGPORT"
fi

if (( START_FRONTEND )); then
	if [[ ! -d "$FRONTEND" || ! -f "$FRONTEND/package.json" ]]; then
		die "frontend/ lane not yet landed (missing frontend/package.json) — cannot start frontend. Run ./scripts/start.sh --backend-only, or wait for the frontend lane."
	fi
	[[ -d "$FRONTEND/node_modules" ]] || die "Frontend deps missing. Run: cd frontend && pnpm install"
fi

backend_up=0
frontend_up=0
backend_ready && backend_up=1
frontend_ready && frontend_up=1

if (( (!START_BACKEND || backend_up) && (!START_FRONTEND || frontend_up) )); then
	(( START_BACKEND )) && info "backend already running on http://127.0.0.1:$BACKEND_PORT"
	(( START_FRONTEND )) && info "frontend already running on http://127.0.0.1:$FRONTEND_PORT"
	exit 0
fi

if (( START_BACKEND && !backend_up )); then
	if lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1; then
		warn "backend port $BACKEND_PORT is in use, but $READY_PATH is not healthy"
	fi
	free_port "$BACKEND_PORT" "backend"
	(
		cd "$BACKEND"
		if [[ -d migrations/versions ]]; then
			info "running alembic upgrade head"
			if ! DATABASE_URL="$DATABASE_URL" MIGRATIONS_DATABASE_URL="$MIGRATIONS_DATABASE_URL" PYTHONPATH=. .venv/bin/alembic upgrade head 2>&1 | tee -a "$LOG_DIR/backend.log"; then
				die "Alembic migration failed (see $LOG_DIR/backend.log)"
			fi
		else
			warn "no migrations found under backend/migrations/versions — skipping alembic upgrade"
		fi

		if [[ "$DEV_AUTH_BYPASS" == "true" ]]; then
			warn "skipping dev-auth-bypass user seed: backend auth/user schema not yet available (WorkOS auth lane has not landed). DEV_AUTH_BYPASS is set but no seed user is created."
		fi

		info "starting backend on http://127.0.0.1:$BACKEND_PORT"
		nohup env \
			DATABASE_URL="$DATABASE_URL" \
			MIGRATIONS_DATABASE_URL="$MIGRATIONS_DATABASE_URL" \
			ENVIRONMENT=development \
			DEV_AUTH_BYPASS="$DEV_AUTH_BYPASS" \
			SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
			CORS_ORIGINS="$CORS_ORIGINS" \
			.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT" \
			</dev/null >>"$LOG_DIR/backend.log" 2>&1 &
		echo $! >"$STATE_DIR/backend.pid"
	)

	for _attempt in {1..30}; do
		backend_ready && break
		sleep 1
	done
	backend_ready || die "Backend failed to start (see $LOG_DIR/backend.log)"
	info "backend ready on http://127.0.0.1:$BACKEND_PORT"
elif (( START_BACKEND )); then
	info "backend already running on http://127.0.0.1:$BACKEND_PORT"
fi

if (( START_FRONTEND )); then
	frontend_up=0
	frontend_ready && frontend_up=1
fi

if (( START_FRONTEND && !frontend_up )); then
	resolve_pnpm
	if lsof -ti:"$FRONTEND_PORT" >/dev/null 2>&1; then
		warn "frontend port $FRONTEND_PORT is in use, but the app/proxy check failed"
	fi
	free_port "$FRONTEND_PORT" "frontend"
	(
		cd "$FRONTEND"
		info "starting frontend on http://127.0.0.1:$FRONTEND_PORT"
		nohup env API_PROXY_TARGET="$API_PROXY_TARGET" \
			VITE_DEV_AUTH_BYPASS="$DEV_AUTH_BYPASS" \
			"${PNPM_CMD[@]}" exec vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort \
			</dev/null >>"$LOG_DIR/frontend.log" 2>&1 &
		echo $! >"$STATE_DIR/frontend.pid"
	)

	for _attempt in {1..20}; do
		frontend_ready && break
		sleep 0.5
	done
	frontend_ready || die "Frontend failed to start or proxy API traffic (see $LOG_DIR/frontend.log)"
	info "frontend ready on http://127.0.0.1:$FRONTEND_PORT"
elif (( START_FRONTEND )); then
	info "frontend already running on http://127.0.0.1:$FRONTEND_PORT"
fi

echo
info "Logs in $LOG_DIR/"
(( START_BACKEND )) && echo "  Backend:  http://127.0.0.1:$BACKEND_PORT"
(( START_FRONTEND )) && echo "  Frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "  Stop:     ./scripts/stop.sh"
